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

""" Comics: the comic list and issues, finding, adding, editing, scanning, searching for and marking comics """

import logging
import os
import threading

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from lazylibrarian import comicscan, database
from lazylibrarian.comicid import cv_identify, cx_identify, name_words, title_words
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import path_exists, splitext
from lazylibrarian.formatter import check_int, now, strip_quotes
from lazylibrarian.magazinescan import remove_if_empty
from lazylibrarian.services import InvalidRequestError, NotFoundError
from lazylibrarian.services.files import delete_issue_file
from lazylibrarian.services.magazines import file_date
from lazylibrarian.services.paging import Page, page_of
from lazylibrarian.services.system import start_task

# the comic list fields, in the order the search has always matched them
SEARCH_FIELDS = ('ComicID', 'LatestCover', 'Title', 'Iss_Cnt', 'LastAcquired', 'LatestIssue', 'Status', 'IssueStatus',
                 'Start', 'Publisher', 'Link', 'Genre')
ISSUE_SEARCH_FIELDS = ('Title', 'Cover', 'IssueID', 'IssueAcquired', 'ComicID')
# comic and issue list sorts that sort numbers in text by value
NATURAL_SORTS = ('LastAcquired', 'LatestIssue', 'IssueID', 'IssueAcquired')
MARK_ACTIONS = ('Paused', 'Active', 'Delete', 'Remove', 'Reset', 'Subscribe', 'Unsubscribe')

# the results of the last find_comics, for add_comic to add one of them
found_comics = []


def get_comic(comicid) -> dict:
    db = database.DBConnection()
    try:
        comic = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
    finally:
        db.close()
    if not comic:
        raise NotFoundError(f"Comic ID {comicid} not found")
    return dict(comic)


def update_comic(comicid, title: str, new_id: str, aka: str, description: str) -> str:
    """ Change a comic's title, aka and description, and its id if the new one isn't taken.
        Returns its id now """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        comicdata = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        if not comicdata:
            logger.warning(f"Invalid comicid [{comicid}]")
            raise NotFoundError(f"Comic ID {comicid} not found")
        edited = ""
        if comicdata["Title"] != title:
            edited += "Title "
        if comicdata["aka"] != aka:
            edited += "aka "
        if comicdata["Description"] != description:
            edited += "Description "
        if comicid != new_id:
            if db.match('SELECT ComicID from comics where ComicID=?', (new_id,)):
                logger.debug(f"Unable to use new ID, {new_id} already exists")
            else:
                db.action('PRAGMA foreign_keys = OFF')
                db.action("UPDATE comics SET comicid=? WHERE comicid=?", (new_id, comicid))
                db.action("UPDATE comicissues SET comicid=? WHERE comicid=?", (new_id, comicid))
                db.action('PRAGMA foreign_keys = ON')
                logger.debug(f"Updated comicid {comicid} to {new_id}")
                comicid = new_id
        if edited:
            db.upsert("comics", {'Title': title, 'aka': aka, 'Description': description}, {'ComicID': comicid})
            logger.info(f'Updated [ {edited}] for {comicdata["Title"]}')
        else:
            logger.debug(f'Comic [{comicdata["Title"]}] has not been changed')
    finally:
        db.close()
    return comicid


def start_search(comicid) -> bool:
    """ Search for a comic's issues, in the background """
    logger = logging.getLogger(__name__)
    if not comicid:
        logger.debug("ComicSearch called with no comic ID")
        return False
    if not CONFIG.use_any():
        logger.warning("Not searching for comic, no download methods available. Check config and blocklist")
        return False
    threading.Thread(target=search_comics, name='SEARCHCOMIC', args=[comicid]).start()
    logger.debug(f"Searching for comic ID {comicid}")
    return True


def search_for_comic(comicid):
    """ Search for one comic now """
    get_comic(comicid)
    start_search(comicid)


def list_comics(search: str = '', sort: str = 'Title', descending: bool = False, offset: int = 0,
                limit: int | None = None, subscriber=None) -> Page:
    """ A page of comics, by title unless sorted otherwise, only the ones subscriber subscribes to if
        given. Each item has the comics columns plus Iss_Cnt, how many issues we have. Titles sort
        ignoring case, LastAcquired and LatestIssue sort numbers in text by value """
    serversidelogger = logging.getLogger('special.serverside')
    cmd = ("select comics.*,(select count(*) as counter from comicissues where "
           "comics.comicid = comicissues.comicid) as Iss_Cnt from comics")
    args = []
    db = database.DBConnection()
    try:
        if subscriber:
            res = db.select("SELECT WantID from subscribers WHERE Type='comic' and UserID=?", (subscriber,))
            serversidelogger.debug(f"User subscribes to {len(res)} comics")
            if res:
                cmd += f" WHERE comics.comicid in ({', '.join('?' * len(res))})"
                args.extend(c['WantID'] for c in res)
        cmd += " order by Title"
        rows = db.select(cmd, tuple(args))
    finally:
        db.close()
    sort_key = None
    if sort == 'Title':
        def sort_key(c):
            return c['Title'].lower() if c['Title'] is not None else ''
    return page_of([dict(r) for r in rows], search=search, search_fields=SEARCH_FIELDS, sort=sort, sort_key=sort_key,
                   natural=sort in NATURAL_SORTS, descending=descending, offset=offset, limit=limit)


def start_scan(comicid=None) -> bool:
    """ Scan the library for one comic's issues, or every comic's """
    if comicid:
        return start_task(f'COMICSCAN_{comicid}', comicscan.comic_scan, comicid)
    return start_task('COMICSCAN', comicscan.comic_scan)


def list_issues(comicid, search: str = '', sort: str = 'IssueID', descending: bool = True, offset: int = 0,
                limit: int | None = None) -> Page:
    """ A page of a comic's issues, newest first unless sorted otherwise. Each item has the comicissues
        columns plus Title, the comic's """
    title = get_comic(comicid)['Title']
    db = database.DBConnection()
    try:
        rows = db.select('SELECT * from comicissues WHERE ComicID=? order by IssueID DESC', (comicid,))
    finally:
        db.close()
    issues = [{**dict(r), 'Title': title} for r in rows]
    return page_of(issues, search=search, search_fields=ISSUE_SEARCH_FIELDS, sort=sort,
                   natural=sort in NATURAL_SORTS, descending=descending, offset=offset, limit=limit)


def find_comics(title: str) -> list | None:
    """ Look a comic title up at ComicVine and Comixology, best match first. None if we already have it.
        A title starting CV looks for that ComicVine id. The results are kept for add_comic """
    global found_comics
    logger = logging.getLogger(__name__)
    found_comics = []
    title = strip_quotes(title)
    db = database.DBConnection()
    try:
        exists = db.match('SELECT Title from comics WHERE Title=?', (title,))
    finally:
        db.close()
    if exists:
        logger.debug(f"Comic {title} already exists ({exists['Title']})")
        return None
    results = []
    cvres = cv_identify(title, best=False)
    if title.startswith('CV'):
        for itm in cvres:
            itm['fuzz'] = fuzz.token_sort_ratio(title, itm['seriesid'], processor=default_process)
            results.append(itm)
    else:
        cxres = cx_identify(title, best=False)
        titlewords = ' '.join(title_words(name_words(title)))
        for itm in cvres + cxres:
            itm['fuzz'] = fuzz.token_sort_ratio(titlewords, itm['title'], processor=default_process)
            results.append(itm)
        results = sorted(results, key=lambda x: -(check_int(x["fuzz"], 0)))
    found_comics = results
    return results


def comic_ids() -> list:
    """ The ids of the comics we have """
    db = database.DBConnection()
    try:
        return [c['ComicID'] for c in db.select("SELECT ComicID from comics")]
    finally:
        db.close()


def add_comic(comicid) -> bool:
    """ Add one of the comics the last find_comics found. Returns False if we already have it.
        InvalidRequestError if a ComicVine comic is asked for without an api key, NotFoundError if it
        wasn't among the results """
    logger = logging.getLogger(__name__)
    if comicid.startswith('CV') and not CONFIG['CV_APIKEY']:
        msg = "Please obtain an apikey from https://comicvine.gamespot.com/api/"
        logger.warning(msg)
        raise InvalidRequestError(msg)
    db = database.DBConnection()
    try:
        exists = db.match('SELECT Title from comics WHERE ComicID=?', (comicid,))
        if exists:
            logger.debug(f"Comic {exists['Title']} already exists ({comicid})")
            return False
        itm = next((c for c in found_comics if c['seriesid'] == comicid), None)
        if not itm:
            msg = f"Failed to get data for {comicid}"
            logger.warning(msg)
            raise NotFoundError(msg)
        aka = ''
        akares = cv_identify(itm['title']) or cx_identify(itm['title'])
        if akares and akares[3]['seriesid'] != comicid:
            aka = akares[3]['seriesid']
        db.action('INSERT INTO comics (ComicID, Title, Status, Added, LastAcquired, Updated, LatestIssue, '
                  'IssueStatus, LatestCover, SearchTerm, Start, First, Last, Publisher, Link, aka) '
                  'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (comicid, itm['title'], 'Active', now(), None, now(), None, 'Wanted', None, itm['searchterm'],
                   itm['start'], itm['first'], itm['last'], itm['publisher'], itm['link'], aka))
    finally:
        db.close()
    if CONFIG.get_bool('IMP_AUTOSEARCH'):
        start_search(comicid)
    return True


def mark_comics(action: str, comicids, userid=None) -> int:
    """ Pause or activate comics, delete their issue files and forget them (Delete) or just forget them
        (Remove), reset their latest issue, or subscribe or unsubscribe the user. Returns how many were marked """
    logger = logging.getLogger(__name__)
    marked = 0
    db = database.DBConnection()
    try:
        for itm in comicids:
            if action in ("Paused", "Active"):
                db.upsert("comics", {"Status": action}, {"ComicID": itm})
                logger.info(f'Status of comic {itm} changed to {action}')
            if action == "Delete":
                logger.debug(f'Deleting comic {itm} from disc')
                issuedir = ''
                for issue in db.select('SELECT IssueFile from comicissues WHERE ComicID=?', (itm,)):
                    if delete_issue_file(issue['IssueFile']):
                        logger.debug(f'Issue {issue["IssueFile"]} deleted from disc')
                        issuedir = os.path.dirname(issue['IssueFile'])
                    else:
                        logger.debug(f'Failed to delete {issue["IssueFile"]}')
                # if no issues are left in the folder, delete it (removes any trailing cover images, opf etc)
                if issuedir and CONFIG.get_bool('COMIC_DELFOLDER'):
                    remove_if_empty(os.path.dirname(issuedir), booktype='comic')
                    logger.info(f'Comic {itm} deleted from disc')
            if action in ("Remove", "Delete"):
                db.action('DELETE from comics WHERE ComicID=?', (itm,))
                db.action('DELETE from wanted where BookID=?', (itm,))
                logger.info(f'Comic {itm} removed from database')
            if action == "Reset":
                db.upsert("comics", {"LastAcquired": '', "LatestIssue": '', "LatestCover": '', "IssueStatus": "Wanted"},
                          {"ComicID": itm})
                logger.info(f'Comic {itm} details reset')
            if action == 'Subscribe' and userid:
                if db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?", (userid, 'comic', itm)):
                    logger.debug(f"User {userid} is already subscribed to {itm}")
                else:
                    db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)', (userid, 'comic', itm))
                    logger.debug(f"Subscribe {userid} to comic {itm}")
            if action == 'Unsubscribe' and userid:
                db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?', (userid, 'comic', itm))
                for iss in db.select('SELECT issueid from comicissues where comicid=?', (itm,)):
                    db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                              (userid, 'comic', iss['issueid']))
                logger.debug(f"Unsubscribe {userid} to comic {itm}")
            if action in MARK_ACTIONS:
                marked += 1
    finally:
        db.close()
    return marked


def set_latest(db, comicid):
    """ Set the comic's latest issue and cover from its newest issue, when it was last acquired from that
        issue's file and when it was added from its oldest issue's file """
    cmd = "select IssueID,IssueAcquired,IssueFile from comicissues where ComicID=? order by IssueID "
    newest = db.match(cmd + 'DESC', (comicid,))
    oldest = db.match(cmd + 'ASC', (comicid,))
    if newest and oldest:
        cover = splitext(newest['IssueFile'])[0] + '.jpg' if path_exists(newest['IssueFile']) else ''
        new_value_dict = {'LatestIssue': newest['IssueID'], 'LatestCover': cover,
                          'LastAcquired': file_date(newest['IssueFile']), 'Added': file_date(oldest['IssueFile'])}
    else:
        new_value_dict = {'LatestIssue': '', 'LastAcquired': '', 'LatestCover': '', 'Added': ''}
    db.upsert("comics", new_value_dict, {'ComicID': comicid})


def mark_issues(action: str, issues) -> str | None:
    """ Delete the files of comic issues (comicid_issueid each) and forget them (Delete), or just forget
        them (Remove). Returns the comicid of the last one """
    logger = logging.getLogger(__name__)
    comicid = None
    db = database.DBConnection()
    try:
        for itm in issues:
            comicid, issueid = itm.split('_')
            issue = db.match("SELECT IssueFile,Title,comics.ComicID from comics,comicissues WHERE "
                             "comics.ComicID = comicissues.ComicID and comics.ComicID=? and IssueID=?",
                             (comicid, issueid))
            if not issue:
                continue
            if action == "Delete" and delete_issue_file(issue['IssueFile']):
                logger.info(f'Issue {issueid} of {issue["Title"]} deleted from disc')
            if action in ("Remove", "Delete"):
                db.action('DELETE from comicissues WHERE ComicID=? and IssueID=?', (comicid, issueid))
                logger.info(f'Issue {issueid} of {issue["Title"]} removed from database')
                set_latest(db, comicid)
    finally:
        db.close()
    return comicid
