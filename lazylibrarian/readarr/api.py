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
translation of the library: its authors, books, queue, history, wanted and settings in Readarr's
shapes. It sits beside LazyLibrarian's own /api/v1 and changes nothing of it.

Readarr has one wanted state per book, LazyLibrarian one for each format, so there's an API for
each: /readarr/ebook and /readarr/audio (and /readarr, the eBooks), each its own Readarr to the
app. Paths an app asks for that aren't here are logged, so the ones it needs can be added """

import contextlib
import datetime
import logging
import os
import platform
import shutil

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

import lazylibrarian
from lazylibrarian import database, quality
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import check_float, check_int, get_list, surname_first
from lazylibrarian.readarr.ids import AUDIOBOOK, AUTHOR, BOOK, api_id, api_ids, item_id
from lazylibrarian.services import health, history, profiles, queue, wanted
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
# Readarr's numbers for its qualities, ours that it hasn't got are numbered from 100
QUALITY_IDS = {'unknown': 0, 'pdf': 1, 'mobi': 2, 'epub': 3, 'azw3': 4, 'mp3': 10, 'flac': 11, 'm4b': 12}
UNKNOWN_AUDIO = 13
# Readarr's history events, by ours
EVENTS = {'grabbed': 'grabbed', 'downloadFolderImported': 'bookFileImported', 'downloadFailed': 'downloadFailed'}


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
        return path[:path.index('/api/v1')] if '/api/v1' in path else path.split('/MediaCover')[0]

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

    def author_resource(row: dict, number: int, stats: dict, where: str) -> dict:
        name = row['AuthorName'] or ''
        last_first = surname_first(name, postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
        image = row.get('AuthorImg') or ''
        return {
            'id': number, 'authorMetadataId': number, 'status': 'ended' if row.get('AuthorDeath') else 'continuing',
            'ended': bool(row.get('AuthorDeath')), 'authorName': name, 'authorNameLastFirst': last_first,
            'foreignAuthorId': row['AuthorID'], 'titleSlug': row['AuthorID'], 'overview': row.get('About') or '',
            'disambiguation': '', 'links': author_links(row),
            'images': [{'url': f"{where}/MediaCover/{number}/poster.jpg", 'coverType': 'poster', 'extension': '.jpg',
                        'remoteUrl': image if image.startswith('http') else None}],
            'path': os.path.join(CONFIG[lib['folder']] or '', name), 'qualityProfileId': default_profile(),
            'metadataProfileId': 1, 'monitored': row['Status'] in ('Active', 'Wanted', 'Loading'),
            'monitorNewItems': {'Wanted': 'all', 'Active': 'new'}.get(row['Status'], 'none'),
            'rootFolderPath': CONFIG[lib['folder']] or '', 'genres': [],
            'cleanName': ''.join(ch for ch in name.lower() if ch.isalnum()), 'sortName': name.lower(),
            'sortNameLastFirst': last_first.lower(), 'tags': [], 'added': _iso(row.get('DateAdded')),
            'ratings': {'votes': 0, 'value': 0.0, 'popularity': 0.0}, 'statistics': stats}

    def authors(db, request: Request, author_id: str = '') -> list[dict]:
        rows = author_rows(db, author_id)
        numbers = api_ids(db, AUTHOR, [row['AuthorID'] for row in rows])
        stats = statistics(db, [row['AuthorID'] for row in rows])
        where = base(request)
        return [author_resource(row, numbers[row['AuthorID']], stats[row['AuthorID']], where) for row in rows]

    @router.get('/api/v1/author')
    def list_authors(request: Request):
        db = database.DBConnection()
        try:
            return authors(db, request)
        finally:
            db.close()

    @router.get('/api/v1/author/{number}')
    def get_author(number: int, request: Request):
        db = database.DBConnection()
        try:
            author = item_id(db, AUTHOR, number)
            found = authors(db, request, author) if author else []
        finally:
            db.close()
        if not found:
            raise HTTPException(404, 'Author not found')
        return found[0]

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
            owners = {author['foreignAuthorId']: author for author in authors(db, request)}
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
        if not book_ids:
            return []
        return book_rows(db, f"WHERE BookID IN ({','.join('?' * len(book_ids))})", tuple(book_ids))

    @router.get('/api/v1/book')
    def list_books(request: Request, authorId: int | None = None, bookIds: list[int] = Query(default=[]),  # noqa: N803
                   titleSlug: str = ''):  # noqa: N803
        db = database.DBConnection()
        try:
            if authorId:
                author = item_id(db, AUTHOR, authorId)
                rows = book_rows(db, 'WHERE books.AuthorID=? OR BookID IN (SELECT BookID FROM bookauthors WHERE '
                                     'AuthorID=?)', (author, author)) if author else []
            elif bookIds:
                rows = books_of(db, [item_id(db, book_kind, number) for number in bookIds])
            elif titleSlug:
                rows = books_of(db, [titleSlug])
            else:
                rows = book_rows(db, "WHERE authors.Status != 'Ignored'")
            return book_resources(db, request, rows)
        finally:
            db.close()

    @router.get('/api/v1/book/{number}')
    def get_book(number: int, request: Request):
        db = database.DBConnection()
        try:
            found = book_resources(db, request, books_of(db, [item_id(db, book_kind, number)]), with_author=True)
        finally:
            db.close()
        if not found:
            raise HTTPException(404, 'Book not found')
        return found[0]

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

    # --- wanted

    @router.get('/api/v1/wanted/missing')
    def missing(request: Request, page: int = 1, pageSize: int = 10, sortKey: str = 'releaseDate',  # noqa: N803
                sortDirection: str = 'descending', includeAuthor: bool = True):  # noqa: N803
        db = database.DBConnection()
        try:
            rows = book_rows(db, f"WHERE books.{status_col}='Wanted'")
            records = book_resources(db, request, rows, with_author=includeAuthor)
        finally:
            db.close()
        records.sort(key=lambda book: book.get('releaseDate') or '', reverse=sortDirection != 'ascending')
        return _page(records, page, pageSize, sortKey, sortDirection)

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

    # --- activity

    def ids_of(db, items: list[dict]) -> tuple[dict, dict]:
        books = api_ids(db, book_kind, [item.get('book_id') for item in items])
        writers = api_ids(db, AUTHOR, [item.get('author_id') for item in items])
        return books, writers

    @router.get('/api/v1/queue')
    def list_queue(request: Request, page: int = 1, pageSize: int = 10, sortKey: str = 'timeleft',  # noqa: N803
                   sortDirection: str = 'ascending', includeAuthor: bool = False,  # noqa: N803
                   includeBook: bool = False):  # noqa: N803
        items = [item for item in queue.list_queue() if item.get('media_type') == media_type]
        db = database.DBConnection()
        try:
            books, writers = ids_of(db, items)
            resources = {}
            if includeBook or includeAuthor:
                for book in book_resources(db, request, books_of(db, [item['book_id'] for item in items]),
                                           with_author=includeAuthor):
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
                'quality': _quality((quality.of_release(item['source_title'], media_type) or ['unknown'])[0],
                                    media_type),
                'customFormats': [], 'customFormatScore': 0, 'size': size, 'sizeleft': round(size * (100 - done) / 100),
                'title': item['source_title'], 'timeleft': None, 'estimatedCompletionTime': None,
                'status': item['status'], 'trackedDownloadStatus': item.get('tracked_download_status', 'ok'),
                'trackedDownloadState': item.get('tracked_download_state', 'downloading'),
                'statusMessages': item.get('status_messages', []), 'errorMessage': item.get('error_message', ''),
                'downloadId': item.get('download_id', ''), 'protocol': item.get('protocol') or 'unknown',
                'downloadClient': item.get('download_client', ''), 'downloadClientHasPostImportCategory': False,
                'indexer': item.get('indexer', ''), 'outputPath': '', 'downloadForced': False}
            book = resources.get(str(item.get('book_id')))
            if includeBook and book:
                record['book'] = book
            if includeAuthor and book:
                record['author'] = book.get('author')
            records.append(record)
        return _page(records, page, pageSize, sortKey, sortDirection)

    @router.get('/api/v1/queue/status')
    def queue_status():
        items = [item for item in queue.list_queue() if item.get('media_type') == media_type]
        warnings = any(item.get('tracked_download_status') == 'warning' for item in items)
        return {'totalCount': len(items), 'count': len(items), 'unknownCount': 0, 'errors': False,
                'warnings': warnings, 'unknownErrors': False, 'unknownWarnings': False}

    @router.get('/api/v1/history')
    def list_history(page: int = 1, pageSize: int = 10, sortKey: str = 'date',  # noqa: N803
                     sortDirection: str = 'descending'):  # noqa: N803
        items = [event for event in history.list_events(limit=None).items if event.get('media_type') == media_type]
        db = database.DBConnection()
        try:
            books, writers = ids_of(db, items)
        finally:
            db.close()
        records = [{'id': event['id'], 'bookId': books.get(str(event.get('book_id') or ''), 0),
                    'authorId': writers.get(str(event.get('author_id') or ''), 0), 'sourceTitle': event['source_title'],
                    'quality': _quality((quality.of_release(event['source_title'], media_type) or ['unknown'])[0],
                                        media_type),
                    'customFormats': [], 'customFormatScore': 0, 'qualityCutoffNotMet': False,
                    'date': _iso(event['date']), 'downloadId': event.get('download_id', ''),
                    'eventType': EVENTS.get(event['event_type'], event['event_type']),
                    'data': {'indexer': event.get('indexer', ''), 'downloadClient': event.get('download_client', ''),
                             'message': event.get('message', ''), 'size': str(event.get('size') or 0)}}
                   for event in items]
        return _page(records, page, pageSize, sortKey, sortDirection)

    # --- settings and system

    def default_profile() -> int:
        found = [profile for profile in profiles.list_profiles() if profile['media_type'] == media_type]
        chosen = next((profile for profile in found if profile['is_default']), found[0] if found else None)
        return chosen['id'] if chosen else 0

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

    @router.get('/api/v1/metadataprofile')
    def metadata_profiles():
        """ The settings that decide which of an author's books come in, as one profile """
        return [{'id': 1, 'name': 'LazyLibrarian', 'minPopularity': 0,
                 'skipMissingDate': CONFIG.get_bool('NO_PUBDATE'), 'skipMissingIsbn': CONFIG.get_bool('NO_ISBN'),
                 'skipPartsAndSets': CONFIG.get_bool('NO_SETS'), 'skipSeriesSecondary': False,
                 'allowedLanguages': ', '.join(get_list(CONFIG['IMP_PREFLANG'])), 'minPages': 0, 'ignored': []}]

    @router.get('/api/v1/rootfolder')
    def root_folders():
        folder = CONFIG[lib['folder']] or ''
        free = total = 0
        with contextlib.suppress(OSError):
            total, _used, free = shutil.disk_usage(folder)
        return [{'id': 1, 'name': lib['name'], 'path': folder, 'defaultMetadataProfileId': 1,
                 'defaultQualityProfileId': default_profile(), 'defaultMonitorOption': 'all',
                 'defaultNewItemMonitorOption': 'new', 'defaultTags': [], 'isCalibreLibrary': False, 'port': 0,
                 'outputProfile': 'default', 'useSsl': False, 'accessible': bool(folder) and os.path.isdir(folder),
                 'freeSpace': free, 'totalSpace': total}]

    @router.get('/api/v1/tag')
    def tags():
        return []

    @router.get('/api/v1/diskspace')
    def disk_space():
        return [{'path': disk['path'], 'label': disk.get('label', ''), 'freeSpace': disk['free_space'],
                 'totalSpace': disk['total_space']} for disk in health.disk_space()]

    @router.get('/api/v1/health')
    def health_checks():
        return [{'source': check['source'], 'type': check['type'], 'message': check['message'],
                 'wikiUrl': check.get('link', '')} for check in health.checks()]

    @router.get('/api/v1/command')
    def commands():
        return []

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

    # Readarr serves them below its urlBase and below /api/v1, apps ask for either
    for prefix in ('', '/api/v1'):
        router.add_api_route(f'{prefix}/MediaCover/Books/{{number}}/{{name}}', book_picture)
        router.add_api_route(f'{prefix}/MediaCover/{{number}}/{{name}}', author_picture)

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
