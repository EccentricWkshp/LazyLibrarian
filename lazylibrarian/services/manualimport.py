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

""" Manual Import, like Sonarr's and Radarr's: what is in a download that couldn't be imported
automatically, or in any folder, which book each item looks like, and importing them once the
right book is chosen. Importing goes through the same steps as the post processor, so a manual
import is checked, renamed and recorded exactly like an automatic one.

An item is a folder, or the files of one book in a folder of several: an ebook's formats share
a name, an audiobook's parts are all the audio files that are directly in one folder. A magazine or
comic issue is its title and issue, as a search's download of it is: the magazine's title and the
issue's date or number as the library keeps it, the comic's id and the issue's number """

import contextlib
import logging
import os
import shutil
import threading
import time
import uuid

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from lazylibrarian import database, magreleases, postprocess
from lazylibrarian.comicid import get_issue_num, name_words
from lazylibrarian.config2 import CONFIG
from lazylibrarian.download_client import is_archive_file
from lazylibrarian.filesystem import DIRS, get_directory, path_isdir, path_isfile, safe_copy
from lazylibrarian.formatter import get_list, make_unicode, now, thread_name
from lazylibrarian.magazinescan import get_dateparts
from lazylibrarian.services import InvalidRequestError, NotFoundError, queue, remotepaths
from lazylibrarian.services.history import client_name, download_target, reset_snatched_books
from lazylibrarian.services.history import media_type as download_kind

BOOK_TYPES = ('ebook', 'audiobook')
PERIODICALS = ('magazine', 'comic')
MEDIA_TYPES = BOOK_TYPES + PERIODICALS
LIBRARIES = {'ebook': 'eBook', 'audiobook': 'AudioBook'}
# how sure a guess at an item's book has to be to fill it in
MATCH_SCORE = 80
# how alike an item's name and a queued download's release title are when the item is that download
SAME_NAME = 95
# how long an import waits for the post processor to finish a run it's in the middle of
POSTPROCESS_WAIT = 600
# the start of the rejection for a book that already has its files, the page knows it by this
ALREADY = 'Already in the library:'


def _kind(name: str) -> str:
    """ The media type a file's extension says it is, '' for anything else """
    for kind in ('audiobook', 'ebook', 'comic', 'magazine'):
        if CONFIG.is_valid_booktype(name, booktype=kind):
            return kind
    return 'archive' if is_archive_file(name) else ''


def _folder_kind(folder: str) -> str:
    """ What a folder holds, from the files in it and below it """
    kinds = set()
    for _root, _dirs, files in os.walk(folder):
        kinds.update(_kind(name) for name in files)
    for kind in ('audiobook', 'ebook', 'comic', 'magazine', 'archive'):
        if kind in kinds:
            return kind
    return ''


def _size(path: str) -> int:
    if path_isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(root, name))
    return total


def _label(path: str) -> str:
    """ A file or folder name as words, for matching it to a book """
    name = os.path.basename(path.rstrip('/\\'))
    if path_isfile(path):
        name = os.path.splitext(name)[0]
    return name.replace('.', ' ').replace('_', ' ')


def _items_in(folder: str) -> list[dict]:
    """ The items in a folder: each subfolder, the formats of each ebook and comic or magazine
    file, and the audio files directly in it as one audiobook """
    names = sorted(os.listdir(folder))
    items = []
    loose_audio = []
    by_name = {}
    for name in names:
        path = os.path.join(folder, name)
        if path_isdir(path):
            kind = _folder_kind(path)
            if kind:
                items.append({'path': path, 'files': [], 'kind': kind})
            continue
        kind = _kind(name)
        if kind == 'audiobook':
            loose_audio.append(path)
        elif kind:
            stem = os.path.splitext(name)[0]
            group = by_name.setdefault((stem, kind == 'ebook'), {'path': path, 'files': [], 'kind': kind})
            group['files'].append(path)
    items.extend(by_name.values())
    if loose_audio:
        items.append({'path': folder, 'files': loose_audio, 'kind': 'audiobook'})
    return items


def _library(db) -> list[dict]:
    rows = db.select('SELECT BookID,BookName,AuthorName,books.Status,AudioStatus,BookFile,AudioFile FROM books,authors '
                     'WHERE books.AuthorID=authors.AuthorID')
    return [dict(row) for row in rows]


def _existing_file(book: dict | None, kind: str) -> str:
    """ The library's file for a book of this kind, when it has one, as Sonarr shows an episode's
    existing file. Importing again puts a second copy beside it """
    if not book or kind not in BOOK_TYPES:
        return ''
    path = book.get('AudioFile' if kind == 'audiobook' else 'BookFile') or ''
    return path if path and path_isfile(path) else ''


def _existing_issue(db, kind: str, target: dict | None) -> str:
    """ The library's file for a magazine or comic issue, when it has one """
    if not target or not target.get('issue') or kind not in PERIODICALS:
        return ''
    if kind == 'magazine':
        row = db.match('SELECT IssueFile FROM issues WHERE Title=? AND IssueDate=?', (target['id'], target['issue']))
    else:
        row = db.match('SELECT IssueFile FROM comicissues WHERE ComicID=? AND IssueID=?',
                       (target['id'], target['issue']))
    path = row['IssueFile'] if row else ''
    return path if path and path_isfile(path) else ''


def _periodicals(db) -> dict:
    """ The magazines and comics in the library, to tell which one an item is """
    return {'magazine': [dict(row) for row in db.select('SELECT Title,DateType FROM magazines')],
            'comic': [dict(row) for row in db.select('SELECT ComicID,Title FROM comics')]}


def issue_of(kind: str, label: str, title: str = '', datetype: str = '') -> str:
    """ The issue a name says it is, without the title's words, which may have numbers of their own:
    a magazine's date or number as the library keeps it, a comic's number. '' when it doesn't say """
    words = [word for word in name_words(label) if word not in name_words(title)]
    if kind == 'magazine':
        return _dated(' '.join(words), datetype)
    issue = get_issue_num(words, [])
    return str(issue) if issue != '' else ''


def _dated(text: str, datetype: str = '') -> str:
    """ A magazine issue's date or number as the library keeps it, '' when text isn't one. Without
    a style the parts weren't found, whatever date they make """
    dateparts = get_dateparts(text, datetype=datetype)
    return str(dateparts['dbdate']) if dateparts['style'] and dateparts['dbdate'] else ''


def _periodical(kind: str, row: dict, issue: str = '') -> dict:
    return {'id': row['ComicID'] if kind == 'comic' else row['Title'], 'title': row['Title'], 'author': '',
            'issue': issue, 'media_type': kind}


def _guess_periodical(kind: str, label: str, periodicals: dict) -> tuple[dict | None, int]:
    """ The magazine or comic a name looks like, with its issue, and how sure the guess is """
    best, best_score = None, 0
    for row in periodicals[kind]:
        score = fuzz.token_set_ratio(row['Title'], label, processor=default_process)
        if score > best_score:
            best, best_score = row, score
    if best_score < MATCH_SCORE:
        return None, 0
    return _periodical(kind, best, issue_of(kind, label, best['Title'], best.get('DateType') or '')), best_score


def _wanted_keys(media_type: str, target_id: str, issue: str = '') -> tuple[str, str]:
    """ The BookID and AuxInfo of a download of this, as the searches record them """
    if media_type == 'magazine':
        return target_id, issue
    if media_type == 'comic':
        return f"{target_id}_{issue}", 'comic'
    return target_id, LIBRARIES[media_type]


def _checked_issue(db, media_type: str, target_id: str, issue: str) -> str:
    """ The issue as the library keeps it, raising InvalidRequestError with what to choose when the
    item's book, magazine or comic, or its issue, isn't one there is """
    if media_type not in MEDIA_TYPES:
        raise InvalidRequestError(f"Import as one of {', '.join(MEDIA_TYPES)}")
    if media_type in BOOK_TYPES:
        if not target_id or not db.match('SELECT BookID FROM books WHERE BookID=?', (target_id,)):
            raise InvalidRequestError('Choose the book')
        return ''
    if media_type == 'magazine':
        row = db.match('SELECT Title,DateType FROM magazines WHERE Title=?', (target_id,)) if target_id else None
    else:
        row = db.match('SELECT ComicID FROM comics WHERE ComicID=?', (target_id,)) if target_id else None
    if not row:
        raise InvalidRequestError(f'Choose the {media_type}')
    issue = (issue or '').strip().lstrip('#').strip()
    if not issue:
        raise InvalidRequestError('Choose the issue')
    if media_type == 'magazine':
        datetype = row['DateType'] or ''
        dated = _dated(issue, datetype)
        if not dated:
            raise InvalidRequestError(f"{issue} isn't an issue date or number for {target_id}"
                                      + (f" [{datetype}]" if datetype else ''))
        return magreleases.convert(dated, magreleases.chosen_scheme(db, row['Title']))
    return issue


def suggested_folders() -> list[dict]:
    """ Where downloads are, to start looking for something to import: the download directories and
    the local paths of the remote path mappings """
    found = {}
    for path in [str(get_directory('Download')), *get_list(CONFIG['DOWNLOAD_DIR'], ',')]:
        if path and path_isdir(path):
            found.setdefault(os.path.normpath(path), 'Download directory')
    for mapping in remotepaths.mappings():
        if path_isdir(mapping['LocalPath']):
            found.setdefault(os.path.normpath(mapping['LocalPath']),
                             f"{mapping['Host']} {mapping['RemotePath']}")
    return [{'path': path, 'label': label} for path, label in found.items()]


def _queued_downloads(db) -> list[dict]:
    """ The queued downloads, the most recent first """
    return [dict(row) for row in db.select(
        "SELECT rowid,* FROM wanted WHERE Status='Snatched' AND IFNULL(Source,'')!='MANUAL' "
        "AND IFNULL(AuxInfo,'')!='' ORDER BY rowid DESC")]


def _download_of(path: str, downloads: list[dict]) -> dict | None:
    """ The queued download an item is, by its name being the release title, as Sonarr knows a
    download's folder when it's imported from somewhere else """
    name = default_process(_label(path))
    for row in downloads:
        title = default_process((row['NZBtitle'] or '').replace('.', ' ').replace('_', ' '))
        if name and title and fuzz.ratio(name, title) >= SAME_NAME:
            return row
    return None


def _queued_for(db, keys: tuple[str, str]) -> dict | None:
    """ The queued download of a book or issue, by its BookID and AuxInfo, the most recent if there
    are several. Importing it from a folder completes it, as Sonarr links a manual import to its
    download """
    row = db.match("SELECT rowid,* FROM wanted WHERE Status='Snatched' AND BookID=? AND AuxInfo=? "
                   "AND IFNULL(Source,'')!='MANUAL' ORDER BY rowid DESC", keys)
    return dict(row) if row else None


def _guess(label: str, library: list[dict], kind: str = 'ebook') -> dict | None:
    """ The book a name looks like, scored like the automatic search scores a release. Of books that
    score the same, as the same book from two sources does, one that is wanted or downloading is the
    likelier """
    status = 'AudioStatus' if kind == 'audiobook' else 'Status'
    best, best_score = None, (0, False)
    for book in library:
        author = fuzz.token_set_ratio(book['AuthorName'], label, processor=default_process)
        title = fuzz.token_set_ratio(book['BookName'], label, processor=default_process)
        score = (title if author >= MATCH_SCORE else (author + title) / 2, book[status] in ('Wanted', 'Snatched'))
        if score > best_score:
            best, best_score = book, score
    return best if best_score[0] >= MATCH_SCORE else None


def _book(book: dict | None) -> dict | None:
    if not book:
        return None
    return {'id': book['BookID'], 'title': book['BookName'], 'author': book['AuthorName']}


def _queue_target(db, row) -> dict:
    """ What a queued download was for, as an item's book, magazine or comic: a comic by its id, its
    issue apart, as a comic is chosen """
    what = download_target(db, row)
    target_id = row['BookID'].split('_', 1)[0] if what['media_type'] == 'comic' else row['BookID']
    return {'id': target_id, 'title': what['title'], 'author': what['author'], 'issue': what['issue'],
            'media_type': what['media_type']}


def _client_folder(row) -> str:
    """ Where the download client says a queued download is, through the remote path mappings """
    state = postprocess.BookState.from_db_row(row, CONFIG)
    db = database.DBConnection()
    try:
        state.enrich_with_download_info(db)
    finally:
        db.close()
    return state.download_folder or ''


def candidates(folder: str = '', queue_id=None) -> dict:
    """ The items to import from a folder, or from a queued download's folder, with the book each
    one looks like and anything that would stop it importing. A queued download's items are for
    its book unless another is chosen, and so are the items of a folder that are queued downloads """
    db = database.DBConnection()
    try:
        row = queue._row(db, queue_id) if queue_id else None
        downloads = [row] if row else _queued_downloads(db)
        targets = {}
        for download in downloads:
            target = _queue_target(db, download)
            book = db.match('SELECT BookFile,AudioFile FROM books WHERE BookID=?', (target['id'],)) \
                if target['media_type'] in BOOK_TYPES else None
            targets[download['rowid']] = (target, dict(book) if book else {})
        library = _library(db) if not row else []
        periodicals = _periodicals(db) if not row else {'magazine': [], 'comic': []}
        own_folder = False
        if row and not folder:
            folder = _client_folder(row)
            if not folder:
                return {'folder': '', 'items': [], 'error': f"{client_name(row['Source'])} did not say where "
                                                            f"{row['NZBtitle']} is. Choose the folder it is in"}
            if not path_isdir(folder):
                hint = remotepaths.explain_missing(row['Source'], folder)
                return {'folder': folder, 'items': [], 'error': f"[{folder}] was not found. {hint}".strip()}
            own_folder = True
        folder = (folder or '').strip()
        if not folder or not os.path.isabs(folder):
            raise InvalidRequestError('Choose a folder, as a full path')
        if not path_isdir(folder):
            raise NotFoundError(f'[{folder}] was not found')
        if own_folder:
            # a queued download's own folder is one item, the way the post processor takes it
            units = [{'path': folder, 'files': [], 'kind': _folder_kind(folder)}]
            base = os.path.dirname(folder.rstrip('/\\'))
        else:
            units, base = _items_in(folder), folder
        found = [_candidate(db, unit, base, row, downloads, targets, library, periodicals) for unit in units]
    finally:
        db.close()
    return {'folder': folder, 'items': found, 'error': ''}


def _candidate(db, unit: dict, base: str, row, downloads, targets, library, periodicals) -> dict:
    """ One item to import, with what it looks like and anything that would stop it importing """
    label = _label(unit['path'])
    download = row or _download_of(unit['path'], downloads)
    target, target_files = targets[download['rowid']] if download else (None, {})
    kind = target['media_type'] if target else unit['kind']
    if kind not in MEDIA_TYPES:
        kind = 'ebook'
    guess = None if target or kind not in BOOK_TYPES else _guess(label, library, kind)
    book = target if target else _book(guess)
    if not target and kind in ('ebook', 'magazine', 'comic'):
        # a pdf or epub may be a magazine issue, when it looks like one more than a book
        for periodical in PERIODICALS:
            if kind != periodical and not (kind == 'ebook' and periodical == 'magazine'):
                continue
            found, _score = _guess_periodical(periodical, label, periodicals)
            if found and (kind == periodical or (not guess and found['issue'])):
                kind, book = periodical, found
                break
    existing = _existing_file(target_files if target else guess, kind) or _existing_issue(db, kind, book)
    first = unit['files'][0] if unit['files'] else unit['path']
    item = {'path': unit['path'], 'files': unit['files'], 'relative_path': os.path.relpath(first, base),
            'size': sum(_size(name) for name in unit['files'] or [unit['path']]), 'media_type': kind,
            'book': book, 'queue_id': download['rowid'] if download else None, 'rejections': [],
            # the issue the name says, to start from when it's chosen as a magazine or comic instead
            'issues': {} if unit['kind'] == 'audiobook' else
            {periodical: issue_of(periodical, label) for periodical in PERIODICALS}}
    if unit['kind'] not in (kind, 'archive') and not (unit['kind'] == 'ebook' and kind == 'magazine'):
        item['rejections'].append(f"No {kind} files found, only {unit['kind'] or 'other'} files")
    if not book:
        item['rejections'].append(f"Choose the {'book' if kind in BOOK_TYPES else kind}")
    elif kind in PERIODICALS and not book.get('issue'):
        item['rejections'].append('Choose the issue')
    if existing:
        # an audiobook's parts are all replaced, an ebook's other formats stay, an issue has one file
        replaces = 'importing replaces the same format' if kind == 'ebook' else 'importing replaces it'
        item['rejections'].append(f"{ALREADY} {existing}, {replaces}")
    return item


def search_titles(media_type: str, term: str, limit: int = 25) -> list[dict]:
    """ Magazines or comics in the library with every word of term in their title, to choose an
    item's, each with its date type, what a magazine's issues are known by """
    if media_type not in PERIODICALS:
        raise InvalidRequestError(f"Search magazines or comics, not {media_type}")
    words = [word for word in (term or '').split() if word]
    if not words:
        return []
    where = ' AND '.join(['Title LIKE ?'] * len(words))
    args = [f'%{word}%' for word in words]
    db = database.DBConnection()
    try:
        if media_type == 'magazine':
            rows = db.select(f'SELECT Title,DateType FROM magazines WHERE {where} ORDER BY Title LIMIT ?',
                             (*args, limit))
        else:
            rows = db.select(f'SELECT ComicID,Title FROM comics WHERE {where} ORDER BY Title LIMIT ?', (*args, limit))
    finally:
        db.close()
    return [{**_periodical(media_type, dict(row)), 'date_type': row['DateType'] if media_type == 'magazine' else ''}
            for row in rows]


def search_books(term: str, limit: int = 25) -> list[dict]:
    """ Library books whose title or author has every word of term, to choose an item's book """
    words = [word for word in (term or '').split() if word]
    if not words:
        return []
    where = ' AND '.join(['(BookName LIKE ? OR AuthorName LIKE ?)'] * len(words))
    args = [arg for word in words for arg in (f'%{word}%', f'%{word}%')]
    db = database.DBConnection()
    try:
        rows = db.select(f'SELECT BookID,BookName,AuthorName,books.Status,AudioStatus FROM books,authors '
                         f'WHERE books.AuthorID=authors.AuthorID AND {where} ORDER BY AuthorName,BookName LIMIT ?',
                         (*args, limit))
    finally:
        db.close()
    return [{**_book(dict(row)), 'status': row['Status'], 'audio_status': row['AudioStatus']} for row in rows]


def get_book(book_id: str) -> dict:
    """ A library book, with its author's id to link to """
    db = database.DBConnection()
    try:
        row = db.match('SELECT BookID,BookName,AuthorName,books.AuthorID,books.Status,AudioStatus FROM books,authors '
                       'WHERE books.AuthorID=authors.AuthorID AND BookID=?', (book_id,))
    finally:
        db.close()
    if not row:
        raise NotFoundError(f'No book {book_id}')
    return {**_book(dict(row)), 'author_id': row['AuthorID'], 'status': row['Status'],
            'audio_status': row['AudioStatus']}


def _wait_for_postprocessor():
    """ Imports and the post processor change the same downloads, so they take turns: an import
    waits for a run that is going, and calls its thread POSTPROCESS so no run starts meanwhile """
    deadline = time.time() + POSTPROCESS_WAIT
    me = threading.current_thread()
    while any(t.name == 'POSTPROCESS' and t is not me for t in threading.enumerate()):
        if time.time() > deadline:
            raise InvalidRequestError('The post processor is still running, try again when it has finished')
        time.sleep(1)
    thread_name('POSTPROCESS')


def _working_copy(files: list[str]) -> str:
    """ A folder of their own for some of the files in a folder, so only they are imported. The
    post processor deletes .unpack folders, its own working copies, when it's done """
    work = os.path.join(DIRS.TMPDIR, f"manualimport-{uuid.uuid4().hex[:12]}.unpack")
    os.makedirs(work)
    for path in files:
        safe_copy(path, os.path.join(work, os.path.basename(path)))
    return work


def _manual_row(db, keys: tuple[str, str], name) -> dict:
    """ A wanted row, with its BookID and AuxInfo, for a download that LazyLibrarian didn't ask for,
    as process_book makes """
    url = f"manual:{uuid.uuid4().hex}"
    book_id, aux_info = keys
    db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,Source,"
              "DownloadID,DLResult,Completed) VALUES (?,?,?,?,'Manual','Snatched',0,?,'','MANUAL','','',0)",
              (book_id, url, name, now(), aux_info))
    return dict(db.match('SELECT rowid,* FROM wanted WHERE NZBurl=?', (url,)))


def import_item(item: dict) -> str:
    """ Import one item: {'path', 'files', 'media_type', 'book_id', 'issue', 'queue_id'}, book_id
    a magazine's title or a comic's id for an issue of one. Returns what was imported, raises
    InvalidRequestError with the reason when it can't be. A queued download that doesn't import is
    blocked with the reason, as if the post processor had tried """
    logger = logging.getLogger(__name__)
    path, files = item.get('path') or '', item.get('files') or []
    media_type, book_id, queue_id = item.get('media_type') or '', item.get('book_id') or '', item.get('queue_id')
    issue = item.get('issue') or ''
    if not path or not (path_isdir(path) or path_isfile(path)):
        raise InvalidRequestError(f'[{path}] was not found')
    if path_isfile(path) and not files:
        files = [path]
    db = database.DBConnection()
    work = ''
    linked = False
    try:
        if not queue_id and book_id:
            keys = _wanted_keys(media_type, book_id, _checked_issue(db, media_type, book_id, issue))
            queued = _queued_for(db, keys)
            if queued:
                queue_id, linked = queued['rowid'], True
                logger.info(f"Importing {path} for the queued download {queued['NZBtitle']}")
        if queue_id:
            row = queue._row(db, queue_id)
            was = download_kind(row['AuxInfo'])
            # an ebook or audiobook download is either, of any book. Unless something else is chosen, it's
            # what it was for, a book's download as the type chosen
            target = book_id or (row['BookID'] if media_type in BOOK_TYPES and was in BOOK_TYPES else '')
            keys = (row['BookID'], row['AuxInfo'])
            # the download's own book or issue is as its search recorded it, anything else is checked
            if target and _wanted_keys(media_type, target, issue.strip()) != keys:
                keys = _wanted_keys(media_type, target, _checked_issue(db, media_type, target, issue))
            if keys != (row['BookID'], row['AuxInfo']):
                if media_type != was and not (media_type in BOOK_TYPES and was in BOOK_TYPES):
                    raise InvalidRequestError(f"A {was} download can only be imported as another {was}"
                                              if was in PERIODICALS else 'Only a book or audiobook can be chosen instead')
                # the download was something else, the book it was for is wanted again
                reset_snatched_books(db, [row])
                db.action('UPDATE wanted SET BookID=?,AuxInfo=? WHERE rowid=?', (*keys, queue_id))
                row = queue._row(db, queue_id)
        else:
            keys = _wanted_keys(media_type, book_id, _checked_issue(db, media_type, book_id, issue))
            row = _manual_row(db, keys, _label(files[0] if files else path))
        folder = _working_copy(files) if files else path
        work = folder if files else ''

        state = postprocess.BookState.from_db_row(row, CONFIG)
        # just the book's title, the folder is chosen rather than asked of the download client
        state.source = ''
        state.enrich_with_download_info(db)
        state.source = row['Source']
        state.download_folder = folder
        logger.info(f"Manual import of {path} as {LIBRARIES.get(media_type, media_type)} {row['BookID']}")
        imported = postprocess._search_in_known_location(state, row['Source'] == 'MANUAL', db, logger,
                                                         logging.getLogger('special.fuzz'))
        if imported:
            if files and not CONFIG.get_bool('DESTINATION_COPY') and not state.is_torrent():
                for name in files:
                    try:
                        os.remove(name)
                    except OSError as why:
                        logger.warning(f"Imported, but could not remove {name}: {why}")
            done = db.match('SELECT DLResult FROM wanted WHERE rowid=?', (row['rowid'],))
            return make_unicode(done['DLResult']) if done else 'Imported'
        reason = postprocess._block_reason(state)
        if row['Source'] == 'MANUAL':
            db.action('DELETE FROM wanted WHERE rowid=?', (row['rowid'],))
        elif not linked:
            # a queued download's own files didn't import. Other files that didn't are no reason to
            # block it
            postprocess._block_import(db, state, logger)
        raise InvalidRequestError(reason)
    finally:
        db.close()
        if work and path_isdir(work):
            shutil.rmtree(work, ignore_errors=True)


def import_items(items: list[dict], progress=None) -> list[dict]:
    """ Import each item in turn, returns each one's result. progress(message) is told as each starts """
    if not items:
        raise InvalidRequestError('Choose something to import')
    _wait_for_postprocessor()
    results = []
    for number, item in enumerate(items, start=1):
        name = os.path.basename((item.get('files') or [item.get('path') or ''])[0])
        if progress:
            progress(f"Importing {name} ({number} of {len(items)})")
        try:
            results.append({'path': item.get('path'), 'imported': True, 'message': import_item(item)})
        except (InvalidRequestError, NotFoundError) as why:
            results.append({'path': item.get('path'), 'imported': False, 'message': str(why)})
    return results
