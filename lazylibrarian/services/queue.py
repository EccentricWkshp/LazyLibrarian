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

""" The download queue, like Sonarr's and Radarr's Activity, Queue: what has been sent to a download
client and not imported yet, how far each has got, and why one that finished can't be imported """

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from lazylibrarian import database
from lazylibrarian.download_client import delete_task, get_download_progress
from lazylibrarian.formatter import check_int, make_unicode
from lazylibrarian.services import NotFoundError, books
from lazylibrarian.services.history import item_type, reset_snatched_books

# postprocess.py writes this before the reason a finished download wasn't imported
BLOCKED = 'Import blocked: '

CLIENT_NAMES = {'SABNZBD': 'SABnzbd', 'NZBGET': 'NZBGet', 'QBITTORRENT': 'qBittorrent',
                'TRANSMISSION': 'Transmission', 'DELUGEWEBUI': 'Deluge', 'DELUGERPC': 'Deluge',
                'RTORRENT': 'rTorrent', 'UTORRENT': 'uTorrent', 'SYNOLOGY_TOR': 'Synology',
                'SYNOLOGY_NZB': 'Synology', 'BLACKHOLE': 'Blackhole', 'DIRECT': 'Direct'}
PROTOCOLS = {'nzb': 'usenet', 'torrent': 'torrent', 'magnet': 'torrent', 'torznab': 'torrent'}
# the download clients are asked for progress at the same time, a slow one doesn't hold up the rest
PROGRESS_WORKERS = 8
# seconds an answer about a download's progress is kept, and the answers by (source, download id)
PROGRESS_KEEP = 15
_asked: dict[tuple, tuple[float, int]] = {}


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


def _what(db, row) -> dict:
    """ What a download is for: its book, magazine issue or comic issue """
    kind = media_type(row['AuxInfo'])
    what = {'media_type': kind, 'book_id': row['BookID'], 'title': row['BookID'], 'author': '', 'author_id': None,
            'issue': ''}
    if kind in ('ebook', 'audiobook'):
        book = db.match('SELECT BookName,AuthorName,books.AuthorID FROM books,authors '
                        'WHERE books.AuthorID=authors.AuthorID AND BookID=?', (row['BookID'],))
        if book:
            what.update(title=book['BookName'], author=book['AuthorName'], author_id=book['AuthorID'])
    elif kind == 'magazine':
        what['issue'] = row['AuxInfo']
    elif '_' in (row['BookID'] or ''):
        comicid, issue = row['BookID'].split('_', 1)
        comic = db.match('SELECT Title FROM comics WHERE ComicID=?', (comicid,))
        what.update(title=comic['Title'] if comic else comicid, issue=issue)
    return what


def _status(row, progress) -> dict:
    """ Sonarr's status, tracked download state and status for a download, and its messages """
    result = row['DLResult'] or ''
    if result.startswith(BLOCKED):
        return {'status': 'completed', 'tracked_download_state': 'importBlocked',
                'tracked_download_status': 'warning',
                'status_messages': [{'title': row['NZBtitle'], 'messages': [result[len(BLOCKED):]]}]}
    status = {'tracked_download_state': 'downloading', 'tracked_download_status': 'ok', 'status_messages': []}
    if progress == -2:
        status['status'] = 'downloadClientUnavailable'
    elif progress == -1:
        status.update(status='warning', error_message=f"Not found in {client_name(row['Source'])}")
    elif progress >= 100:
        status.update(status='completed', tracked_download_state='importPending')
    else:
        status['status'] = 'downloading'
    return status


def _progress(row) -> int:
    """ How far a download has got, -1 when its client doesn't have it and -2 when the client can't
    be reached. A client that can't be reached can take seconds to say so, and the page asks every
    few seconds, so an answer is kept for a little while """
    if not row['Source'] or not row['DownloadID']:
        return -1
    key = (row['Source'], make_unicode(row['DownloadID']))
    asked, progress = _asked.get(key, (0, 0))
    if time.monotonic() - asked < PROGRESS_KEEP:
        return progress
    progress, finished = get_download_progress(*key)
    progress = check_int(progress, 0, positive=False)
    progress = 100 if finished and progress >= 0 else progress
    _asked[key] = (time.monotonic(), progress)
    return progress


def list_queue() -> list[dict]:
    """ The downloads that haven't been imported yet, oldest first, with their progress from the
    download clients """
    db = database.DBConnection()
    try:
        rows = [dict(row) for row in db.select("SELECT rowid,* FROM wanted WHERE Status='Snatched' ORDER BY rowid")]
        items = []
        for row in rows:
            item = _what(db, row)
            item.update(id=row['rowid'], source_title=row['NZBtitle'] or '', indexer=row['NZBprov'] or '',
                        protocol=PROTOCOLS.get(row['NZBmode'], row['NZBmode'] or ''),
                        download_client=client_name(row['Source']),
                        download_id=make_unicode(row['DownloadID']) or '',
                        size=round(float(row['NZBsize'] or 0) * 1048576) if _number(row['NZBsize']) else 0,
                        added=row['NZBdate'] or '')
            items.append(item)
    finally:
        db.close()
    with ThreadPoolExecutor(max_workers=PROGRESS_WORKERS) as pool:
        progress = list(pool.map(_progress, rows))
    for item, row, done in zip(items, rows, progress, strict=True):
        item.update(_status(row, done))
        item['progress'] = 100 if item['status'] == 'completed' else max(0, min(done, 100))
    return items


def _number(value) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _row(db, item_id) -> dict:
    row = db.match("SELECT rowid,* FROM wanted WHERE rowid=? AND Status='Snatched'", (item_id,))
    if not row:
        raise NotFoundError(f'No queue item {item_id}')
    return dict(row)


def get_item(item_id) -> dict:
    db = database.DBConnection()
    try:
        return _row(db, item_id)
    finally:
        db.close()


def remove(item_id, remove_from_client=True, blocklist=False, skip_redownload=False) -> str:
    """ Take a download off the queue, as Sonarr's Remove does.

        remove_from_client deletes it and its files from the download client. blocklist marks it
        Failed, so a search won't take that release again, and then searches for the item again
        unless skip_redownload. Without blocklist the download is forgotten and its book wanted
        again. Returns a message for anything that couldn't be done """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        row = _row(db, item_id)
        message = ''
        in_client = row['Source'] and row['DownloadID'] and row['Source'] not in ('DIRECT', 'MANUAL')
        if remove_from_client and in_client and \
                not delete_task(row['Source'], make_unicode(row['DownloadID']), True, abandoned=True):
            message = f"{client_name(row['Source'])} did not remove {row['NZBtitle']}"
        reset_snatched_books(db, [row])
        if blocklist:
            logger.info(f"Removed {row['NZBtitle']} from the queue and blocklisted it")
            db.action("UPDATE wanted SET Status='Failed',DLResult=? WHERE rowid=?",
                      ('Removed from the queue and blocklisted', item_id))
        else:
            logger.info(f"Removed {row['NZBtitle']} from the queue")
            db.action('DELETE FROM wanted WHERE rowid=?', (item_id,))
    finally:
        db.close()
    if blocklist and not skip_redownload and media_type(row['AuxInfo']) in ('ebook', 'audiobook'):
        books.start_search([{'bookid': row['BookID']}], library=item_type(row['AuxInfo']), force=True)
    return message
