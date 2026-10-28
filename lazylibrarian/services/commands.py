#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

""" Commands, like Sonarr's: work that takes a while runs in the background, and the web page
asks how it is going and how it ended, with a message to show for it. They are kept in memory,
the most recent first, until LazyLibrarian restarts """

import itertools
import logging
import os
import threading
import traceback
from collections.abc import Callable
from datetime import UTC, datetime

from lazylibrarian.formatter import plural
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    ServiceError,
    blocklist,
    events,
    manualimport,
    tasks,
    wanted,
)

KEEP = 100
_commands: dict[int, dict] = {}
_ids = itertools.count(1)
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def _update(command: dict, **changes):
    """ Change a command, and tell the pages listening, as Sonarr's command updates do """
    command.update(changes)
    events.publish('command', dict(command))


def _manual_import(command: dict, body: dict) -> str:
    def progress(message):
        _update(command, message=message)

    results = manualimport.import_items(body.get('files') or [], progress=progress)
    command['result'] = results
    imported = sum(1 for result in results if result['imported'])
    failed = [result['message'] for result in results if not result['imported']]
    message = f"Imported {imported} of {len(results)}"
    if failed:
        message += f". {'; '.join(failed)}"
    if not imported:
        raise InvalidRequestError(message)
    return message


def _book_search(command: dict, body: dict) -> str:
    def progress(message):
        _update(command, message=message)

    found, message = wanted.search_books(body.get('books') or [], progress=progress)
    command['result'] = {'found': found}
    return message


def _missing_book_search(command: dict, body: dict) -> str:
    def progress(message):
        _update(command, message=message)

    found, message = wanted.search_books([], progress=progress)
    command['result'] = {'found': found}
    return message


def _cutoff_unmet_search(command: dict, body: dict) -> str:
    def progress(message):
        _update(command, message=message)

    found, message = wanted.search_upgrades(body.get('books') or [], progress=progress)
    command['result'] = {'found': found}
    return message


def _clear_blocklist(command: dict, body: dict) -> str:
    cleared = blocklist.clear()
    command['result'] = {'cleared': cleared}
    return f"Cleared {cleared} {plural(cleared, 'release')} from the blocklist"


def _run_task(command: dict, body: dict) -> str:
    return tasks.run(body.get('task') or '')


def _backup(command: dict, body: dict) -> str:
    from lazylibrarian.common import dbbackup  # it imports most of LazyLibrarian
    path, error = dbbackup('manual')
    if not path:
        raise InvalidRequestError(f"The backup failed: {error}")
    return f"Backed up to {os.path.basename(path)}"


def _application_update(command: dict, body: dict) -> str:
    from lazylibrarian.services import updates  # it imports most of LazyLibrarian
    return updates.install()


def _add_author(command: dict, body: dict) -> str:
    from lazylibrarian.services import addnew  # it imports most of LazyLibrarian
    message, command['result'] = addnew.add_author(
        body.get('author_id') or '', body.get('author_name') or '', body.get('monitor') or 'new',
        body.get('media_types'), bool(body.get('search')), progress=lambda text: _update(command, message=text))
    return message


def _add_book(command: dict, body: dict) -> str:
    from lazylibrarian.services import addnew  # it imports most of LazyLibrarian
    message, command['result'] = addnew.add_book(
        body.get('book_id') or '', body.get('source') or '', body.get('author_id') or '', body.get('media_types'),
        bool(body.get('search')), progress=lambda text: _update(command, message=text), title=body.get('title') or '')
    return message


def _refresh_author(command: dict, body: dict) -> str:
    from lazylibrarian.services import addnew  # it imports most of LazyLibrarian
    return addnew.refresh_author(body.get('author_id') or '', progress=lambda text: _update(command, message=text))


def _author_search(command: dict, body: dict) -> str:
    from lazylibrarian.services import authors, library  # they import most of LazyLibrarian
    author_id = body.get('author_id') or ''
    name = authors.get_author(author_id)['AuthorName']
    _update(command, message=f"Finding {name}'s wanted books")
    found = library.wanted_books(author_id)
    if not found:
        command['result'] = {'found': 0}
        return f"None of {name}'s books are wanted"
    count, message = wanted.search_books(found, progress=lambda text: _update(command, message=f"{text} by {name}"))
    command['result'] = {'found': count}
    return f"{name}: {message}"


def _library_scan(command: dict, body: dict) -> str:
    from lazylibrarian.config2 import CONFIG
    from lazylibrarian.services import magazines, system  # they import most of LazyLibrarian
    message = system.scan_now(body.get('media_type') or '', body.get('title') or '', body.get('comic_id') or '',
                              progress=lambda text: _update(command, message=text))
    if body.get('media_type') == 'magazine' and CONFIG.get_bool('MAG_FULLTEXT'):
        # the issues it found go in the search index
        found = magazines.index_issues(progress=lambda text: _update(command, message=text))
        if found['indexed']:
            message += f", {found['items']} {plural(found['items'], 'issue')} can be searched"
    return message


def _refresh_book(command: dict, body: dict) -> str:
    from lazylibrarian.services import addnew  # it imports most of LazyLibrarian
    return addnew.refresh_book(body.get('book_id') or '', progress=lambda text: _update(command, message=text))


def _issues(body: dict) -> list[str]:
    """ The magazine issues a command is for: those asked for, else every issue of the magazine """
    from lazylibrarian.services import magazines  # it imports most of LazyLibrarian
    if body.get('ids'):
        return list(body['ids'])
    if body.get('title'):
        return [issue['IssueID'] for issue in magazines.list_issues(body['title'], limit=None).items]
    raise InvalidRequestError('Which issues?')


def _done(what: str, passed: int, failed: int) -> str:
    message = f"{what} {passed} {plural(passed, 'issue')}"
    if failed:
        message += f", {failed} failed, see the log"
    if not passed and failed:
        raise InvalidRequestError(message)
    return message


def _issue_covers(command: dict, body: dict) -> str:
    """ Make issues' covers again, from page (or the magazine's cover page). A comic's are
    comicid_issueid """
    from lazylibrarian.services import comics, magazines  # they import most of LazyLibrarian
    page = int(body.get('page') or 0)
    if body.get('media_type') == 'comic':
        passed = failed = 0
        ids = body.get('ids') or []
        for number, item in enumerate(ids, start=1):
            _update(command, message=f"Making cover {number} of {len(ids)}")
            comic_id, _, issue_id = item.partition('_')
            try:
                comics.set_issue_cover(comic_id, issue_id, page or 1)
                passed += 1
            except ServiceError:
                failed += 1
        return _done('Made the covers of', passed, failed)
    ids = _issues(body)
    if not page:
        page = magazines.cover_page(body.get('title') or '', ids[0] if ids else '')
    _update(command, message=f"Making {len(ids)} {plural(len(ids), 'cover')} from page {page}")
    passed, failed, _title = magazines.mark_issues(f'reCover{page}', ids)
    return _done(f'Made covers from page {page} for', passed, failed)


def _swap_cover(command: dict, body: dict) -> str:
    """ Move a page of magazine issues' PDFs to the front, so it's the cover """
    from lazylibrarian.services import magazines  # it imports most of LazyLibrarian
    ids = _issues(body)
    page = int(body.get('page') or 2)
    _update(command, message=f"Moving page {page} to the front of {len(ids)} {plural(len(ids), 'issue')}")
    passed, failed, _title = magazines.mark_issues('coverswap', ids, swap_page=page)
    return _done(f'Moved page {page} to the front of', passed, failed)


def _tag_issues(command: dict, body: dict) -> str:
    """ Write the magazine's title, issue date and genres into issues' PDFs """
    from lazylibrarian.services import magazines  # it imports most of LazyLibrarian
    ids = _issues(body)
    _update(command, message=f"Tagging {len(ids)} {plural(len(ids), 'issue')}")
    passed, failed, _title = magazines.mark_issues('tag', ids)
    return _done('Tagged', passed, failed)


def _refresh_magazine(command: dict, body: dict) -> str:
    """ Take a magazine's details from Wikidata: the item given, the one it's linked to, or the one
    called exactly its title """
    from lazylibrarian.services import magazines  # it imports most of LazyLibrarian
    title = body.get('title') or ''
    _update(command, message=f"Looking {title} up on Wikidata")
    if body.get('wikidata_id'):
        return magazines.set_wikidata(title, body['wikidata_id'])
    return magazines.refresh_magazine(title)


def _apply_retention(command: dict, body: dict) -> str:
    """ Delete the issues a magazine (title), or every magazine, doesn't keep """
    from lazylibrarian.services import magazines  # it imports most of LazyLibrarian
    title = body.get('title') or ''
    _update(command, message=f"Deleting the issues {title or 'the magazines'} doesn't keep")
    deleted = magazines.apply_retention(title) if title else magazines.apply_all_retention()
    return f"Deleted {deleted} {plural(deleted, 'issue')} {title or 'the magazines'} doesn't keep" if deleted \
        else f"{title or 'The magazines'} keeps every issue there is"


def _renumber_issues(command: dict, body: dict) -> str:
    """ Put a magazine's (title) issues in the numbering chosen for it """
    from lazylibrarian.services import magazines  # it imports most of LazyLibrarian
    title = body.get('title') or ''
    done = magazines.renumber_issues(title, progress=lambda message: _update(command, message=message))
    message = f"Renumbered {done['renumbered']} {plural(done['renumbered'], 'issue')} of {title}"
    if done['left']:
        message += f", left {len(done['left'])} as {'it was' if len(done['left']) == 1 else 'they were'}: " \
                   f"{'; '.join(done['left'])}"
    return message


def _index_issues(command: dict, body: dict) -> str:
    """ Put the words of the issues that aren't, or whose files changed, in the search index """
    from lazylibrarian.services import magazines  # it imports most of LazyLibrarian
    found = magazines.index_issues(progress=lambda text: _update(command, message=text))
    command['result'] = found
    return (f"Read the words of {found['indexed']} {plural(found['indexed'], 'issue')}, {found['items']} "
            f"{plural(found['items'], 'issue')} can be searched, {found['pages']} {plural(found['pages'], 'page')}")


def _refresh_languages(command: dict, body: dict) -> str:
    from lazylibrarian.services import books  # it imports most of LazyLibrarian
    return books.refresh_languages_now(progress=lambda text: _update(command, message=text))


HANDLERS: dict[str, Callable[[dict, dict], str]] = {'ManualImport': _manual_import, 'BookSearch': _book_search,
                                                    'MissingBookSearch': _missing_book_search,
                                                    'CutoffUnmetSearch': _cutoff_unmet_search,
                                                    'ClearBlocklist': _clear_blocklist, 'RunTask': _run_task,
                                                    'Backup': _backup, 'ApplicationUpdate': _application_update,
                                                    'AddAuthor': _add_author, 'AddBook': _add_book,
                                                    'RefreshAuthor': _refresh_author, 'RefreshBook': _refresh_book,
                                                    'AuthorSearch': _author_search, 'LibraryScan': _library_scan,
                                                    'RefreshLanguages': _refresh_languages,
                                                    'IssueCovers': _issue_covers, 'SwapCover': _swap_cover,
                                                    'TagIssues': _tag_issues, 'RefreshMagazine': _refresh_magazine,
                                                    'ApplyRetention': _apply_retention, 'IndexIssues': _index_issues,
                                                    'RenumberIssues': _renumber_issues}
# what System, Tasks calls each command
TITLES = {'ManualImport': 'Manual Import', 'BookSearch': 'Book Search', 'MissingBookSearch': 'Missing Book Search',
          'CutoffUnmetSearch': 'Upgrade Search',
          'ClearBlocklist': 'Clear Blocklist', 'Backup': 'Backup', 'ApplicationUpdate': 'Update',
          'AddAuthor': 'Add Author', 'AddBook': 'Add Book', 'RefreshAuthor': 'Refresh Author',
          'RefreshBook': 'Refresh Book', 'AuthorSearch': 'Author Search', 'LibraryScan': 'Library Scan',
          'RefreshLanguages': tasks.MANUAL['RefreshLanguages'][0], 'IssueCovers': 'Make Covers',
          'SwapCover': 'Swap Cover Page', 'TagIssues': 'Tag Issues', 'RefreshMagazine': 'Refresh Magazine',
          'ApplyRetention': 'Delete Old Issues', 'IndexIssues': 'Index Issues for Search',
          'RenumberIssues': 'Renumber Issues'}


def _run(command: dict, body: dict):
    logger = logging.getLogger(__name__)
    _update(command, status='started', started=_now())
    try:
        message = HANDLERS[command['name']](command, body)
        _update(command, status='completed', message=message, ended=_now())
    except ServiceError as why:
        _update(command, status='failed', message=str(why), ended=_now())
    except Exception as why:
        logger.error(f"{command['name']} failed: {traceback.format_exc()}")
        _update(command, status='failed', message=f"{type(why).__name__}: {why}", ended=_now())


def start(name: str, body: dict) -> dict:
    """ Start a command in the background, returns it as it is now """
    if name not in HANDLERS:
        raise InvalidRequestError(f"There is no command {name}, there is {', '.join(HANDLERS)}")
    # a task is known by its name in Settings, one that isn't there is NotFound before it starts
    title = tasks.task_name(body.get('task') or '') if name == 'RunTask' else TITLES.get(name, name)
    command = {'id': next(_ids), 'name': name, 'title': title, 'status': 'queued', 'message': '',
               'queued': _now(), 'started': None, 'ended': None, 'result': None}
    with _lock:
        _commands[command['id']] = command
        for old in sorted(_commands)[:-KEEP]:
            del _commands[old]
    events.publish('command', dict(command))
    threading.Thread(target=_run, args=(command, body), name=f"COMMAND-{name.upper()}", daemon=True).start()
    return dict(command)


def get(command_id) -> dict:
    with _lock:
        command = _commands.get(int(command_id))
    if not command:
        raise NotFoundError(f'No command {command_id}')
    return dict(command)


def list_commands() -> list[dict]:
    with _lock:
        return [dict(command) for command in sorted(_commands.values(), key=lambda c: -c['id'])]
