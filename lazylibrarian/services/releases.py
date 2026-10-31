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
import traceback

from lazylibrarian import database, quality
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import path_isfile
from lazylibrarian.formatter import check_int, get_list, now, nzbdate2format, plural
from lazylibrarian.providers import (
    iterate_over_direct_sites,
    iterate_over_irc_sites,
    iterate_over_rss_sites,
    iterate_over_torrent_sites,
    iterate_over_znab_sites,
)
from lazylibrarian.resultlist import download_result, evaluate_results
from lazylibrarian.services import InvalidRequestError, NotFoundError, history, profiles

LIBRARIES = {'ebook': 'eBook', 'audiobook': 'AudioBook'}
PROTOCOLS = {**history.PROTOCOLS, 'direct': 'direct', 'irc': 'irc'}
# how long the releases of a search can be downloaded from, in seconds, as in Sonarr
KEEP = 30 * 60
_releases: dict[str, tuple[float, list, dict]] = {}
_lock = threading.Lock()


def _search_book(book_id, library: str) -> dict:
    """ The book as the automatic search describes it """
    db = database.DBConnection()
    try:
        row = db.match('SELECT BookID,AuthorName,BookName,BookSub,BookFile,AudioFile FROM books,authors '
                       'WHERE books.AuthorID=authors.AuthorID AND BookID=?', (book_id,))
        profile = profiles.for_library(library, db)
    finally:
        db.close()
    if not row:
        raise NotFoundError(f'No book {book_id}')
    searchterm = f"{row['AuthorName']} {row['BookName']}"
    if row['BookSub']:
        searchterm += f": {row['BookSub']}"
    # the file there is, a release worse than it is turned down
    path = row['AudioFile' if library == 'AudioBook' else 'BookFile']
    current = ''
    if profile and path and path_isfile(path):
        current = profiles.book_quality(profile, quality.of_book(path, profiles.LIBRARIES[library]))
    return {'bookid': row['BookID'], 'authorName': row['AuthorName'], 'bookName': row['BookName'],
            'bookSub': row['BookSub'] or '', 'library': library, 'searchterm': searchterm,
            'current_quality': current}


def _provider_results(book: dict, searchtype: str) -> list[tuple[str, list]]:
    """ What each kind of provider found, as the automatic search's first try asks them. One kind
    failing is logged and the others are still asked """
    logger = logging.getLogger(__name__)
    found = []
    for source, used, iterate in (('nzb', CONFIG.use_nzb, iterate_over_znab_sites),
                                  ('tor', CONFIG.use_tor, iterate_over_torrent_sites),
                                  ('direct', CONFIG.use_direct, iterate_over_direct_sites),
                                  ('irc', CONFIG.use_irc, iterate_over_irc_sites),
                                  ('rss', CONFIG.use_rss, None)):
        if not used():
            continue
        try:
            if iterate:
                results, nprov = iterate(book, searchtype)
            else:
                results, nprov, _dltypes = iterate_over_rss_sites()
        except Exception:
            logger.error(f"Interactive search of the {source} providers failed: {traceback.format_exc()}")
            continue
        if nprov and results:
            found.append((source, results))
    return found


def _evaluated(results: list, book: dict, searchtype: str, source: str) -> list[dict]:
    """ The results scored and checked; when that fails, each on its own, leaving out any that can't
    be, so one odd result doesn't lose the rest """
    logger = logging.getLogger(__name__)
    try:
        return evaluate_results(results, book, searchtype, source)
    except Exception:
        logger.error(f"Evaluating the {source} results failed: {traceback.format_exc()}")
    evaluated = []
    for result in results:
        try:
            evaluated += evaluate_results([result], book, searchtype, source)
        except Exception as why:
            logger.warning(f"Leaving out {result.get('tor_title') or result.get('nzbtitle')}: "
                           f"{type(why).__name__} {why}")
    return evaluated


def search(book_id, media_type: str) -> list[dict]:
    """ The releases for a book (ebook) or audiobook, the ones the automatic search would take
    first, then by score. Each has an id to download it by, and its rejections: none means the
    automatic search could take it """
    if media_type not in LIBRARIES:
        raise InvalidRequestError('Interactive search is for books and audiobooks')
    if not CONFIG.total_active_providers():
        raise InvalidRequestError('No search providers are enabled, add one in Settings, Indexers')
    book = _search_book(book_id, LIBRARIES[media_type])
    searchtype = 'audio' if media_type == 'audiobook' else 'book'
    ratio = CONFIG.get_int('MATCH_RATIO')
    releases = []
    now = time.monotonic()
    with _lock:
        for key in [key for key, (when, _, _) in _releases.items() if now - when > KEEP]:
            del _releases[key]
    for source, results in _provider_results(book, searchtype):
        for result in _evaluated(results, book, searchtype, source):
            rejections = list(result['rejections'])
            if result['score'] < ratio:
                rejections.append(f"Scores {round(result['score'])}, under the {ratio} the automatic search "
                                  f"needs (Settings, match ratio)")
            release_id = hashlib.sha1(f"{book_id}|{media_type}|{result['provider']}|{result['url']}".encode(),
                                      usedforsecurity=False).hexdigest()[:16]
            match = [result['score'], result['new_value_dict'], result['control_value_dict'], result['priority'],
                     max(result['seeders'], 0), result['quality_rank']]
            with _lock:
                _releases[release_id] = (now, match, book)
            releases.append({'id': release_id, 'title': result['title'], 'indexer': CONFIG.disp_name(result['provider']),
                             'protocol': PROTOCOLS.get(result['mode'], result['mode'] or ''),
                             'size': round(result['size'] * 1048576), 'seeders': result['seeders'],
                             'score': round(result['score'], 1), 'quality': quality.name(result['quality']),
                             'quality_rank': result['quality_rank'], 'rejections': rejections,
                             'approved': not rejections})
    # as the automatic search would choose: what it would take, the best quality, then the best match
    releases.sort(key=lambda release: (not release['approved'], -release['quality_rank'], -release['score']))
    logging.getLogger(__name__).info(f"Interactive search for {book['searchterm']} found {len(releases)} "
                                     f"{plural(len(releases), 'release')}, "
                                     f"{sum(release['approved'] for release in releases)} the automatic search "
                                     f"could take")
    return releases


def download(release_id: str, issue: str = '') -> str:
    """ Download a release from a search, as the automatic search downloads the one it chooses; a
    magazine's filed under issue when one is given, typed as in an issue's Edit, else the one it says.
    Returns what happened """
    with _lock:
        kept = _releases.get(release_id)
    if not kept:
        raise NotFoundError('That release is no longer known, search again')
    _when, match, book = kept
    if book.get('magazine'):
        return _download_issue(match, issue)
    result = download_result(match, book)
    title = match[1]['NZBtitle']
    if result == 2:
        return f"Downloading {title}"
    if result == 1:
        raise InvalidRequestError(f"{book['bookName']} is already being downloaded, see Activity, Queue")
    raise InvalidRequestError(f"{title} could not be sent to the download client, see the log")



# --- a magazine's issues, as Sonarr searches for an episode

# what each kind of provider's results are, as the magazine search takes them
MAG_MODES = {'tor': 'torrent', 'direct': 'direct', 'irc': 'irc'}
NO_DATE = 'Fri, 01 Jan 1970 00:00:00 +0100'


def _magazine_results(book: dict) -> list[dict]:
    """ What the providers have for a magazine by one search term, each in the form a newznab
    provider's result has, as the magazine search puts them """
    found = []
    for source, results in _provider_results(book, 'mag'):
        for item in results:
            if source == 'nzb':
                found.append(dict(item))
            elif source != 'rss' or 'M' in item.get('types', ''):
                found.append({'bookid': book['bookid'], 'nzbprov': item['tor_prov'], 'nzbtitle': item['tor_title'],
                              'nzburl': item['tor_url'], 'nzbdate': item.get('tor_date') or NO_DATE,
                              'nzbsize': item['tor_size'],
                              'nzbmode': item.get('tor_type') if source == 'rss' else MAG_MODES[source]})
    return found


def _posted(nzbdate: str) -> str:
    """ When a result was posted, yyyy-mm-dd, '' when it came without a date """
    try:
        year, month, day = nzbdate2format(nzbdate).split('-')
        posted = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except (ValueError, AttributeError):
        return ''
    return '' if posted < '1971' else posted


def _wanted_issue(db, title: str, issue: str) -> str:
    """ An issue as the library keeps it, typed as in an issue's Edit, '' for none """
    from lazylibrarian import magreleases  # noqa: PLC0415, it imports the magazine scan
    if not (issue or '').strip():
        return ''
    issuedate, why = magreleases.entered(db, title, issue, strict=False)
    if not issuedate:
        raise InvalidRequestError(why)
    return issuedate


def search_issues(title: str, issue: str = '') -> list[dict]:
    """ Interactive search for a magazine, as Sonarr's for an episode: every release the providers have
    for it, with the issue each one is and the reasons the magazine search would turn it down. With an
    issue, typed as in an issue's Edit or as the library keeps it, its releases come first (matches) """
    from lazylibrarian import magreleases, searchmag  # noqa: PLC0415, they import most of LazyLibrarian
    if not CONFIG.total_active_providers():
        raise InvalidRequestError('No search providers are enabled, add one in Settings, Indexers')
    db = database.DBConnection()
    try:
        magazine = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (title,))
        if not magazine:
            raise NotFoundError(f'No magazine {title}')
        title = magazine['Title']
        wanted_issue = _wanted_issue(db, title, issue)
    finally:
        db.close()
    datetype = magazine['DateType'] or ''
    results, seen = [], set()
    for searchterm in searchmag.search_terms(magazine):
        for nzb in _magazine_results({'bookid': title, 'searchterm': searchterm, 'datetype': datetype,
                                      'library': 'magazine'}):
            if nzb['nzburl'] not in seen:
                seen.add(nzb['nzburl'])
                results.append(nzb)
    now = time.monotonic()
    with _lock:
        for key in [key for key, (when, _, _) in _releases.items() if now - when > KEEP]:
            del _releases[key]
    releases = []
    db = database.DBConnection()
    try:
        terms = get_list(magazine['Regex'], ',') or [title]
        scheme = magreleases.scheme_of(db, title)
        pairs = magreleases.known_pairs(db, title, terms, [nzb['nzbtitle'] for nzb in results])
        profile = profiles.for_item('magazine', title, db)
        for nzb in results:
            nzb['quality'] = profiles.release_quality(
                profile, quality.of_release(nzb['nzbtitle'], 'magazine')) if profile else quality.UNKNOWN
            found, rejections = searchmag.check_release(db, magazine, nzb, terms, datetype, scheme, pairs, profile)
            issuedate = found['issuedate'] if found and found['kind'] == magreleases.ISSUE else ''
            if found and found['kind'] is not None and not issuedate:
                rejections.append(found['reason'])
            if issuedate and db.match('SELECT IssueID from issues WHERE Title=? AND IssueDate=?', (title, issuedate)):
                rejections.append('That issue is in the library already')
            release_id = hashlib.sha1(f"{title}|magazine|{nzb['nzbprov']}|{nzb['nzburl']}".encode(),
                                      usedforsecurity=False).hexdigest()[:16]
            with _lock:
                _releases[release_id] = (now, {'nzb': nzb, 'issue': issuedate}, {'magazine': title})
            posted = _posted(nzb['nzbdate'])
            releases.append({'id': release_id, 'title': nzb['nzbtitle'], 'indexer': CONFIG.disp_name(nzb['nzbprov']),
                             'protocol': PROTOCOLS.get(nzb['nzbmode'], nzb['nzbmode'] or ''),
                             'size': check_int(nzb['nzbsize'], 0), 'posted': posted,
                             'issue': issuedate, 'quality': quality.name(nzb['quality']),
                             'quality_rank': profiles.rank(profile, nzb['quality']) if profile else 0,
                             'rejections': rejections, 'approved': not rejections,
                             'matches': bool(wanted_issue) and issuedate == wanted_issue})
    finally:
        db.close()
    # the issue asked for first, what could be taken, the best quality, then the newest
    releases.sort(key=lambda release: release['posted'], reverse=True)
    releases.sort(key=lambda release: (not release['matches'], not release['approved'], -release['quality_rank']))
    logging.getLogger(__name__).info(
        f"Interactive search for {title}{' ' + wanted_issue if wanted_issue else ''} found {len(releases)} "
        f"{plural(len(releases), 'release')}, {sum(release['matches'] for release in releases)} of the issue")
    return releases


def _download_issue(kept: dict, issue: str = '') -> str:
    """ Download a magazine's release from a search, filed under issue, or the issue it says """
    from lazylibrarian import searchmag  # noqa: PLC0415, it imports most of LazyLibrarian
    nzb = kept['nzb']
    title = nzb['bookid']
    db = database.DBConnection()
    try:
        issuedate = _wanted_issue(db, title, issue) or kept['issue']
        if not issuedate:
            raise InvalidRequestError(f"{nzb['nzbtitle']} doesn't say which issue it is, choose the issue")
        if db.match("SELECT NZBurl from wanted WHERE NZBurl=? AND Status='Snatched'", (nzb['nzburl'],)):
            raise InvalidRequestError(f"{nzb['nzbtitle']} is already being downloaded, see Activity, Queue")
        db.upsert('wanted', {'BookID': title, 'NZBtitle': nzb['nzbtitle'], 'NZBdate': now(), 'NZBprov': nzb['nzbprov'],
                             'Status': 'Wanted', 'NZBsize': round(check_int(nzb['nzbsize'], 0) / 1048576, 2),
                             'AuxInfo': issuedate, 'NZBmode': nzb['nzbmode']}, {'NZBurl': nzb['nzburl']})
    finally:
        db.close()
    searchmag.download_maglist([{'bookid': title, 'nzbprov': nzb['nzbprov'], 'nzbtitle': nzb['nzbtitle'],
                                 'nzburl': nzb['nzburl'], 'nzbmode': nzb['nzbmode']}], 'wanted')
    db = database.DBConnection()
    try:
        row = db.match('SELECT Status,DLResult from wanted WHERE NZBurl=?', (nzb['nzburl'],))
    finally:
        db.close()
    if row and row['Status'] == 'Snatched':
        return f"Downloading {nzb['nzbtitle']} as {title} {issuedate}"
    raise InvalidRequestError(f"{nzb['nzbtitle']} could not be sent to the download client"
                              f"{': ' + row['DLResult'] if row and row['DLResult'] else ', see the log'}")


def search_issue(title: str, issue: str) -> str:
    """ The automatic search for one issue: the best release of it the magazine search could take,
    downloaded. Returns what happened """
    releases = search_issues(title, issue)
    chosen = next((release for release in releases if release['matches'] and release['approved']), None)
    if not chosen:
        found = sum(release['matches'] for release in releases)
        return (f"No release of {title} {issue} could be taken, {found} {plural(found, 'was')} found, see Interactive "
                f"Search" if found else f"No release of {title} {issue} was found")
    return download(chosen['id'])
