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

""" Readarr's v1 API, for the apps that manage Readarr (nzb360, LunaSea, Managarr...), as a
translation of the library: its authors, books, files, series, queue, history, wanted, searches and
settings in Readarr's shapes, and its actions (monitoring, adding, searching, grabbing, removing)
done by LazyLibrarian's own services. It sits beside LazyLibrarian's own /api/v1 and changes
nothing of it.

Readarr has one wanted state per book, LazyLibrarian one for each format, so there's an API for
each: /readarr/ebook and /readarr/audio (and /readarr, the eBooks), each its own Readarr to the
app. Readarr's paths are matched whatever their case, as Readarr's are; webapp.py lower-cases them
on the way in, so the paths here are lower case. What Readarr has that LazyLibrarian hasn't (custom
formats, delay profiles, import lists...) is there but empty, so an app goes on. Paths an app asks
for that aren't here at all are logged, so they can be added """

import contextlib
import datetime
import logging
import os
import platform
import shutil
import threading
import time

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

import lazylibrarian
from lazylibrarian import database, quality
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import check_float, check_int, get_list, surname_first
from lazylibrarian.readarr.ids import AUDIOBOOK, AUTHOR, BOOK, api_id, api_ids, item_id
from lazylibrarian.services import (
    ServiceError,
    blocklist,
    commands,
    health,
    history,
    library,
    profiles,
    queue,
    releases,
    remotepaths,
    system,
    tasks,
    wanted,
)
from lazylibrarian.services.library import audio_parts

# what an app is told it's talking to: the last Readarr, which the apps know
READARR_VERSION = '0.4.18.2805'
# each format's book status and file columns, library setting and quality media type
LIBRARIES = {
    'ebook': {'status': 'Status', 'file': 'BookFile', 'folder': 'EBOOK_DIR', 'name': 'eBooks', 'aux': 'eBook'},
    'audiobook': {'status': 'AudioStatus', 'file': 'AudioFile', 'folder': 'AUDIO_DIR', 'name': 'Audiobooks',
                  'aux': 'AudioBook'},
}
MONITORED = ('Wanted', 'Snatched', 'Open', 'Have')
OWNED = ('Open', 'Have')
SERIES = 'series'
# Readarr's numbers for its qualities, ours that it hasn't got are numbered from 100
QUALITY_IDS = {'unknown': 0, 'pdf': 1, 'mobi': 2, 'epub': 3, 'azw3': 4, 'mp3': 10, 'flac': 11, 'm4b': 12}
UNKNOWN_AUDIO = 13
# Readarr's history events, by ours
EVENTS = {'grabbed': 'grabbed', 'downloadFolderImported': 'bookFileImported', 'downloadFailed': 'downloadFailed'}
# Readarr's monitor choices for a new author, as LazyLibrarian's
MONITOR_CHOICES = {'all': 'all', 'missing': 'all', 'future': 'new', 'latest': 'new', 'first': 'new',
                   'existing': 'new', 'none': 'none'}
# the info source each looked up author and book came from, by its id, for adding it after
_looked_up: dict[str, tuple[float, str]] = {}
_looked_up_lock = threading.Lock()
LOOKUP_KEEP = 3600
# Readarr settings pages that LazyLibrarian has no counterpart of, answered with nothing in them
EMPTY_LISTS = ('customfilter', 'customformat', 'delayprofile', 'importlist', 'importlistexclusion', 'metadata',
               'notification', 'releaseprofile', 'indexerflag', 'tag', 'tag/detail', 'system/backup', 'update',
               'rename', 'retag', 'indexer', 'downloadclient', 'filesystem/mediafiles', 'qualitydefinition',
               'localization', 'system/routes')
EMPTY_SCHEMAS = ('customformat/schema', 'indexer/schema', 'downloadclient/schema', 'importlist/schema',
                 'notification/schema', 'metadata/schema')


def _iso(date) -> str | None:
    """ A date as Readarr gives them, 2026-10-27T00:00:00Z, None when there's none. A year or a year
    and month is its first day """
    text = str(date or '').strip()
    if not text or text.startswith('0000'):
        return None
    text = text.replace(' ', 'T')
    if len(text) == 4:
        text += '-01-01'
    elif len(text) == 7:
        text += '-01'
    if 'T' not in text:
        text += 'T00:00:00'
    return text[:19] + 'Z'


def _quality_id(name: str, media_type: str) -> int:
    if name in QUALITY_IDS and not (name == 'unknown' and media_type == 'audiobook'):
        return QUALITY_IDS[name]
    if name == 'unknown':
        return UNKNOWN_AUDIO
    known = quality.qualities(media_type)
    return 100 + (known.index(name) if name in known else len(known))


def _quality(name: str, media_type: str) -> dict:
    return {'quality': {'id': _quality_id(name, media_type), 'name': quality.name(name)},
            'revision': {'version': 1, 'real': 0, 'isRepack': False}}


def _release_quality(title: str, media_type: str) -> dict:
    return _quality((quality.of_release(title, media_type) or ['unknown'])[0], media_type)


def _size(path: str, media_type: str) -> int:
    """ The size of a book's file, all of an audiobook's parts """
    try:
        if not path or not os.path.isfile(path):
            return 0
        if media_type == 'audiobook':
            return sum(os.path.getsize(part) for part in audio_parts(path))
        return os.path.getsize(path)
    except OSError:
        return 0


def _page(records: list, page: int, page_size: int, sort_key: str, direction: str) -> dict:
    """ Readarr's paged list """
    page, page_size = max(page, 1), max(page_size, 1)
    return {'page': page, 'pageSize': page_size, 'sortKey': sort_key, 'sortDirection': direction,
            'totalRecords': len(records), 'records': records[(page - 1) * page_size:page * page_size]}


def _remember_lookup(item: str, source: str):
    now = time.monotonic()
    with _looked_up_lock:
        for key in [key for key, (when, _) in _looked_up.items() if now - when > LOOKUP_KEEP]:
            del _looked_up[key]
        _looked_up[item] = (now, source)


def _looked_up_source(item: str) -> str:
    with _looked_up_lock:
        return _looked_up.get(item, (0, ''))[1]


def _command(command: dict, body: dict | None = None) -> dict:
    """ A command as Readarr's: its name, state and when it was queued, started and ended """
    state = command['status']
    return {'id': command['id'], 'name': command['name'], 'commandName': command.get('title') or command['name'],
            'message': command.get('message') or '', 'body': {**(body or {}), 'name': command['name']},
            'priority': 'normal', 'status': state,
            'result': 'successful' if state == 'completed' else 'unsuccessful' if state == 'failed' else 'unknown',
            'queued': command.get('queued'), 'started': command.get('started'), 'ended': command.get('ended'),
            'trigger': 'manual', 'stateChangeTime': command.get('ended') or command.get('started') or
            command.get('queued'), 'sendUpdatesToClient': False, 'updateScheduledTask': False}


def make_router(media_type: str) -> APIRouter:
    """ Readarr's API for one format's library """
    lib = LIBRARIES[media_type]
    status_col, file_col = lib['status'], lib['file']
    # the format's book numbers, a book's eBook and audiobook are two as they are in Chaptarr
    book_kind = BOOK if media_type == 'ebook' else AUDIOBOOK
    logger = logging.getLogger(__name__)
    router = APIRouter(include_in_schema=False)

    def base(request: Request) -> str:
        """ Where this API is, as Readarr gives its urlBase in the images it lists """
        path = request.url.path
        return path[:path.index('/api/v1')] if '/api/v1' in path else path.split('/mediacover')[0]

    def default_profile() -> int:
        found = [profile for profile in profiles.list_profiles() if profile['media_type'] == media_type]
        chosen = next((profile for profile in found if profile['is_default']), found[0] if found else None)
        return chosen['id'] if chosen else 0

    def own_id(db, kind: str, number) -> str:
        """ Our id for one of the numbers, NotFound when nothing has it """
        found = item_id(db, kind, number)
        if not found:
            raise HTTPException(404, f"{'Author' if kind == AUTHOR else 'Book'} {number} not found")
        return found

    # --- authors

    def author_rows(db, author_id: str = '') -> list[dict]:
        where = 'WHERE AuthorID=?' if author_id else "WHERE Status != 'Ignored'"
        return [dict(row) for row in db.select(f'SELECT * FROM authors {where} ORDER BY AuthorName COLLATE NOCASE',
                                               (author_id,) if author_id else ())]

    def statistics(db, author_ids: list[str]) -> dict[str, dict]:
        """ Each author's books in this format: how many, monitored, with files, and their size """
        found = {author: {'bookFileCount': 0, 'bookCount': 0, 'availableBookCount': 0, 'totalBookCount': 0,
                          'sizeOnDisk': 0, 'percentOfBooks': 0} for author in author_ids}
        rows = db.select(f"SELECT written.AuthorID, books.{status_col} AS Status, books.{file_col} AS File FROM books "
                         f"JOIN (SELECT AuthorID, BookID FROM books UNION SELECT AuthorID, BookID FROM bookauthors) "
                         f"AS written ON books.BookID=written.BookID")
        for row in rows:
            stats = found.get(row['AuthorID'])
            if stats is None or row['Status'] == 'Ignored':
                continue
            stats['totalBookCount'] += 1
            if row['Status'] in MONITORED:
                stats['bookCount'] += 1
            if row['Status'] in OWNED:
                stats['availableBookCount'] += 1
                stats['bookFileCount'] += 1
                stats['sizeOnDisk'] += _size(row['File'], media_type)
        for stats in found.values():
            if stats['bookCount']:
                stats['percentOfBooks'] = round(stats['availableBookCount'] * 100 / stats['bookCount'], 1)
        return found

    def author_links(row: dict) -> list[dict]:
        return [{'url': row[source['author_link']], 'name': name}
                for name, source in lazylibrarian.INFOSOURCES.items()
                if source.get('author_link') and row.get(source['author_link'])]

    def author_resource(row: dict, number: int, stats: dict, where: str, profile: int) -> dict:
        name = row.get('AuthorName') or ''
        last_first = surname_first(name, postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
        image = row.get('AuthorImg') or ''
        status = row.get('Status') or ''
        return {
            'id': number, 'authorMetadataId': number, 'status': 'ended' if row.get('AuthorDeath') else 'continuing',
            'ended': bool(row.get('AuthorDeath')), 'authorName': name, 'authorNameLastFirst': last_first,
            'foreignAuthorId': row['AuthorID'], 'titleSlug': row['AuthorID'], 'overview': row.get('About') or '',
            'disambiguation': '', 'links': author_links(row),
            'images': [{'url': f"{where}/MediaCover/{number}/poster.jpg" if number else image, 'coverType': 'poster',
                        'extension': '.jpg', 'remoteUrl': image if image.startswith('http') else None}],
            'remotePoster': image if image.startswith('http') else None,
            'path': os.path.join(CONFIG[lib['folder']] or '', name), 'qualityProfileId': profile,
            'metadataProfileId': 1, 'monitored': status in ('Active', 'Wanted', 'Loading'),
            'monitorNewItems': {'Wanted': 'all', 'Active': 'new'}.get(status, 'none'),
            'rootFolderPath': CONFIG[lib['folder']] or '', 'folder': name, 'genres': [],
            'cleanName': ''.join(ch for ch in name.lower() if ch.isalnum()), 'sortName': name.lower(),
            'sortNameLastFirst': last_first.lower(), 'tags': [], 'added': _iso(row.get('DateAdded')),
            'ratings': {'votes': 0, 'value': 0.0, 'popularity': 0.0}, 'statistics': stats}

    def authors(db, request: Request, author_id: str = '') -> list[dict]:
        rows = author_rows(db, author_id)
        numbers = api_ids(db, AUTHOR, [row['AuthorID'] for row in rows])
        stats = statistics(db, [row['AuthorID'] for row in rows])
        where, profile = base(request), default_profile()
        return [author_resource(row, numbers[row['AuthorID']], stats[row['AuthorID']], where, profile) for row in rows]

    def one_author(db, request: Request, author_id: str) -> dict:
        found = authors(db, request, author_id)
        if not found:
            raise HTTPException(404, 'Author not found')
        return found[0]

    def set_author_monitored(author_ids: list[str], monitored: bool):
        """ Readarr's monitored author is one LazyLibrarian looks for books of: Active, or Paused """
        db = database.DBConnection()
        try:
            current = {row['AuthorID']: row['Status'] for row in db.select(
                f"SELECT AuthorID, Status FROM authors WHERE AuthorID IN ({','.join('?' * len(author_ids))})",
                tuple(author_ids))} if author_ids else {}
        finally:
            db.close()
        change = [author for author, status in current.items()
                  if monitored != (status in ('Active', 'Wanted', 'Loading'))]
        if change:
            library.set_author_status(change, 'Active' if monitored else 'Paused')

    @router.get('/api/v1/author')
    def list_authors(request: Request):
        db = database.DBConnection()
        try:
            return authors(db, request)
        finally:
            db.close()

    @router.get('/api/v1/author/lookup')
    def author_lookup(request: Request, term: str = ''):
        """ The authors a name finds at the info sources, the library's own numbered """
        from lazylibrarian.services import addnew  # noqa: PLC0415, it imports most of LazyLibrarian
        found = addnew.lookup(term, max_pages=1)['authors']
        db = database.DBConnection()
        try:
            have = {row['AuthorID'] for row in db.select('SELECT AuthorID FROM authors')}
            numbers = api_ids(db, AUTHOR, [author['id'] for author in found if author['id'] in have])
        finally:
            db.close()
        where, profile, result = base(request), default_profile(), []
        for author in found:
            _remember_lookup(author['id'], author['source'])
            stats = {'bookFileCount': 0, 'bookCount': 0, 'availableBookCount': 0,
                     'totalBookCount': author['books'], 'sizeOnDisk': 0, 'percentOfBooks': 0}
            resource = author_resource({'AuthorID': author['id'], 'AuthorName': author['name'], 'Status': ''},
                                       numbers.get(author['id'], 0), stats, where, profile)
            resource['monitored'] = False
            result.append(resource)
        return result

    @router.post('/api/v1/author')
    def add_author(request: Request, body: dict = Body(...)):
        """ Add an author as Readarr does: their books come in, wanted as addOptions.monitor says,
        and searched for if searchForMissingBooks """
        foreign = str(body.get('foreignAuthorId') or '')
        if not foreign:
            raise HTTPException(400, 'Which author? foreignAuthorId is missing')
        options = body.get('addOptions') or {}
        monitor = MONITOR_CHOICES.get(str(options.get('monitor') or 'all'), 'new') if body.get('monitored', True) \
            else 'none'
        commands.start('AddAuthor', {'author_id': foreign, 'author_name': body.get('authorName') or '',
                                     'monitor': monitor, 'media_types': [media_type],
                                     'search': bool(options.get('searchForMissingBooks'))})
        db = database.DBConnection()
        try:
            number = api_id(db, AUTHOR, foreign)
        finally:
            db.close()
        # added in the background, Readarr answers with the author as it will be
        return {**body, 'id': number, 'foreignAuthorId': foreign, 'added': _iso(datetime.date.today()),
                'images': body.get('images') or []}

    @router.get('/api/v1/author/{number:int}')
    def get_author(number: int, request: Request):
        db = database.DBConnection()
        try:
            return one_author(db, request, own_id(db, AUTHOR, number))
        finally:
            db.close()

    @router.put('/api/v1/author/{number:int}')
    def update_author(number: int, request: Request, body: dict = Body(...)):
        """ An author's monitored, the one change LazyLibrarian keeps of Readarr's author editor """
        db = database.DBConnection()
        try:
            author = own_id(db, AUTHOR, number)
        finally:
            db.close()
        if 'monitored' in body:
            set_author_monitored([author], bool(body['monitored']))
        db = database.DBConnection()
        try:
            return one_author(db, request, author)
        finally:
            db.close()

    @router.delete('/api/v1/author/{number:int}')
    def delete_author(number: int, deleteFiles: bool = False):  # noqa: N803
        db = database.DBConnection()
        try:
            author = own_id(db, AUTHOR, number)
        finally:
            db.close()
        library.delete_authors([author], deleteFiles)
        return {}

    @router.put('/api/v1/author/editor')
    def edit_authors(body: dict = Body(...)):
        db = database.DBConnection()
        try:
            ids = [item_id(db, AUTHOR, number) for number in body.get('authorIds') or []]
        finally:
            db.close()
        if 'monitored' in body and body['monitored'] is not None:
            set_author_monitored([author for author in ids if author], bool(body['monitored']))
        return []

    @router.delete('/api/v1/author/editor')
    def delete_authors(body: dict = Body(...)):
        db = database.DBConnection()
        try:
            ids = [item_id(db, AUTHOR, number) for number in body.get('authorIds') or []]
        finally:
            db.close()
        library.delete_authors([author for author in ids if author], bool(body.get('deleteFiles')))
        return {}

    # --- books

    def book_rows(db, where: str = '', args: tuple = ()) -> list[dict]:
        return [dict(row) for row in db.select(
            f'SELECT books.*, AuthorName FROM books JOIN authors ON books.AuthorID=authors.AuthorID {where}', args)]

    def book_resources(db, request: Request, rows: list[dict], with_author: bool = False) -> list[dict]:
        if not rows:
            return []
        book_numbers = api_ids(db, book_kind, [row['BookID'] for row in rows])
        author_numbers = api_ids(db, AUTHOR, [row['AuthorID'] for row in rows])
        ids = [row['BookID'] for row in rows]
        series: dict[str, list[str]] = {}
        for member in db.select(f"SELECT BookID, SeriesName, SeriesNum FROM member JOIN series ON "
                                f"member.SeriesID=series.SeriesID WHERE BookID IN ({','.join('?' * len(ids))})",
                                tuple(ids)):
            series.setdefault(member['BookID'], []).append(
                f"{member['SeriesName']}{' #' + member['SeriesNum'] if member['SeriesNum'] else ''}")
        owners = {}
        if with_author:
            owners = {author['foreignAuthorId']: author
                      for author_id in {row['AuthorID'] for row in rows}
                      for author in authors(db, request, author_id)}
        where = base(request)
        found = []
        for row in rows:
            number = book_numbers[row['BookID']]
            status = row[status_col] or 'Skipped'
            owned = status in OWNED
            size = _size(row[file_col], media_type) if owned else 0
            image = row['BookImg'] or ''
            name = row['AuthorName'] or ''
            book = {
                'id': number, 'title': row['BookName'] or '', 'authorTitle': f"{name.lower()} {row['BookName'] or ''}",
                'seriesTitle': '; '.join(series.get(row['BookID'], [])), 'disambiguation': row['BookSub'] or '',
                'overview': row['BookDesc'] or '', 'authorId': author_numbers.get(row['AuthorID'], 0),
                'foreignBookId': row['BookID'], 'foreignEditionId': row['BookID'], 'titleSlug': row['BookID'],
                'monitored': status in MONITORED, 'anyEditionOk': True,
                'ratings': {'votes': 0, 'value': check_float(row['BookRate'], 0), 'popularity': 0.0},
                'releaseDate': _iso(row['BookDate']), 'pageCount': check_int(row['BookPages'], 0),
                'genres': get_list(row['BookGenre'], ','),
                'images': [{'url': f"{where}/MediaCover/Books/{number}/cover.jpg", 'coverType': 'cover',
                            'extension': '.jpg', 'remoteUrl': image if image.startswith('http') else None}],
                'remoteCover': image if image.startswith('http') else None,
                'links': [{'url': source['link_template'].format(row[source['book_key']]), 'name': source_name}
                          for source_name, source in lazylibrarian.INFOSOURCES.items()
                          if source.get('link_template') and row.get(source['book_key'])],
                'statistics': {'bookFileCount': 1 if owned else 0, 'bookCount': 1, 'totalBookCount': 1,
                               'sizeOnDisk': size, 'percentOfBooks': 100.0 if owned else 0.0},
                'added': _iso(row['BookAdded']), 'grabbed': status == 'Snatched', 'editions': [],
                # what Chaptarr adds, the apps that know it read each format's state
                'mediaType': media_type, 'ebookMonitored': (row['Status'] or '') in MONITORED,
                'audiobookMonitored': (row['AudioStatus'] or '') in MONITORED, 'narrator': row.get('Narrator') or ''}
            if with_author:
                book['author'] = owners.get(row['AuthorID'])
            found.append(book)
        return found

    def books_of(db, book_ids: list[str]) -> list[dict]:
        book_ids = [book for book in book_ids if book]
        if not book_ids:
            return []
        return book_rows(db, f"WHERE BookID IN ({','.join('?' * len(book_ids))})", tuple(book_ids))

    def author_books(db, author: str) -> list[dict]:
        return book_rows(db, 'WHERE books.AuthorID=? OR BookID IN (SELECT BookID FROM bookauthors WHERE AuthorID=?)',
                         (author, author))

    def set_books_monitored(book_ids: list[str], monitored: bool):
        """ Want books in this format, or stop: a book the library has the file of stays as it is """
        db = database.DBConnection()
        try:
            change = [row['BookID'] for row in books_of(db, book_ids)
                      if (row[status_col] or 'Skipped') not in OWNED + ('Snatched',)
                      and ((row[status_col] or 'Skipped') == 'Wanted') != monitored]
        finally:
            db.close()
        if change:
            library.set_book_status(change, [media_type], 'Wanted' if monitored else 'Skipped')

    def one_book(db, request: Request, book: str) -> dict:
        found = book_resources(db, request, books_of(db, [book]), with_author=True)
        if not found:
            raise HTTPException(404, 'Book not found')
        return found[0]

    @router.get('/api/v1/book')
    def list_books(request: Request, authorId: int | None = None, bookIds: list[int] = Query(default=[]),  # noqa: N803
                   titleSlug: str = ''):  # noqa: N803
        db = database.DBConnection()
        try:
            if authorId:
                author = item_id(db, AUTHOR, authorId)
                rows = author_books(db, author) if author else []
            elif bookIds:
                rows = books_of(db, [item_id(db, book_kind, number) for number in bookIds])
            elif titleSlug:
                rows = books_of(db, [titleSlug])
            else:
                rows = book_rows(db, "WHERE authors.Status != 'Ignored'")
            return book_resources(db, request, rows)
        finally:
            db.close()

    @router.get('/api/v1/book/lookup')
    def book_lookup(request: Request, term: str = ''):
        """ The books a title, author or ISBN finds at the info sources, the library's own numbered """
        from lazylibrarian.services import addnew  # noqa: PLC0415, it imports most of LazyLibrarian
        found = addnew.lookup(term, max_pages=1)['books']
        return [looked_up_book(request, book) for book in found]

    def looked_up_book(request: Request, book: dict) -> dict:
        _remember_lookup(book['id'], book['source'])
        db = database.DBConnection()
        try:
            if book['in_library']:
                row = books_of(db, [book['id']])
                if row:
                    return book_resources(db, request, row, with_author=True)[0]
            number = api_id(db, AUTHOR, book['author_id']) if book['author_in_library'] else 0
        finally:
            db.close()
        author = author_resource({'AuthorID': book['author_id'], 'AuthorName': book['author_name'], 'Status': ''},
                                 number, {}, base(request), default_profile())
        return {'id': 0, 'title': book['title'], 'authorTitle': f"{book['author_name'].lower()} {book['title']}",
                'seriesTitle': '', 'disambiguation': book['subtitle'], 'overview': book['overview'],
                'authorId': number, 'foreignBookId': book['id'], 'foreignEditionId': book['id'],
                'titleSlug': book['id'], 'monitored': False, 'anyEditionOk': True,
                'ratings': {'votes': book['ratings'], 'value': book['rating'], 'popularity': 0.0},
                'releaseDate': _iso(book['release_date']), 'pageCount': book['pages'],
                'genres': get_list(book['genres'], ','),
                'images': [{'url': book['cover'], 'coverType': 'cover', 'extension': '.jpg',
                            'remoteUrl': book['cover'] if book['cover'].startswith('http') else None}],
                'remoteCover': book['cover'] if book['cover'].startswith('http') else None,
                'links': [{'url': book['link'], 'name': book['source']}] if book['link'] else [],
                'author': author, 'editions': [], 'grabbed': False, 'mediaType': media_type}

    @router.post('/api/v1/book')
    def add_book(body: dict = Body(...)):
        """ Add a book and want it in this format, as Readarr's Add Book """
        foreign = str(body.get('foreignBookId') or '')
        if not foreign:
            raise HTTPException(400, 'Which book? foreignBookId is missing')
        author = body.get('author') or {}
        options = body.get('addOptions') or {}
        commands.start('AddBook', {'book_id': foreign, 'source': _looked_up_source(foreign),
                                   'author_id': str(author.get('foreignAuthorId') or ''), 'media_types': [media_type],
                                   'search': bool(options.get('searchForNewBook')), 'title': body.get('title') or ''})
        db = database.DBConnection()
        try:
            number = api_id(db, book_kind, foreign)
        finally:
            db.close()
        return {**body, 'id': number, 'monitored': True}

    @router.put('/api/v1/book/monitor')
    def monitor_books(body: dict = Body(...)):
        db = database.DBConnection()
        try:
            ids = [item_id(db, book_kind, number) for number in body.get('bookIds') or []]
        finally:
            db.close()
        set_books_monitored([book for book in ids if book], bool(body.get('monitored')))
        return {}

    @router.put('/api/v1/book/editor')
    def edit_books(body: dict = Body(...)):
        return monitor_books(body)

    @router.delete('/api/v1/book/editor')
    def delete_books(body: dict = Body(...)):
        db = database.DBConnection()
        try:
            ids = [item_id(db, book_kind, number) for number in body.get('bookIds') or []]
        finally:
            db.close()
        remove_books([book for book in ids if book], bool(body.get('deleteFiles')))
        return {}

    def remove_books(book_ids: list[str], delete_files: bool):
        """ Readarr's delete of a book: this format of it is ignored from now on, its file deleted if asked """
        if book_ids:
            library.mark_books(book_ids, media_type, 'Delete' if delete_files else 'Remove')

    @router.post('/api/v1/bookshelf')
    def bookshelf(body: dict = Body(...)):
        """ Readarr's monitoring editor: authors, and some of each one's books, monitored or not """
        db = database.DBConnection()
        try:
            changes = []
            for author in body.get('authors') or []:
                author_id = item_id(db, AUTHOR, author.get('id'))
                books = [(item_id(db, book_kind, book.get('id')), bool(book.get('monitored')))
                         for book in author.get('books') or []]
                changes.append((author_id, author.get('monitored'), books))
        finally:
            db.close()
        for author_id, monitored, books in changes:
            if author_id and monitored is not None:
                set_author_monitored([author_id], bool(monitored))
            for wanted_now in (True, False):
                set_books_monitored([book for book, flag in books if book and flag == wanted_now], wanted_now)
        return {}

    @router.get('/api/v1/book/{number:int}')
    def get_book(number: int, request: Request):
        db = database.DBConnection()
        try:
            return one_book(db, request, own_id(db, book_kind, number))
        finally:
            db.close()

    @router.get('/api/v1/book/{number:int}/overview')
    def book_overview(number: int):
        db = database.DBConnection()
        try:
            row = books_of(db, [own_id(db, book_kind, number)])
        finally:
            db.close()
        return {'id': number, 'overview': row[0]['BookDesc'] or '' if row else ''}

    @router.put('/api/v1/book/{number:int}')
    def update_book(number: int, request: Request, body: dict = Body(...)):
        db = database.DBConnection()
        try:
            book = own_id(db, book_kind, number)
        finally:
            db.close()
        if 'monitored' in body:
            set_books_monitored([book], bool(body['monitored']))
        db = database.DBConnection()
        try:
            return one_book(db, request, book)
        finally:
            db.close()

    @router.delete('/api/v1/book/{number:int}')
    def delete_book(number: int, deleteFiles: bool = False):  # noqa: N803
        db = database.DBConnection()
        try:
            book = own_id(db, book_kind, number)
        finally:
            db.close()
        remove_books([book], deleteFiles)
        return {}

    # --- a book's file, editions and series

    def book_file(db, row: dict) -> dict | None:
        status = row[status_col] or ''
        path = row[file_col] or ''
        if status not in OWNED or not path:
            return None
        number = api_id(db, book_kind, row['BookID'])
        found = quality.of_file(path, media_type)
        return {'id': number, 'authorId': api_id(db, AUTHOR, row['AuthorID']), 'bookId': number, 'path': path,
                'size': _size(path, media_type),
                'dateAdded': _iso(row.get('BookLibrary' if media_type == 'ebook' else 'AudioLibrary')
                                  or row.get('BookAdded')),
                'quality': _quality(found, media_type), 'qualityWeight': _quality_id(found, media_type),
                'qualityCutoffNotMet': False, 'mediaInfo': {}}

    @router.get('/api/v1/bookfile')
    def book_files(authorId: int | None = None, bookId: list[int] = Query(default=[]),  # noqa: N803
                   bookFileIds: list[int] = Query(default=[])):  # noqa: N803
        """ The files of an author's books, of books, or by their ids, which are the books' numbers """
        db = database.DBConnection()
        try:
            if authorId:
                author = item_id(db, AUTHOR, authorId)
                rows = author_books(db, author) if author else []
            else:
                rows = books_of(db, [item_id(db, book_kind, number) for number in bookId + bookFileIds])
            return [found for found in (book_file(db, row) for row in rows) if found]
        finally:
            db.close()

    @router.get('/api/v1/bookfile/{number:int}')
    def one_book_file(number: int):
        db = database.DBConnection()
        try:
            rows = books_of(db, [own_id(db, book_kind, number)])
            found = book_file(db, rows[0]) if rows else None
        finally:
            db.close()
        if not found:
            raise HTTPException(404, 'Book file not found')
        return found

    @router.delete('/api/v1/bookfile/{number:int}')
    def delete_book_file(number: int):
        db = database.DBConnection()
        try:
            book = own_id(db, book_kind, number)
        finally:
            db.close()
        remove_books([book], True)
        return {}

    @router.delete('/api/v1/bookfile/bulk')
    def delete_book_files(body: dict = Body(...)):
        db = database.DBConnection()
        try:
            ids = [item_id(db, book_kind, number) for number in body.get('bookFileIds') or []]
        finally:
            db.close()
        remove_books([book for book in ids if book], True)
        return {}

    @router.get('/api/v1/edition')
    def editions(request: Request, bookId: list[int] = Query(default=[])):  # noqa: N803
        """ A book's one edition, as LazyLibrarian has a book """
        db = database.DBConnection()
        try:
            rows = books_of(db, [item_id(db, book_kind, number) for number in bookId])
            numbers = api_ids(db, book_kind, [row['BookID'] for row in rows])
        finally:
            db.close()
        where = base(request)
        return [{'id': numbers[row['BookID']], 'bookId': numbers[row['BookID']], 'foreignEditionId': row['BookID'],
                 'titleSlug': row['BookID'], 'isbn13': row['BookIsbn'] or '', 'asin': row.get('ASIN') or '',
                 'title': row['BookName'] or '', 'language': row['BookLang'] or '', 'overview': row['BookDesc'] or '',
                 'format': 'Audiobook' if media_type == 'audiobook' else 'eBook', 'isEbook': media_type == 'ebook',
                 'disambiguation': row['BookSub'] or '', 'publisher': row['BookPub'] or '',
                 'pageCount': check_int(row['BookPages'], 0), 'releaseDate': _iso(row['BookDate']),
                 'images': [{'url': f"{where}/MediaCover/Books/{numbers[row['BookID']]}/cover.jpg",
                             'coverType': 'cover', 'extension': '.jpg'}],
                 'links': [], 'ratings': {'votes': 0, 'value': check_float(row['BookRate'], 0), 'popularity': 0.0},
                 'monitored': True, 'manualAdd': False, 'grabbed': False} for row in rows]

    @router.get('/api/v1/series')
    def list_series(authorId: int | None = None):  # noqa: N803
        """ The series of an author's books, each with its books' numbers and places in it """
        db = database.DBConnection()
        try:
            author = item_id(db, AUTHOR, authorId) if authorId else ''
            if authorId and not author:
                return []
            where = ('WHERE member.BookID IN (SELECT BookID FROM books WHERE AuthorID=? UNION SELECT BookID FROM '
                     'bookauthors WHERE AuthorID=?)') if author else ''
            rows = db.select(f'SELECT series.SeriesID, SeriesName, member.BookID, SeriesNum FROM series JOIN member '
                             f'ON series.SeriesID=member.SeriesID {where}', (author, author) if author else ())
            numbers = api_ids(db, SERIES, [row['SeriesID'] for row in rows])
            books = api_ids(db, book_kind, [row['BookID'] for row in rows])
        finally:
            db.close()
        found: dict[str, dict] = {}
        for row in rows:
            series = found.setdefault(row['SeriesID'], {
                'id': numbers[str(row['SeriesID'])], 'title': row['SeriesName'] or '', 'description': '',
                'foreignSeriesId': str(row['SeriesID']), 'links': []})
            position = row['SeriesNum'] or ''
            series['links'].append({'id': len(series['links']) + 1, 'position': position,
                                    'seriesPosition': check_int(position, 0), 'seriesId': series['id'],
                                    'bookId': books[str(row['BookID'])]})
        return list(found.values())

    # --- searching

    @router.get('/api/v1/search')
    def search(request: Request, term: str = ''):
        """ What a term finds, authors and books, as Readarr's search box """
        from lazylibrarian.services import addnew  # noqa: PLC0415, it imports most of LazyLibrarian
        found = addnew.lookup(term, max_pages=1)
        results = []
        for number, author in enumerate(author_lookup(request, term)[:10], start=1):
            results.append({'id': number, 'foreignId': author['foreignAuthorId'], 'author': author})
        for number, book in enumerate(found['books'][:20], start=len(results) + 1):
            results.append({'id': number, 'foreignId': book['id'], 'book': looked_up_book(request, book)})
        return results

    def release_resource(release: dict, book_number: int, author_number: int) -> dict:
        return {'guid': release['id'], 'indexerId': 0, 'indexer': release['indexer'], 'title': release['title'],
                'size': release['size'], 'quality': _quality(release.get('quality', 'unknown').lower(), media_type),
                'qualityWeight': release.get('quality_rank', 0), 'approved': release['approved'],
                'rejected': not release['approved'], 'temporarilyRejected': False,
                'rejections': release['rejections'], 'protocol': release['protocol'] or 'unknown',
                'seeders': release['seeders'] if release['seeders'] >= 0 else None, 'leechers': None,
                'ageHours': 0, 'ageMinutes': 0, 'age': 0, 'publishDate': None, 'downloadAllowed': True,
                'releaseWeight': 0, 'customFormats': [], 'customFormatScore': 0, 'bookId': book_number,
                'authorId': author_number, 'discography': False, 'sceneSource': False}

    @router.get('/api/v1/release')
    def find_releases(bookId: int | None = None, authorId: int | None = None):  # noqa: N803
        """ Interactive search: the releases for a book, or for an author's wanted books """
        db = database.DBConnection()
        try:
            if bookId:
                rows = books_of(db, [own_id(db, book_kind, bookId)])
            elif authorId:
                rows = [row for row in author_books(db, own_id(db, AUTHOR, authorId)) if row[status_col] == 'Wanted']
            else:
                raise HTTPException(400, 'Which book? bookId or authorId')
            numbers = api_ids(db, book_kind, [row['BookID'] for row in rows])
            authors_ = api_ids(db, AUTHOR, [row['AuthorID'] for row in rows])
        finally:
            db.close()
        found = []
        for row in rows:
            try:
                for release in releases.search(row['BookID'], media_type):
                    found.append(release_resource(release, numbers[row['BookID']], authors_[row['AuthorID']]))
            except ServiceError as why:
                raise HTTPException(400, str(why)) from why
        return found

    @router.post('/api/v1/release')
    def grab_release(body: dict = Body(...)):
        """ Download a release interactive search found, by its guid """
        try:
            message = releases.download(str(body.get('guid') or ''))
        except ServiceError as why:
            raise HTTPException(400, str(why)) from why
        return {**body, 'title': body.get('title') or message, 'approved': True}

    # --- commands

    def wanted_of(book_ids: list[str]) -> list[dict]:
        return [{'book_id': book, 'media_type': media_type} for book in book_ids if book]

    @router.post('/api/v1/command')
    def start_command(body: dict = Body(...)):
        """ Readarr's commands, done by LazyLibrarian's own """
        name = str(body.get('name') or '')
        db = database.DBConnection()
        try:
            author = item_id(db, AUTHOR, body['authorId']) if body.get('authorId') else ''
            books = [item_id(db, book_kind, number) for number in body.get('bookIds') or []]
            if body.get('bookId'):
                books.append(item_id(db, book_kind, body['bookId']))
            author_wanted = [row['BookID'] for row in author_books(db, author) if row[status_col] == 'Wanted'] \
                if author else []
        finally:
            db.close()
        if name == 'BookSearch':
            started = commands.start('BookSearch', {'books': wanted_of(books)})
        elif name == 'AuthorSearch':
            started = commands.start('BookSearch', {'books': wanted_of(author_wanted)})
        elif name in ('MissingBookSearch', 'RssSync'):
            missing = wanted.list_missing(media_type, limit=None).items
            started = commands.start('BookSearch', {'books': wanted_of([item['book_id'] for item in missing])})
        elif name == 'CutoffUnmetBookSearch':
            unmet = wanted.list_cutoff_unmet(media_type, limit=None).items
            started = commands.start('CutoffUnmetSearch', {'books': wanted_of([item['book_id'] for item in unmet])})
        elif name == 'RefreshAuthor' and author:
            started = commands.start('RefreshAuthor', {'author_id': author})
        elif name == 'RefreshBook' and books:
            started = commands.start('RefreshBook', {'book_id': books[0]})
        elif name in ('RescanFolders', 'DownloadedBooksScan', 'RefreshAuthor'):
            started = commands.start('LibraryScan', {'media_type': media_type})
        elif name in ('ApplicationUpdate', 'Backup', 'ClearBlocklist'):
            started = commands.start(name, {})
        else:
            raise HTTPException(400, f"LazyLibrarian has no command like Readarr's {name}")
        return _command(started, body)

    @router.get('/api/v1/command')
    def list_commands():
        return [_command(command) for command in commands.list_commands()]

    @router.get('/api/v1/command/{number:int}')
    def get_command(number: int):
        try:
            return _command(commands.get(number))
        except ServiceError as why:
            raise HTTPException(404, str(why)) from why

    @router.delete('/api/v1/command/{number:int}')
    def cancel_command(number: int):
        return {}

    # --- wanted and the calendar

    @router.get('/api/v1/calendar')
    def calendar(request: Request, start: str = '', end: str = '', unmonitored: bool = False,
                 includeAuthor: bool = False):  # noqa: N803
        """ The books released between start and end, the monitored ones unless unmonitored """
        today = datetime.date.today()
        start = (start or today.isoformat())[:10]
        end = (end or (today + datetime.timedelta(days=28)).isoformat())[:10]
        db = database.DBConnection()
        try:
            rows = [row for row in book_rows(db, "WHERE substr(BookDate,1,10) BETWEEN ? AND ? AND "
                                                 "authors.Status != 'Ignored'", (start, end))
                    if unmonitored or (row[status_col] or 'Skipped') in MONITORED]
            return book_resources(db, request, rows, with_author=includeAuthor)
        finally:
            db.close()

    @router.get('/api/v1/calendar/{number:int}')
    def calendar_book(number: int, request: Request):
        return get_book(number, request)

    def missing_books(request: Request, include_author: bool) -> list[dict]:
        db = database.DBConnection()
        try:
            return book_resources(db, request, book_rows(db, f"WHERE books.{status_col}='Wanted'"),
                                  with_author=include_author)
        finally:
            db.close()

    @router.get('/api/v1/wanted/missing')
    def missing(request: Request, page: int = 1, pageSize: int = 10, sortKey: str = 'releaseDate',  # noqa: N803
                sortDirection: str = 'descending', includeAuthor: bool = True):  # noqa: N803
        records = missing_books(request, includeAuthor)
        records.sort(key=lambda book: book.get('releaseDate') or '', reverse=sortDirection != 'ascending')
        return _page(records, page, pageSize, sortKey, sortDirection)

    @router.get('/api/v1/wanted/missing/{number:int}')
    def missing_book(number: int, request: Request):
        return get_book(number, request)

    @router.get('/api/v1/wanted/cutoff')
    def cutoff(request: Request, page: int = 1, pageSize: int = 10, sortKey: str = 'releaseDate',  # noqa: N803
               sortDirection: str = 'descending', includeAuthor: bool = True):  # noqa: N803
        found = wanted.list_cutoff_unmet(media_type, limit=None).items
        db = database.DBConnection()
        try:
            records = book_resources(db, request, books_of(db, [item['book_id'] for item in found]),
                                     with_author=includeAuthor)
        finally:
            db.close()
        return _page(records, page, pageSize, sortKey, sortDirection)

    @router.get('/api/v1/wanted/cutoff/{number:int}')
    def cutoff_book(number: int, request: Request):
        return get_book(number, request)

    # --- the queue, history and blocklist

    def ids_of(db, items: list[dict]) -> tuple[dict, dict]:
        books = api_ids(db, book_kind, [item.get('book_id') for item in items])
        writers = api_ids(db, AUTHOR, [item.get('author_id') for item in items])
        return books, writers

    def queue_records(request: Request, include_author: bool, include_book: bool, author: str = '',
                      book_ids: tuple = ()) -> list[dict]:
        items = [item for item in queue.list_queue() if item.get('media_type') == media_type]
        if author:
            items = [item for item in items if item.get('author_id') == author]
        if book_ids:
            items = [item for item in items if item.get('book_id') in book_ids]
        db = database.DBConnection()
        try:
            books, writers = ids_of(db, items)
            resources = {}
            if include_book or include_author:
                for book in book_resources(db, request, books_of(db, [item['book_id'] for item in items]),
                                           with_author=include_author):
                    resources[book['foreignBookId']] = book
        finally:
            db.close()
        records = []
        for item in items:
            size = item.get('size') or 0
            done = item.get('progress') or 0
            record = {
                'id': item['id'], 'authorId': writers.get(str(item.get('author_id') or '')),
                'bookId': books.get(str(item.get('book_id') or '')),
                'quality': _release_quality(item['source_title'], media_type),
                'customFormats': [], 'customFormatScore': 0, 'size': size, 'sizeleft': round(size * (100 - done) / 100),
                'title': item['source_title'], 'timeleft': None, 'estimatedCompletionTime': None,
                'status': item['status'], 'trackedDownloadStatus': item.get('tracked_download_status', 'ok'),
                'trackedDownloadState': item.get('tracked_download_state', 'downloading'),
                'statusMessages': item.get('status_messages', []), 'errorMessage': item.get('error_message', ''),
                'downloadId': item.get('download_id', ''), 'protocol': item.get('protocol') or 'unknown',
                'downloadClient': item.get('download_client', ''), 'downloadClientHasPostImportCategory': False,
                'indexer': item.get('indexer', ''), 'outputPath': '', 'downloadForced': False}
            book = resources.get(str(item.get('book_id')))
            if include_book and book:
                record['book'] = book
            if include_author and book:
                record['author'] = book.get('author')
            records.append(record)
        return records

    @router.get('/api/v1/queue')
    def list_queue(request: Request, page: int = 1, pageSize: int = 10, sortKey: str = 'timeleft',  # noqa: N803
                   sortDirection: str = 'ascending', includeAuthor: bool = False,  # noqa: N803
                   includeBook: bool = False):  # noqa: N803
        return _page(queue_records(request, includeAuthor, includeBook), page, pageSize, sortKey, sortDirection)

    @router.get('/api/v1/queue/details')
    def queue_details(request: Request, authorId: int | None = None, bookIds: list[int] = Query(default=[]),  # noqa: N803
                      includeAuthor: bool = False, includeBook: bool = True):  # noqa: N803
        db = database.DBConnection()
        try:
            author = item_id(db, AUTHOR, authorId) if authorId else ''
            books = tuple(item_id(db, book_kind, number) for number in bookIds)
        finally:
            db.close()
        return queue_records(request, includeAuthor, includeBook, author, books)

    @router.get('/api/v1/queue/status')
    def queue_status():
        items = [item for item in queue.list_queue() if item.get('media_type') == media_type]
        warnings = any(item.get('tracked_download_status') == 'warning' for item in items)
        return {'totalCount': len(items), 'count': len(items), 'unknownCount': 0, 'errors': False,
                'warnings': warnings, 'unknownErrors': False, 'unknownWarnings': False}

    @router.delete('/api/v1/queue/{item:int}')
    def remove_queue_item(item: int, removeFromClient: bool = True, blocklist: bool = False,  # noqa: N803
                          skipRedownload: bool = False):  # noqa: N803
        queue.remove(item, removeFromClient, blocklist, skipRedownload)
        return {}

    @router.delete('/api/v1/queue/bulk')
    def remove_queue_items(body: dict = Body(...), removeFromClient: bool = True,  # noqa: N803
                           blocklist: bool = False, skipRedownload: bool = False):  # noqa: N803
        for item in body.get('ids') or []:
            with contextlib.suppress(ServiceError):
                queue.remove(item, removeFromClient, blocklist, skipRedownload)
        return {}

    def history_records(request: Request, items: list[dict], include_author: bool, include_book: bool) -> list[dict]:
        db = database.DBConnection()
        try:
            books, writers = ids_of(db, items)
            resources = {}
            if include_book or include_author:
                for book in book_resources(db, request, books_of(db, [item['book_id'] for item in items]),
                                           with_author=include_author):
                    resources[book['foreignBookId']] = book
        finally:
            db.close()
        records = []
        for event in items:
            record = {'id': event['id'], 'bookId': books.get(str(event.get('book_id') or ''), 0),
                      'authorId': writers.get(str(event.get('author_id') or ''), 0),
                      'sourceTitle': event['source_title'],
                      'quality': _release_quality(event['source_title'], media_type),
                      'customFormats': [], 'customFormatScore': 0, 'qualityCutoffNotMet': False,
                      'date': _iso(event['date']), 'downloadId': event.get('download_id', ''),
                      'eventType': EVENTS.get(event['event_type'], event['event_type']),
                      'data': {'indexer': event.get('indexer', ''), 'downloadClient': event.get('download_client', ''),
                               'message': event.get('message', ''), 'size': str(event.get('size') or 0)}}
            book = resources.get(str(event.get('book_id')))
            if include_book and book:
                record['book'] = book
            if include_author and book:
                record['author'] = book.get('author')
            records.append(record)
        return records

    def history_items() -> list[dict]:
        return [event for event in history.list_events(limit=None).items if event.get('media_type') == media_type]

    @router.get('/api/v1/history')
    def list_history(request: Request, page: int = 1, pageSize: int = 10, sortKey: str = 'date',  # noqa: N803
                     sortDirection: str = 'descending', includeAuthor: bool = False,  # noqa: N803
                     includeBook: bool = False, eventType: int | None = None,  # noqa: N803
                     bookId: int | None = None, downloadId: str = ''):  # noqa: N803
        items = history_items()
        if bookId:
            db = database.DBConnection()
            try:
                book = item_id(db, book_kind, bookId)
            finally:
                db.close()
            items = [event for event in items if event.get('book_id') == book]
        if downloadId:
            items = [event for event in items if event.get('download_id') == downloadId]
        return _page(history_records(request, items, includeAuthor, includeBook), page, pageSize, sortKey,
                     sortDirection)

    @router.get('/api/v1/history/author')
    def author_history(request: Request, authorId: int | None = None, bookId: int | None = None,  # noqa: N803
                       includeAuthor: bool = False, includeBook: bool = False):  # noqa: N803
        db = database.DBConnection()
        try:
            author = item_id(db, AUTHOR, authorId) if authorId else ''
            book = item_id(db, book_kind, bookId) if bookId else ''
        finally:
            db.close()
        items = [event for event in history_items()
                 if (not author or event.get('author_id') == author) and (not book or event.get('book_id') == book)]
        return history_records(request, items, includeAuthor, includeBook)

    @router.get('/api/v1/history/since')
    def history_since(request: Request, date: str = '', includeAuthor: bool = False,  # noqa: N803
                      includeBook: bool = False):  # noqa: N803
        since = date[:19].replace('T', ' ')
        items = [event for event in history_items() if str(event.get('date') or '') >= since]
        return history_records(request, items, includeAuthor, includeBook)

    @router.post('/api/v1/history/failed/{item:int}')
    def mark_failed(item: int):
        history.mark_failed(item)
        return {}

    @router.get('/api/v1/blocklist')
    def list_blocklist(page: int = 1, pageSize: int = 10, sortKey: str = 'date',  # noqa: N803
                       sortDirection: str = 'descending'):  # noqa: N803
        items = [item for item in blocklist.list_blocklist(limit=None).items if item.get('media_type') == media_type]
        db = database.DBConnection()
        try:
            books, writers = ids_of(db, items)
        finally:
            db.close()
        records = [{'id': item['id'], 'authorId': writers.get(str(item.get('author_id') or ''), 0),
                    'bookIds': [books[str(item['book_id'])]] if str(item.get('book_id') or '') in books else [],
                    'sourceTitle': item['source_title'], 'quality': _release_quality(item['source_title'], media_type),
                    'customFormats': [], 'date': _iso(item['date']), 'protocol': item['protocol'] or 'unknown',
                    'indexer': item['indexer'], 'message': item['message']} for item in items]
        return _page(records, page, pageSize, sortKey, sortDirection)

    @router.delete('/api/v1/blocklist/{item:int}')
    def unblock(item: int):
        blocklist.remove([item])
        return {}

    @router.delete('/api/v1/blocklist/bulk')
    def unblock_many(body: dict = Body(...)):
        blocklist.remove(list(body.get('ids') or []))
        return {}

    # --- settings and system

    @router.get('/api/v1/qualityprofile')
    def quality_profiles():
        found = []
        for profile in profiles.list_profiles():
            if profile['media_type'] != media_type:
                continue
            items = [{'quality': {'id': _quality_id(item['quality'], media_type), 'name': item['name']},
                      'items': [], 'allowed': bool(item['allowed'])} for item in profile['items']]
            found.append({'id': profile['id'], 'name': profile['name'], 'upgradeAllowed': profile['upgrade_allowed'],
                          'cutoff': _quality_id(profile['cutoff'], media_type) if profile['cutoff'] else 0,
                          'items': items, 'minFormatScore': 0, 'cutoffFormatScore': 0, 'formatItems': []})
        return found

    @router.get('/api/v1/qualityprofile/{number:int}')
    def quality_profile(number: int):
        found = [profile for profile in quality_profiles() if profile['id'] == number]
        if not found:
            raise HTTPException(404, 'Quality profile not found')
        return found[0]

    def metadata_profile() -> dict:
        """ The settings that decide which of an author's books come in, as one profile """
        return {'id': 1, 'name': 'LazyLibrarian', 'minPopularity': 0,
                'skipMissingDate': CONFIG.get_bool('NO_PUBDATE'), 'skipMissingIsbn': CONFIG.get_bool('NO_ISBN'),
                'skipPartsAndSets': CONFIG.get_bool('NO_SETS'), 'skipSeriesSecondary': False,
                'allowedLanguages': ', '.join(get_list(CONFIG['IMP_PREFLANG'])), 'minPages': 0, 'ignored': []}

    @router.get('/api/v1/metadataprofile')
    def metadata_profiles():
        return [metadata_profile()]

    @router.get('/api/v1/metadataprofile/{number:int}')
    def one_metadata_profile(number: int):
        return metadata_profile()

    def root_folder() -> dict:
        folder = CONFIG[lib['folder']] or ''
        free = total = 0
        with contextlib.suppress(OSError):
            total, _used, free = shutil.disk_usage(folder)
        return {'id': 1, 'name': lib['name'], 'path': folder, 'defaultMetadataProfileId': 1,
                'defaultQualityProfileId': default_profile(), 'defaultMonitorOption': 'all',
                'defaultNewItemMonitorOption': 'new', 'defaultTags': [], 'isCalibreLibrary': False, 'port': 0,
                'outputProfile': 'default', 'useSsl': False, 'accessible': bool(folder) and os.path.isdir(folder),
                'freeSpace': free, 'totalSpace': total}

    @router.get('/api/v1/rootfolder')
    def root_folders():
        return [root_folder()]

    @router.get('/api/v1/rootfolder/{number:int}')
    def one_root_folder(number: int):
        return root_folder()

    @router.get('/api/v1/remotepathmapping')
    def remote_path_mappings():
        return [{'id': mapping['Id'], 'host': mapping['Host'], 'remotePath': mapping['RemotePath'],
                 'localPath': mapping['LocalPath']} for mapping in remotepaths.mappings()]

    @router.get('/api/v1/diskspace')
    def disk_space():
        return [{'path': disk['path'], 'label': disk.get('label', ''), 'freeSpace': disk['free_space'],
                 'totalSpace': disk['total_space']} for disk in health.disk_space()]

    @router.get('/api/v1/health')
    def health_checks():
        return [{'source': check['source'], 'type': check['type'], 'message': check['message'],
                 'wikiUrl': check.get('link', '')} for check in health.checks()]

    @router.get('/api/v1/system/status')
    def status(request: Request):
        return {'appName': 'Readarr', 'instanceName': f"LazyLibrarian {lib['name']}", 'version': READARR_VERSION,
                'buildTime': None, 'isDebug': False, 'isProduction': True, 'isAdmin': False,
                'isUserInteractive': False, 'startupPath': DIRS.PROG_DIR, 'appData': DIRS.DATADIR,
                'osName': platform.system().lower(), 'osVersion': platform.release(), 'isNetCore': False,
                'isLinux': platform.system() == 'Linux', 'isOsx': platform.system() == 'Darwin',
                'isWindows': platform.system() == 'Windows', 'isDocker': os.path.exists('/.dockerenv'),
                'mode': 'console', 'branch': CONFIG['GIT_BRANCH'] or 'master', 'databaseType': 'sqLite',
                'authentication': 'forms', 'migrationVersion': 0, 'urlBase': base(request),
                'runtimeVersion': platform.python_version(), 'runtimeName': 'python',
                'packageUpdateMechanism': 'external', 'lazyLibrarianVersion': CONFIG['CURRENT_VERSION']}

    @router.get('/api/v1/system/task')
    def list_tasks():
        return [{'id': number, 'name': task['name'], 'taskName': task['task_name'], 'interval': task['interval'],
                 'lastExecution': task['last_execution'], 'lastStartTime': task['last_start_time'],
                 'nextExecution': task['next_execution'], 'lastDuration': f"00:00:{task['last_duration'] or 0:06.3f}"}
                for number, task in enumerate(tasks.list_tasks(), start=1)]

    @router.get('/api/v1/system/task/{number:int}')
    def one_task(number: int):
        found = [task for task in list_tasks() if task['id'] == number]
        if not found:
            raise HTTPException(404, 'Task not found')
        return found[0]

    @router.post('/api/v1/system/restart')
    def restart():
        system.request_stop('restart')
        return {}

    @router.get('/api/v1/log')
    def logs(page: int = 1, pageSize: int = 10, sortKey: str = 'time', sortDirection: str = 'descending',  # noqa: N803
             level: str = ''):
        found = system.list_events(level if level in ('info', 'warn', 'error') else '', limit=None).items
        records = [{'id': number, 'time': _iso(event.get('time')), 'level': event.get('level', ''),
                    'logger': event.get('thread', ''), 'message': event.get('message', '')}
                   for number, event in enumerate(found, start=1)]
        return _page(records, page, pageSize, sortKey, sortDirection)

    @router.get('/api/v1/config/ui')
    def ui_settings():
        return {'id': 1, 'firstDayOfWeek': 0, 'calendarWeekColumnHeader': 'ddd M/D', 'shortDateFormat': 'MMM D YYYY',
                'longDateFormat': 'dddd, MMMM D YYYY', 'timeFormat': 'h(:mm)a', 'showRelativeDates': True,
                'enableColorImpairedMode': False, 'uiLanguage': 1, 'theme': 'auto'}

    @router.get('/api/v1/config/naming')
    def naming_settings():
        return {'id': 1, 'renameBooks': CONFIG.get_bool('IMP_RENAME'), 'replaceIllegalCharacters': True,
                'standardBookFormat': CONFIG['EBOOK_DEST_FILE'], 'authorFolderFormat': CONFIG['EBOOK_DEST_FOLDER']}

    @router.get('/api/v1/config/mediamanagement')
    def media_settings():
        return {'id': 1, 'recycleBin': CONFIG['RECYCLE_BIN'] if 'RECYCLE_BIN' in CONFIG.config else '',
                'deleteEmptyFolders': True, 'copyUsingHardlinks': False}

    @router.get('/api/v1/language')
    def languages():
        return [{'id': number, 'name': name} for number, name in enumerate(get_list(CONFIG['IMP_PREFLANG']) or ['en'],
                                                                           start=1)]

    def nothing() -> list:
        return []

    def no_settings() -> dict:
        return {'id': 1}

    for name in EMPTY_LISTS + EMPTY_SCHEMAS:
        router.add_api_route(f'/api/v1/{name}', nothing, methods=['GET'])
    for name in ('config/host', 'config/indexer', 'config/downloadclient', 'config/metadataprovider',
                 'config/development'):
        router.add_api_route(f'/api/v1/{name}', no_settings, methods=['GET'])

    # --- pictures

    def picture(path: str):
        """ A picture we keep, or where it is when it's somewhere else """
        if path.startswith('http'):
            return RedirectResponse(path)
        if path.startswith('cache/'):
            local = os.path.join(DIRS.CACHEDIR, path[len('cache/'):])
            if os.path.isfile(local):
                return FileResponse(local)
        raise HTTPException(404, 'No picture')

    def author_picture(number: int):
        db = database.DBConnection()
        try:
            row = db.match('SELECT AuthorImg FROM authors WHERE AuthorID=?', (item_id(db, AUTHOR, number),))
        finally:
            db.close()
        return picture(row['AuthorImg'] or '' if row else '')

    def book_picture(number: int):
        db = database.DBConnection()
        try:
            row = db.match('SELECT BookImg FROM books WHERE BookID=?', (item_id(db, book_kind, number),))
        finally:
            db.close()
        return picture(row['BookImg'] or '' if row else '')

    # Readarr serves them below its urlBase, /MediaCover/{author}/poster.jpg and
    # /MediaCover/Books/{book}/cover.jpg, and its API's way below /api/v1, which nzb360 asks for,
    # /api/v1/mediacover/author/{id}/poster.jpg and .../book/{id}/cover-200.jpg (any size, the one picture)
    for prefix in ('', '/api/v1'):
        router.add_api_route(f'{prefix}/mediacover/books/{{number:int}}/{{name}}', book_picture)
        router.add_api_route(f'{prefix}/mediacover/{{number:int}}/{{name}}', author_picture)
    router.add_api_route('/api/v1/mediacover/author/{number:int}/{name}', author_picture)
    router.add_api_route('/api/v1/mediacover/book/{number:int}/{name}', book_picture)

    @router.get('/api')
    def api_versions():
        return {'current': 'v1', 'deprecated': []}

    @router.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    def not_here(path: str, request: Request):
        """ What an app asked for that isn't here yet, in the log so it can be added """
        logger.warning(f"Readarr API ({media_type}): no {request.method} /{path} yet "
                       f"({request.headers.get('user-agent', '')})")
        raise HTTPException(404, f'No such endpoint: {path}')

    return router


def routers() -> list[tuple[str, APIRouter]]:
    """ Each format's Readarr API, by where it is: the eBooks are /readarr too """
    ebook, audio = make_router('ebook'), make_router('audiobook')
    return [('/readarr/ebook', ebook), ('/readarr/audio', audio), ('/readarr', ebook)]


def api_number(kind: str, item: str) -> int:
    """ The number Readarr's API gives an author or book, for tests and other modules """
    db = database.DBConnection()
    try:
        return api_id(db, kind, item)
    finally:
        db.close()
