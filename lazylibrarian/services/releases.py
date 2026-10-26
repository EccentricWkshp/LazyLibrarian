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

""" Interactive Search, like Sonarr's: every release the search providers have for a book, scored
and checked by the same code as the automatic search, with each reason it would turn one down, so
it's plain why the automatic search didn't take something. Downloading one goes the way the
automatic search's choice does. Releases are kept a while by an id, as Sonarr keeps them by guid """

import hashlib
import logging
import threading
import time

from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import plural
from lazylibrarian.providers import (
    iterate_over_direct_sites,
    iterate_over_irc_sites,
    iterate_over_rss_sites,
    iterate_over_torrent_sites,
    iterate_over_znab_sites,
)
from lazylibrarian.resultlist import download_result, evaluate_results
from lazylibrarian.services import InvalidRequestError, NotFoundError, queue

LIBRARIES = {'ebook': 'eBook', 'audiobook': 'AudioBook'}
PROTOCOLS = {**queue.PROTOCOLS, 'direct': 'direct', 'irc': 'irc'}
# how long the releases of a search can be downloaded from, in seconds, as in Sonarr
KEEP = 30 * 60
_releases: dict[str, tuple[float, list, dict]] = {}
_lock = threading.Lock()


def _search_book(book_id, library: str) -> dict:
    """ The book as the automatic search describes it """
    db = database.DBConnection()
    try:
        row = db.match('SELECT BookID,AuthorName,BookName,BookSub FROM books,authors '
                       'WHERE books.AuthorID=authors.AuthorID AND BookID=?', (book_id,))
    finally:
        db.close()
    if not row:
        raise NotFoundError(f'No book {book_id}')
    searchterm = f"{row['AuthorName']} {row['BookName']}"
    if row['BookSub']:
        searchterm += f": {row['BookSub']}"
    return {'bookid': row['BookID'], 'authorName': row['AuthorName'], 'bookName': row['BookName'],
            'bookSub': row['BookSub'] or '', 'library': library, 'searchterm': searchterm}


def _provider_results(book: dict, searchtype: str) -> list[tuple[str, list]]:
    """ What each kind of provider found, as the automatic search's first try asks them """
    found = []
    for source, used, iterate in (('nzb', CONFIG.use_nzb, iterate_over_znab_sites),
                                  ('tor', CONFIG.use_tor, iterate_over_torrent_sites),
                                  ('direct', CONFIG.use_direct, iterate_over_direct_sites),
                                  ('irc', CONFIG.use_irc, iterate_over_irc_sites)):
        if used():
            results, nprov = iterate(book, searchtype)
            if nprov and results:
                found.append((source, results))
    if CONFIG.use_rss():
        results, nprov, _dltypes = iterate_over_rss_sites()
        if nprov and results:
            found.append(('rss', results))
    return found


def search(book_id, media_type: str) -> list[dict]:
    """ The releases for a book (ebook) or audiobook, the ones the automatic search would take
    first, then by score. Each has an id to download it by, and its rejections: none means the
    automatic search could take it """
    if media_type not in LIBRARIES:
        raise InvalidRequestError('Interactive search is for books and audiobooks')
    if not CONFIG.total_active_providers():
        raise InvalidRequestError('No search providers are enabled, add one in Settings, Providers')
    book = _search_book(book_id, LIBRARIES[media_type])
    searchtype = 'audio' if media_type == 'audiobook' else 'book'
    ratio = CONFIG.get_int('MATCH_RATIO')
    releases = []
    now = time.monotonic()
    with _lock:
        for key in [key for key, (when, _, _) in _releases.items() if now - when > KEEP]:
            del _releases[key]
    for source, results in _provider_results(book, searchtype):
        for result in evaluate_results(results, book, searchtype, source):
            rejections = list(result['rejections'])
            if result['score'] < ratio:
                rejections.append(f"Scores {round(result['score'])}, under the {ratio} the automatic search "
                                  f"needs (Settings, match ratio)")
            release_id = hashlib.sha1(f"{book_id}|{media_type}|{result['provider']}|{result['url']}".encode(),
                                      usedforsecurity=False).hexdigest()[:16]
            match = [result['score'], result['new_value_dict'], result['control_value_dict'], result['priority'],
                     max(result['seeders'], 0)]
            with _lock:
                _releases[release_id] = (now, match, book)
            releases.append({'id': release_id, 'title': result['title'], 'indexer': CONFIG.disp_name(result['provider']),
                             'protocol': PROTOCOLS.get(result['mode'], result['mode'] or ''),
                             'size': round(result['size'] * 1048576), 'seeders': result['seeders'],
                             'score': round(result['score'], 1), 'rejections': rejections,
                             'approved': not rejections})
    releases.sort(key=lambda release: (not release['approved'], -release['score']))
    logging.getLogger(__name__).info(f"Interactive search for {book['searchterm']} found {len(releases)} "
                                     f"{plural(len(releases), 'release')}, "
                                     f"{sum(release['approved'] for release in releases)} the automatic search "
                                     f"could take")
    return releases


def download(release_id: str) -> str:
    """ Download a release from a search, as the automatic search downloads the one it chooses.
    Returns what happened """
    with _lock:
        kept = _releases.get(release_id)
    if not kept:
        raise NotFoundError('That release is no longer known, search again')
    _when, match, book = kept
    result = download_result(match, book)
    title = match[1]['NZBtitle']
    if result == 2:
        return f"Downloading {title}"
    if result == 1:
        raise InvalidRequestError(f"{book['bookName']} is already being downloaded, see Activity, Queue")
    raise InvalidRequestError(f"{title} could not be sent to the download client, see the log")
