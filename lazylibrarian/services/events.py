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

""" Live updates, like Sonarr's SignalR messages: the web pages keep a stream open (/api/v1/events)
and are told when something they show has changed, instead of each asking every few seconds.

Commands publish themselves as they start, say how they are going and end. Everything else is
noticed in the database, whoever changed it: while a page is listening, one thread looks at
SQLite's data_version, which moves when another connection commits, and works out which of the
pages' data changed from a few cheap queries """

import asyncio
import contextlib
import logging
import sqlite3
import threading

from lazylibrarian.filesystem import DIRS

# seconds between the comments that keep a quiet stream, and any proxy on the way, open
HEARTBEAT = 15
# seconds between looks at the database
WATCH = 1
# what the pages show, and a query whose answer changes when it does
SIGNATURES = {
    'queue': "SELECT COUNT(*),MAX(rowid),TOTAL(LENGTH(DLResult)) FROM wanted WHERE Status='Snatched'",
    'history': "SELECT Status,COUNT(*),MAX(rowid) FROM wanted GROUP BY Status",
    'blocklist': "SELECT COUNT(*),MAX(rowid) FROM blocklist",
    'wanted': "SELECT COUNT(*),TOTAL(LENGTH(BookID)) FROM books WHERE Status='Wanted' OR AudioStatus='Wanted'",
    'tasks': "SELECT TOTAL(Start),TOTAL(Finish) FROM jobs",
    # the authors and their books: how many of each are in each state
    'author': "SELECT (SELECT COUNT(*)||'/'||TOTAL(HaveBooks)||'/'||TOTAL(UnignoredBooks) FROM authors),"
              "(SELECT GROUP_CONCAT(c) FROM (SELECT Status||COUNT(*) AS c FROM authors GROUP BY Status)),"
              "(SELECT GROUP_CONCAT(c) FROM (SELECT Status||'/'||AudioStatus||COUNT(*) AS c FROM books "
              "GROUP BY Status, AudioStatus))",
    # the library pages: the books by status, the magazines, comics and their issues, the series
    'library': "SELECT (SELECT GROUP_CONCAT(c) FROM (SELECT Status||'/'||AudioStatus||COUNT(*) AS c FROM books "
               "GROUP BY Status, AudioStatus)),"
               "(SELECT COUNT(*)||GROUP_CONCAT(Status) FROM magazines),"
               "(SELECT COUNT(*)||'/'||TOTAL(LENGTH(IssueDate)) FROM issues),"
               "(SELECT COUNT(*)||GROUP_CONCAT(Status) FROM comics),(SELECT COUNT(*) FROM comicissues),"
               "(SELECT GROUP_CONCAT(c) FROM (SELECT Status||COUNT(*)||'/'||TOTAL(Have) AS c FROM series "
               "GROUP BY Status))",
}

_subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
_lock = threading.Lock()
_watcher: threading.Thread | None = None


def publish(name: str, body: dict):
    """ Tell every page listening, from any thread """
    with _lock:
        subscribers = list(_subscribers)
    for loop, queue in subscribers:
        with contextlib.suppress(RuntimeError):  # its loop has closed
            loop.call_soon_threadsafe(queue.put_nowait, (name, body))


def subscribe(loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
    """ A queue of (name, body) for a page listening on loop. None in it means stop """
    global _watcher
    queue = asyncio.Queue()
    with _lock:
        _subscribers.add((loop, queue))
        if _watcher is None:
            _watcher = threading.Thread(target=_watch, name='EVENTS', daemon=True)
            _watcher.start()
    return queue


def unsubscribe(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    with _lock:
        _subscribers.discard((loop, queue))


def listeners() -> int:
    with _lock:
        return len(_subscribers)


def close():
    """ End every stream, so the web server can stop without waiting for them """
    with _lock:
        subscribers = list(_subscribers)
    for loop, queue in subscribers:
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(queue.put_nowait, None)


def signatures(connection) -> dict:
    found = {}
    for key, query in SIGNATURES.items():
        try:
            found[key] = connection.execute(query).fetchall()
        except sqlite3.Error:  # a table that isn't there yet
            found[key] = None
    return found


def changed(before: dict, after: dict) -> list[str]:
    return [key for key in SIGNATURES if before.get(key) != after.get(key)]


def _still_listened_to() -> bool:
    """ Whether to keep watching. The watcher gives up its place under the lock subscribe takes,
    so a page that subscribes as it stops starts another """
    global _watcher
    with _lock:
        if _subscribers:
            return True
        _watcher = None
        return False


def _watch():
    """ While anyone listens, publish what changed in the database """
    global _watcher
    logger = logging.getLogger(__name__)
    try:
        connection = sqlite3.connect(DIRS.get_dbfile(), timeout=20)
    except sqlite3.Error as why:
        logger.warning(f"Live updates can't read the database: {why}")
        with _lock:
            _watcher = None
        return
    try:
        version = connection.execute('PRAGMA data_version').fetchone()[0]
        last = signatures(connection)
        while _still_listened_to():
            threading.Event().wait(WATCH)
            now = connection.execute('PRAGMA data_version').fetchone()[0]
            if now == version:
                continue
            version = now
            current = signatures(connection)
            keys = changed(last, current)
            last = current
            if keys:
                publish('changed', {'keys': keys})
    except sqlite3.Error as why:
        logger.warning(f"Live updates stopped: {why}")
        with _lock:
            _watcher = None
    finally:
        connection.close()
