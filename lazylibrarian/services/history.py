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

from lazylibrarian import database
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.download_client import get_download_progress
from lazylibrarian.formatter import make_unicode
from lazylibrarian.services import NotFoundError
from lazylibrarian.services.paging import Page, page_of

# the history fields, in the order the search has always matched them
HISTORY_FIELDS = ('NZBtitle', 'AuxInfo', 'BookID', 'NZBprov', 'NZBdate', 'NZBsize', 'Status', 'Source', 'DownloadID')
BOOK_TYPES = ('eBook', 'AudioBook')
# asking the download clients for progress is slow, so only the first few snatched items on a page get it
PROGRESS_LIMIT = 5


def item_type(auxinfo) -> str:
    """ eBook or AudioBook, Magazine for an issue (its AuxInfo is the issue date), eBook when it's not known """
    if auxinfo in BOOK_TYPES:
        return auxinfo
    return 'Magazine' if auxinfo else 'eBook'


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
    """ Mark a download Failed and want its book again """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        match = db.match('SELECT NZBtitle,Status,BookID,AuxInfo from wanted WHERE rowid=?', (rowid,))
        if not match:
            raise NotFoundError(f'No history item {rowid}')
        logger.debug(f'Marking {match["Status"]} history item {match["NZBtitle"]} as Failed')
        db.action("UPDATE wanted SET Status='Failed' WHERE rowid=?", (rowid,))
        if item_type(match['AuxInfo']) == 'AudioBook':
            db.action("UPDATE books SET audiostatus='Wanted' WHERE BookID=?", (match["BookID"],))
        else:
            db.action("UPDATE books SET status='Wanted' WHERE BookID=?", (match["BookID"],))
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


def reset_snatched_books(db, downloads):
    """ Books still marked Snatched by these downloads go back to Wanted """
    for book in downloads:
        if book['BookID'] == 'unknown':
            continue
        if book['AuxInfo'] == 'eBook':
            db.action("UPDATE books SET Status='Wanted' WHERE Bookid=? AND Status='Snatched'", (book['BookID'],))
        elif book['AuxInfo'] == 'AudioBook':
            db.action("UPDATE books SET AudioStatus='Wanted' WHERE Bookid=? AND AudioStatus='Snatched'",
                      (book['BookID'],))


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
