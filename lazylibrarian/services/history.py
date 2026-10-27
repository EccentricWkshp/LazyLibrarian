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

""" Download history (the wanted table), the provider blocklist and the provider download counters """

import logging
import os

from lazylibrarian import database
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.config2 import CONFIG
from lazylibrarian.download_client import get_download_progress
from lazylibrarian.formatter import make_unicode
from lazylibrarian.services import InvalidRequestError, NotFoundError
from lazylibrarian.services.paging import Page, page_of

# the history fields, in the order the search has always matched them
HISTORY_FIELDS = ('NZBtitle', 'AuxInfo', 'BookID', 'NZBprov', 'NZBdate', 'NZBsize', 'Status', 'Source', 'DownloadID')
BOOK_TYPES = ('eBook', 'AudioBook')
# asking the download clients for progress is slow, so only the first few snatched items on a page get it
PROGRESS_LIMIT = 5

CLIENT_NAMES = {'SABNZBD': 'SABnzbd', 'NZBGET': 'NZBGet', 'QBITTORRENT': 'qBittorrent',
                'TRANSMISSION': 'Transmission', 'DELUGEWEBUI': 'Deluge', 'DELUGERPC': 'Deluge',
                'RTORRENT': 'rTorrent', 'UTORRENT': 'uTorrent', 'SYNOLOGY_TOR': 'Synology',
                'SYNOLOGY_NZB': 'Synology', 'BLACKHOLE': 'Blackhole', 'DIRECT': 'Direct', 'MANUAL': 'Manual Import'}
PROTOCOLS = {'nzb': 'usenet', 'torrent': 'torrent', 'magnet': 'torrent', 'torznab': 'torrent'}
# Sonarr's history event for a download, by where it has got to
EVENT_TYPES = {'Snatched': 'grabbed', 'Seeding': 'downloadFolderImported', 'Processed': 'downloadFolderImported',
               'Failed': 'downloadFailed', 'Aborted': 'downloadFailed'}
EVENT_SORTS = ('date', 'title', 'source_title', 'event_type', 'indexer')


def item_type(auxinfo) -> str:
    """ eBook or AudioBook, Magazine for an issue (its AuxInfo is the issue date), eBook when it's not known """
    if auxinfo in BOOK_TYPES:
        return auxinfo
    return 'Magazine' if auxinfo else 'eBook'


def client_name(source) -> str:
    source = source or ''
    if source.startswith('IRC'):
        return 'IRC'
    return CLIENT_NAMES.get(source, source.title())


def media_type(auxinfo) -> str:
    """ ebook, audiobook, magazine or comic, from a download's AuxInfo """
    if auxinfo == 'comic':
        return 'comic'
    return {'eBook': 'ebook', 'AudioBook': 'audiobook', 'Magazine': 'magazine'}[item_type(auxinfo)]


def indexer_name(provider) -> str:
    """ A provider's name, as Settings shows it, rather than its address """
    return CONFIG.disp_name(provider.strip('/')) if provider else ''


def size_bytes(size) -> int:
    """ A download's size, recorded in MB """
    try:
        return round(float(size) * 1048576)
    except (TypeError, ValueError):
        return 0


def download_target(db, row, book=None) -> dict:
    """ What a download is for: its book, magazine issue or comic issue. book is the download's book
    and author when they were looked up already """
    kind = media_type(row['AuxInfo'])
    what = {'media_type': kind, 'book_id': row['BookID'], 'title': row['BookID'], 'author': '', 'author_id': None,
            'issue': ''}
    if kind in ('ebook', 'audiobook'):
        if book is None:
            book = db.match('SELECT BookName,AuthorName,books.AuthorID FROM books,authors '
                            'WHERE books.AuthorID=authors.AuthorID AND BookID=?', (row['BookID'],))
        if book and book['BookName']:
            what.update(title=book['BookName'], author=book['AuthorName'] or '', author_id=book['AuthorID'])
    elif kind == 'magazine':
        what['issue'] = row['AuxInfo']
    elif '_' in (row['BookID'] or ''):
        comicid, issue = row['BookID'].split('_', 1)
        comic = db.match('SELECT Title FROM comics WHERE ComicID=?', (comicid,))
        what.update(title=comic['Title'] if comic else comicid, issue=issue)
    return what


def list_events(event_type: str = '', search: str = '', sort: str = 'date', descending: bool = True,
                offset: int = 0, limit: int | None = None) -> Page:
    """ The download history as Sonarr's History shows it: each download as an event, grabbed,
    imported or failed, with what it was for, newest first """
    if event_type and event_type not in EVENT_TYPES.values():
        raise InvalidRequestError(f"The event type is one of {', '.join(sorted(set(EVENT_TYPES.values())))}")
    if sort not in EVENT_SORTS:
        raise InvalidRequestError(f"Sort by one of {', '.join(EVENT_SORTS)}")
    db = database.DBConnection()
    try:
        # one query for the books and authors, the history can be long
        rows = db.select("SELECT wanted.rowid AS Id,wanted.*,BookName,AuthorName,books.AuthorID AS AuthorID "
                         "FROM wanted LEFT JOIN books ON wanted.BookID=books.BookID "
                         "LEFT JOIN authors ON books.AuthorID=authors.AuthorID "
                         "WHERE wanted.BookID IS NOT NULL AND AuxInfo IS NOT NULL")
        records = []
        for row in rows:
            event = EVENT_TYPES.get(row['Status'], (row['Status'] or '').lower())
            if event_type and event != event_type:
                continue
            record = download_target(db, row, book=row)
            record.update(id=row['Id'], event_type=event, status=row['Status'] or '',
                          source_title=row['NZBtitle'] or '', indexer=indexer_name(row['NZBprov']),
                          download_client=client_name(row['Source']),
                          download_id=make_unicode(row['DownloadID']) or '',
                          protocol=PROTOCOLS.get(row['NZBmode'], row['NZBmode'] or ''),
                          size=size_bytes(row['NZBsize']), date=row['NZBdate'] or '',
                          message=make_unicode(row['DLResult']) or '')
            records.append(record)
    finally:
        db.close()
    return page_of(records, search=search, search_fields=('title', 'author', 'source_title', 'indexer', 'issue'),
                   sort=sort, descending=descending, natural=sort == 'title', offset=offset, limit=limit)


def list_history(search: str = '', sort: str = 'rowid', descending: bool = True, offset: int = 0,
                 limit: int | None = None, progress_limit: int = PROGRESS_LIMIT) -> Page:
    """ A page of download history, newest first unless sorted otherwise.

        Each item has the HISTORY_FIELDS and rowid, plus AuthorID for a book (None otherwise) and
        Progress, the download percentage for the first progress_limit snatched items (None otherwise).
        NZBsize sorts by its number.
    """
    db = database.DBConnection()
    try:
        rows = db.select(f"SELECT {','.join(HISTORY_FIELDS)},rowid from wanted "
                         "where BookID is not null and AuxInfo is not null")
        page = page_of([dict(row) for row in rows], search=search, search_fields=HISTORY_FIELDS + ('rowid',),
                       sort=sort, descending=descending, natural=sort == 'NZBsize', offset=offset, limit=limit)
        snatching = 0
        for item in page.items:
            item['DownloadID'] = make_unicode(item['DownloadID'])  # delugerpc returns bytes
            item['Progress'] = None
            if item['Status'] == 'Snatched':
                snatching += 1
                if snatching <= progress_limit:
                    item['Progress'], _ = get_download_progress(item['Source'], item['DownloadID'])
            item['AuthorID'] = None
            if item['AuxInfo'] in BOOK_TYPES:
                book = db.match('SELECT AuthorID from books where BookID=?', (item['BookID'],))
                if book:
                    item['AuthorID'] = book['AuthorID']
    finally:
        db.close()
    return page


def get_history_item(rowid) -> dict:
    """ Everything about one download """
    db = database.DBConnection()
    try:
        item = db.match("SELECT NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,DLResult,Source,"
                        "DownloadID,BookID from wanted where rowid=?", (rowid,))
    finally:
        db.close()
    if not item:
        raise NotFoundError(f'No history item {rowid}')
    return dict(item)


def ignored_reason(bookid) -> str:
    """ Why a book was ignored, from its last scan """
    db = database.DBConnection()
    try:
        book = db.match('SELECT ScanResult from books WHERE BookID=?', (bookid,))
    finally:
        db.close()
    if not book:
        raise NotFoundError(f'No book {bookid}')
    return book['ScanResult']


def delete_history_item(rowid):
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        match = db.match('SELECT NZBtitle,Status from wanted WHERE rowid=?', (rowid,))
        if not match:
            raise NotFoundError(f'No history item {rowid}')
        logger.debug(f'Deleting {match["Status"]} history item {match["NZBtitle"]}')
        db.action('DELETE from wanted WHERE rowid=?', (rowid,))
    finally:
        db.close()


def mark_failed(rowid):
    """ Mark a download Failed and want its book again, unless it has its file already """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        match = db.match('SELECT NZBtitle,Status,BookID,AuxInfo from wanted WHERE rowid=?', (rowid,))
        if not match:
            raise NotFoundError(f'No history item {rowid}')
        logger.debug(f'Marking {match["Status"]} history item {match["NZBtitle"]} as Failed')
        # the blocklist says why, as Sonarr's does
        db.action("UPDATE wanted SET Status='Failed',DLResult='Manually marked as failed' WHERE rowid=?", (rowid,))
        unsnatch_book(db, match['BookID'], item_type(match['AuxInfo']), only_snatched=False)
    finally:
        db.close()


def clear_history(status: str = 'all'):
    """ Remove history with this status, or all of it.

        Books that were snatched go back to Wanted so they're searched for again.
        Clearing Snatched clears Matched too.
    """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        if not status or status == 'all':
            logger.info("Clearing all history")
            snatched = db.select("SELECT BookID,AuxInfo from wanted WHERE Status='Snatched'")
            reset_snatched_books(db, snatched)
            db.action("DELETE from wanted")
        else:
            logger.info(f"Clearing history where status is {status}")
            if status == 'Snatched':
                snatched = db.select("SELECT BookID,AuxInfo from wanted WHERE Status in ('Snatched', 'Matched')")
                reset_snatched_books(db, snatched)
                db.action("DELETE from wanted WHERE Status='Matched'")
            db.action('DELETE from wanted WHERE Status=?', (status,))
    finally:
        db.close()


def unsnatch_book(db, book_id, library: str, only_snatched: bool = True):
    """ A book whose download didn't come to anything: wanted again, unless it has its file in the
    library, as when the download was an upgrade, when it is owned as before (FOUND_STATUS) rather
    than looking like a book that isn't there. only_snatched leaves a book that isn't Snatched """
    library = {'ebook': 'eBook', 'audiobook': 'AudioBook'}.get(str(library).lower())
    if not library or book_id == 'unknown':
        return
    status, file_column = ('AudioStatus', 'AudioFile') if library == 'AudioBook' else ('Status', 'BookFile')
    row = db.match(f'SELECT {file_column} AS Path FROM books WHERE BookID=?', (book_id,))
    owned = bool(row and row['Path'] and os.path.isfile(row['Path']))
    cmd = f"UPDATE books SET {status}=? WHERE BookID=?"
    if only_snatched:
        cmd += f" AND {status}='Snatched'"
    db.action(cmd, (CONFIG['FOUND_STATUS'] if owned else 'Wanted', book_id))


def reset_snatched_books(db, downloads):
    """ Books still marked Snatched by these downloads are wanted again, or owned if they have their file """
    for book in downloads:
        unsnatch_book(db, book['BookID'], book['AuxInfo'])


def clear_blocked() -> int:
    """ Unblock every provider, returns how many were blocked """
    return BLOCKHANDLER.clear_all()


def blocked_text() -> str:
    """ The blocked providers, one per line with how long for and why """
    return BLOCKHANDLER.get_text_list_of_blocks()


def clear_download_counts() -> int:
    """ Reset the provider download counters, returns how many providers had one """
    db = database.DBConnection()
    try:
        count = db.match('SELECT COUNT(*) as counter FROM downloads')
        db.action('DELETE from downloads')
    finally:
        db.close()
    return count['counter'] if count else 0


def download_counts() -> list[dict]:
    """ Downloads per provider, most first """
    db = database.DBConnection()
    try:
        return [dict(row) for row in db.select('SELECT Count,Provider FROM downloads ORDER BY Count DESC')]
    finally:
        db.close()
