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
        bool(body.get('search')), progress=lambda text: _update(command, message=text))
    return message


def _refresh_author(command: dict, body: dict) -> str:
    from lazylibrarian.services import addnew  # it imports most of LazyLibrarian
    return addnew.refresh_author(body.get('author_id') or '', progress=lambda text: _update(command, message=text))


def _author_search(command: dict, body: dict) -> str:
    from lazylibrarian.services import library  # it imports most of LazyLibrarian
    found = library.wanted_books(body.get('author_id') or '')
    if not found:
        command['result'] = {'found': 0}
        return 'None of their books are wanted'
    count, message = wanted.search_books(found, progress=lambda text: _update(command, message=text))
    command['result'] = {'found': count}
    return message


def _library_scan(command: dict, body: dict) -> str:
    from lazylibrarian.services import system  # it imports most of LazyLibrarian
    _update(command, message='Scanning')
    return system.scan_now(body.get('media_type') or '', body.get('title') or '', body.get('comic_id') or '')


def _refresh_book(command: dict, body: dict) -> str:
    from lazylibrarian.services import addnew  # it imports most of LazyLibrarian
    return addnew.refresh_book(body.get('book_id') or '', progress=lambda text: _update(command, message=text))


HANDLERS: dict[str, Callable[[dict, dict], str]] = {'ManualImport': _manual_import, 'BookSearch': _book_search,
                                                    'MissingBookSearch': _missing_book_search,
                                                    'CutoffUnmetSearch': _cutoff_unmet_search,
                                                    'ClearBlocklist': _clear_blocklist, 'RunTask': _run_task,
                                                    'Backup': _backup, 'ApplicationUpdate': _application_update,
                                                    'AddAuthor': _add_author, 'AddBook': _add_book,
                                                    'RefreshAuthor': _refresh_author, 'RefreshBook': _refresh_book,
                                                    'AuthorSearch': _author_search, 'LibraryScan': _library_scan}
# what System, Tasks calls each command
TITLES = {'ManualImport': 'Manual Import', 'BookSearch': 'Book Search', 'MissingBookSearch': 'Missing Book Search',
          'CutoffUnmetSearch': 'Upgrade Search',
          'ClearBlocklist': 'Clear Blocklist', 'Backup': 'Backup', 'ApplicationUpdate': 'Update',
          'AddAuthor': 'Add Author', 'AddBook': 'Add Book', 'RefreshAuthor': 'Refresh Author',
          'RefreshBook': 'Refresh Book', 'AuthorSearch': 'Author Search', 'LibraryScan': 'Library Scan'}


def _run(command: dict, body: dict):
    logger = logging.getLogger(__name__)
    _update(command, status='started', started=_now())
    try:
        message = HANDLERS[command['name']](command, body)
        _update(command, status='completed', message=message, ended=_now())
    except (InvalidRequestError, NotFoundError) as why:
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
