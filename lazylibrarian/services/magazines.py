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

""" Magazines: the magazine list, issues and past issues, renaming and editing them, adding,
    searching for and marking magazines and issues """

import datetime
import logging
import os
import subprocess
import threading
import traceback
import uuid
from shutil import copyfile

import lazylibrarian
from lazylibrarian import database, pages, wikidata
from lazylibrarian.cache import ImageType, cache_img
from lazylibrarian.calibre import calibredb, get_calibre_id
from lazylibrarian.calibre_integration import send_mag_issue_to_calibre
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, path_exists, setperm, syspath
from lazylibrarian.formatter import (
    check_int,
    get_list,
    make_unicode,
    now,
    plural,
    replace_all,
    today,
)
from lazylibrarian.images import (
    coverswap,
    create_mag_cover,
    extract_image_from_page,
    read_pdf_tags,
    write_pdf_tags,
)
from lazylibrarian.magazinescan import get_dateparts, magazine_scan, remove_if_empty, rename_issue
from lazylibrarian.searchmag import download_maglist, search_magazines
from lazylibrarian.services import InvalidRequestError, NotFoundError
from lazylibrarian.services.files import (
    delete_issue_file,
    remove_from_calibre,
    update_calibre_cover,
)
from lazylibrarian.services.paging import Page, page_of

# the magazine list fields the search looks in
SEARCH_FIELDS = ('Title', 'LatestCover', 'Iss_Cnt', 'LastAcquired', 'IssueDate', 'Status', 'IssueStatus', 'Genre')
ISSUE_SEARCH_FIELDS = ('Title', 'Cover', 'IssueDate', 'IssueAcquired', 'IssueID')
PAST_ISSUE_FIELDS = ('NZBurl', 'NZBtitle', 'NZBdate', 'AuxInfo', 'NZBprov')
# magazine and issue list sorts that sort numbers in text by value
NATURAL_SORTS = ('LastAcquired', 'IssueDate', 'IssueAcquired')
MARK_ACTIONS = ('Paused', 'Active', 'Delete', 'tag', 'Scan', 'Search', 'Remove', 'Reset', 'Subscribe', 'Unsubscribe')

# how far a rename or a mark of several issues got, as current/total/percent
issue_progress = ''


def set_issue_progress(current: int, total: int):
    global issue_progress
    issue_progress = f"{current}/{total}/{int(current * 100 / total)}" if total else ''


def list_magazines(search: str = '', sort: str = 'Title', descending: bool = False, offset: int = 0,
                   limit: int | None = None, subscriber=None) -> Page:
    """ A page of magazines, by title unless sorted otherwise, only the ones subscriber subscribes to if
        given. Each item has the magazines columns plus Iss_Cnt, how many issues we have. Titles sort
        ignoring case, LastAcquired and IssueDate sort numbers in text by value """
    serversidelogger = logging.getLogger('special.serverside')
    cmd = ("select magazines.*,(select count(*) as counter from issues where "
           "magazines.title = issues.title) as Iss_Cnt from magazines")
    args = []
    db = database.DBConnection()
    try:
        if subscriber:
            res = db.select("SELECT WantID from subscribers WHERE Type='magazine' and UserID=?", (subscriber,))
            serversidelogger.debug(f"User subscribes to {len(res)} magazines")
            if res:
                cmd += f" WHERE Title in ({', '.join('?' * len(res))})"
                args.extend(m['WantID'] for m in res)
        cmd += " order by Title"
        serversidelogger.debug(f"{cmd} {args}")
        rows = db.select(cmd, tuple(args))
    finally:
        db.close()
    sort_key = None
    if sort == 'Title':
        def sort_key(m):
            return m['Title'].lower() if m['Title'] is not None else ''
    return page_of([dict(r) for r in rows], search=search, search_fields=SEARCH_FIELDS, sort=sort, sort_key=sort_key,
                   natural=sort in NATURAL_SORTS, descending=descending, offset=offset, limit=limit)


def get_magazine(title) -> dict:
    """ A magazine, its title matched ignoring case """
    db = database.DBConnection()
    try:
        magazine = db.match("SELECT * from magazines WHERE Title=? COLLATE NOCASE", (title,))
    finally:
        db.close()
    if not magazine:
        raise NotFoundError(f"Magazine {title} not found")
    return dict(magazine)


def rename_magazine(old_title: str, new_title: str) -> tuple[int, int]:
    """ Rename a magazine and move its issue files to match, in Calibre too if it's used for magazines.
        Returns (issues moved, issues that failed to move). InvalidRequestError if the new title is taken """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        if db.match("SELECT Title from magazines WHERE Title=? COLLATE NOCASE", (new_title,)):
            raise InvalidRequestError(f'Title {new_title} already exists, unable to rename')
    finally:
        db.close()
    logger.debug(f"Changing title [{old_title}] to [{new_title}]")
    passed = failed = 0
    db = database.DBConnection()
    try:
        db.action('PRAGMA foreign_keys = OFF')
        db.action("UPDATE magazines SET Title=? WHERE Title=? COLLATE NOCASE", (new_title, old_title))
        db.action("UPDATE issues SET Title=? WHERE Title=? COLLATE NOCASE", (new_title, old_title))
        db.action('PRAGMA foreign_keys = ON')
        db.commit()
        # rename files/folders to match, and issuefile to match new location
        issues = db.select("SELECT IssueDate,IssueFile,IssueID from issues WHERE Title=?", (new_title,))
        for current, issue in enumerate(issues, start=1):
            set_issue_progress(current, len(issues))
            calibre_id = None
            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                data = dict(db.match('SELECT * from issues WHERE IssueID=?', (issue['IssueID'],)))
                data['Title'] = old_title
                calibre_id = get_calibre_id(data, try_filename=False)
                if calibre_id:
                    logger.debug(f"Found calibre ID {calibre_id} for {old_title} {issue['IssueDate']}")
            fname, err = rename_issue(issue['IssueID'])
            if err:
                logger.warning(f"Failed to move file {issue['IssueFile']}: {err}")
                failed += 1
                continue
            logger.debug(f"Renamed {issue['IssueDate']} to {os.path.basename(fname)}")
            passed += 1
            if calibre_id:
                readd_to_calibre(db, issue['IssueID'], calibre_id)
    except Exception:
        logger.error(f'Unhandled exception in magazine_update: {traceback.format_exc()}')
    finally:
        db.close()
        set_issue_progress(0, 0)
    return passed, failed


def readd_to_calibre(db, issueid, calibre_id):
    """ Replace an issue in Calibre after its file moved, Calibre may rename it again """
    logger = logging.getLogger(__name__)
    res, err, rc = calibredb('remove', [calibre_id])
    logger.debug(f"Remove result: {res} [{err}] {rc}")
    data = dict(db.match('SELECT * from issues WHERE IssueID=?', (issueid,)))
    data['mag_genres'] = db.match('SELECT Genre from magazines WHERE Title=?', (data['Title'],))['Genre']
    res, filename, _ = send_mag_issue_to_calibre(data)
    logger.debug(f"Add result: {res}")
    if res and filename:
        db.action("UPDATE issues SET IssueFile=? WHERE IssueID=?", (filename, issueid))


def list_issues(title: str, search: str = '', sort: str = 'IssueDate', descending: bool = True, offset: int = 0,
                limit: int | None = None) -> Page:
    """ A page of a magazine's issues, newest first unless sorted otherwise """
    db = database.DBConnection()
    try:
        rows = db.select('SELECT * from issues WHERE Title=? order by IssueDate DESC', (title,))
    finally:
        db.close()
    return page_of([dict(r) for r in rows], search=search, search_fields=ISSUE_SEARCH_FIELDS, sort=sort,
                   natural=sort in NATURAL_SORTS, descending=descending, offset=offset, limit=limit)


def issue_for_edit(issueid) -> tuple[dict, dict]:
    """ An issue and the tags in its file """
    db = database.DBConnection()
    try:
        issue = db.match("SELECT Title,IssueDate,IssueID,IssueFile from issues WHERE IssueID=?", (issueid,))
    finally:
        db.close()
    if not issue:
        raise NotFoundError(f"Missing issue {issueid}")
    # only a PDF has tags, pypdf can't read the other formats
    is_pdf = str(issue['IssueFile'] or '').lower().endswith('.pdf')
    return dict(issue), read_pdf_tags(issue['IssueFile']) if is_pdf else {}


def date_matches_type(dateparts: dict, datetype: str) -> bool:
    """ Does an issue date/number have every part (Day Month Year Vol Iss, MM for two months) the
        magazine's date type needs """
    style = dateparts['style']
    if not style:
        return False
    if not datetype:
        return True
    needs = (('M', [1, 2, 3, 4, 5, 6, 7, 12]), ('D', [3, 5, 6]), ('MM', [1]),
             ('V', [2, 8, 9, 10, 11, 12, 13, 14, 17, 18]), ('I', [2, 10, 11, 12, 13, 14, 16, 17, 18]),
             ('Y', [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 13, 15, 16, 18]))
    return all(style in styles for part, styles in needs if part in datetype)


def update_issue(issueid, magtitle: str, issuenum: str, new_tags: dict, old_tags: dict) -> tuple[str, str]:
    """ Move an issue to another magazine title (added if new) and/or issue date/number, and change the
        tags in its file. Returns (the magazine title to show, what happened). NotFoundError for a missing
        issue, InvalidRequestError if a new title is empty or the file can't be moved """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        issue = db.match("SELECT Title,IssueDate,IssueFile,Cover,IssueID from issues WHERE IssueID=?", (issueid,))
        if not issue:
            raise NotFoundError(f"Missing issue {issueid}")
        magazine = db.match("SELECT DateType,IssueDate from magazines WHERE Title=? COLLATE NOCASE", (magtitle,))
        datetype = magazine['DateType'] if magazine else ''
        mostrecentissue = magazine['IssueDate'] if magazine else ''
        redirect = issue['Title']
        if not date_matches_type(get_dateparts(issuenum, datetype=datetype), datetype):
            response = f'Date {issuenum} not in a recognised date format [{datetype}]'
            logger.debug(response)
            return redirect, response
        if not magtitle and issuenum:
            response = (f"Issue {issue['IssueDate']} of {issue['Title']} is unchanged. "
                        f"Insufficient information, need Title and valid IssueNum/Date")
            logger.debug(response)
            return redirect, response

        old_path = os.path.dirname(issue['IssueFile'])
        edited = ''
        if issue["Title"] != magtitle:
            edited = 'Title '
        if issue["IssueDate"] != issuenum:
            edited += 'Date/Num '
        if old_tags == new_tags:
            logger.debug("No tag changes")
        else:
            edited += 'Tags '
        if not edited:
            response = f'Issue {issue["IssueDate"]} of {issue["Title"]} is unchanged'
            logger.debug(response)
            return redirect, response

        if issue["Title"] != magtitle:
            if not magazine:
                if not magtitle:
                    logger.warning("Missing magazine title")
                    raise InvalidRequestError("Magazine title missing")
                logger.debug(f"Magazine title [{magtitle}] not found, adding it")
                db.upsert("magazines", {"LastAcquired": today(), "IssueStatus": CONFIG['FOUND_STATUS'],
                                        "IssueDate": "", "LatestCover": ""}, {"Title": magtitle})
            db.action("UPDATE issues SET Title=? WHERE IssueID=?", (magtitle, issue['IssueID']))
        db.action("UPDATE issues SET IssueDate=? WHERE IssueID=?", (issuenum, issue['IssueID']))

        fname, err = rename_issue(issue['IssueID'], tags=new_tags)
        response = f'Issue {issue["IssueDate"]} of {issue["Title"]}, changed to {os.path.basename(fname)} {edited}'
        if err:
            raise InvalidRequestError(f"Magazine IssueFile {issue['IssueFile']} move failed: {err}")

        if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
            calibre_id = get_calibre_id(issue, try_filename=False)
            if calibre_id:
                logger.debug(f"Found calibre ID {calibre_id} for {issue['Title']} {issue['IssueDate']}")
                readd_to_calibre(db, issue['IssueID'], calibre_id)

        # if no magazine issues left in the folder, delete it (removes any trailing cover images, opf etc)
        remove_if_empty(old_path)

        if not mostrecentissue:
            older = False
        elif mostrecentissue.isdigit() and str(issuenum).isdigit():
            older = int(mostrecentissue) > int(issuenum)  # issuenumber
        else:
            older = mostrecentissue > issuenum  # YYYY-MM-DD
        new_value_dict = {"LastAcquired": today(), "IssueStatus": CONFIG['FOUND_STATUS']}
        if not older:
            new_value_dict.update({"IssueDate": issuenum, "LatestCover": issue['Cover']})
        db.upsert("magazines", new_value_dict, {"Title": magtitle})
    finally:
        db.close()
    # show the old title if it has issues left, the new one if not
    return (issue['Title'] if set_latest(issue['Title']) else magtitle), response


def abort_marking():
    """ Stop a mark of several issues or magazines """
    lazylibrarian.MARK_ISSUES = False
    logging.getLogger(__name__).warning('Mark Issues/Magazines Aborted by user')


def list_past_issues(status: str, magazine: str | None = None, search: str = '', sort: str = 'NZBurl',
                     descending: bool = False, offset: int = 0, limit: int | None = None) -> Page:
    """ A page of past issues, the search results not wanted for a magazine at the time, with a status,
        and for one magazine if given """
    cmd = f"SELECT {', '.join(PAST_ISSUE_FIELDS)}, BookID from pastissues WHERE Status=?"
    args = [status]
    if magazine:
        cmd += " AND BookID=?"
        args.append(magazine)
    logging.getLogger('special.serverside').debug(f"list_past_issues {cmd}: {str(args)}")
    db = database.DBConnection()
    try:
        rows = db.select(cmd, tuple(args))
    finally:
        db.close()
    return page_of([dict(r) for r in rows], search=search, search_fields=PAST_ISSUE_FIELDS, sort=sort,
                   descending=descending, offset=offset, limit=limit)


def mark_past_issues(action: str, nzburls) -> int:
    """ Remove past issues, set them Ignored or Skipped, or want them (copied into the wanted table and
        downloaded in the background). Returns how many were changed """
    logger = logging.getLogger(__name__)
    maglist = []
    db = database.DBConnection()
    try:
        for nzburl in nzburls:
            nzburl = make_unicode(nzburl)
            # some NZBurl have &amp;  some have just & so need to try both forms
            if '&' in nzburl and '&amp;' not in nzburl:
                nzburl2 = nzburl.replace('&', '&amp;')
            elif '&amp;' in nzburl:
                nzburl2 = nzburl.replace('&amp;', '&')
            else:
                nzburl2 = ''
            if nzburl2:
                found = db.select('SELECT * from pastissues WHERE NZBurl=? OR NZBurl=?', (nzburl, nzburl2))
            else:
                found = db.select('SELECT * from pastissues WHERE NZBurl=?', (nzburl,))
            for itm in found:
                nzburl = itm['NZBurl']
                if action == 'Remove':
                    db.action('DELETE from pastissues WHERE NZBurl=?', (nzburl,))
                    logger.debug(f'Item {itm["NZBtitle"]} removed from past issues')
                    maglist.append({'nzburl': nzburl})
                elif action == 'Wanted':
                    maglist.append({'bookid': itm['BookID'], 'nzbprov': itm['NZBprov'], 'nzbtitle': itm['NZBtitle'],
                                    'nzburl': nzburl, 'nzbmode': itm['NZBmode']})
                    # copy into wanted table
                    db.upsert("wanted", {'BookID': itm['BookID'], 'NZBtitle': itm['NZBtitle'], 'NZBdate': now(),
                                         'NZBprov': itm['NZBprov'], 'Status': action, 'NZBsize': itm['NZBsize'],
                                         'AuxInfo': itm['AuxInfo'], 'NZBmode': itm['NZBmode']}, {'NZBurl': nzburl})
                elif action in ['Ignored', 'Skipped']:
                    db.action('UPDATE pastissues set status=? WHERE NZBurl=?', (action, nzburl))
                    logger.debug(f'Item {itm["NZBtitle"]} marked {action} in past issues')
                    maglist.append({'nzburl': nzburl})
    finally:
        db.close()
    if action == 'Remove':
        logger.info(f'Removed {len(maglist)} {plural(len(maglist), "item")} from past issues')
    else:
        logger.info(f'Status set to {action} for {len(maglist)} past {plural(len(maglist), "issue")}')
    if action == 'Wanted':
        threading.Thread(target=download_maglist, name='DL-MAGLIST', args=[maglist, 'wanted']).start()
    return len(maglist)


def new_issue_cover(db, issue: dict, title: str, coverfile: str) -> str:
    """ Use coverfile as the issue's cover, and its magazine's latest cover if it's the latest issue.
        Returns the magazine's title """
    myhash = uuid.uuid4().hex
    hashname = os.path.join(DIRS.CACHEDIR, 'magazine', f'{myhash}.jpg')
    copyfile(coverfile, hashname)
    setperm(hashname)
    newcover = f'cache/magazine/{myhash}.jpg'
    db.upsert("Issues", {"Cover": newcover}, {"IssueFile": issue['IssueFile']})
    latest = db.match("select Title,LatestCover,IssueDate from magazines where title=? COLLATE NOCASE", (title,))
    if latest:
        title = latest['Title']
        if latest['IssueDate'] == issue['IssueDate'] and latest['LatestCover'] != newcover:
            db.action("UPDATE magazines SET LatestCover=? WHERE Title=? COLLATE NOCASE", (newcover, title))
    issue['Cover'] = newcover
    issue['CoverFile'] = coverfile  # for updating calibre cover
    if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
        update_calibre_cover(issue)
    return title


def tag_issue(issuefile: str, title: str, issuedate: str, issueid, language, genres) -> bool:
    """ Write the title, date and genres into an issue's file, and an opf next to it if IMP_MAGOPF is set """
    logger = logging.getLogger(__name__)
    tags = {f'/Genre_{cnt}': genre for cnt, genre in enumerate(get_list(genres), start=1)}
    try:
        res = write_pdf_tags(issuefile, title, issuedate, tags)
    except Exception as e:
        logger.error(f"Failed to tag {issuefile}: {e}")
        res = False
    if res and CONFIG.get_bool('IMP_MAGOPF'):
        logger.debug(f"Writing opf for {issuefile}")
        _, _ = lazylibrarian.metadata_opf.create_mag_opf(issuefile, title, issuedate, issueid, language=language,
                                                         genres=genres, overwrite=True)
    return bool(res)


def cover_page(title: str = '', issueid: str = '') -> int:
    """ The page a magazine's covers are made from, by its title or one of its issues """
    db = database.DBConnection()
    try:
        row = db.match('SELECT CoverPage FROM magazines WHERE Title=? COLLATE NOCASE OR Title=(SELECT Title '
                       'FROM issues WHERE IssueID=?)', (title, issueid))
    finally:
        db.close()
    return check_int(row['CoverPage'], 1) if row else 1


def page_cover(issuefile: str, page: int) -> str:
    """ A cover drawn from a page of an issue's file, made even when the settings don't make covers,
        as it was asked for. Returns the picture's path, empty if there's no such page """
    if pages.is_paged(issuefile) and page > pages.page_count(issuefile):
        return ''
    return extract_image_from_page(issuefile, refresh=True, pagenum=page, cover=True)


def set_issue_cover(issueid, page: int) -> str:
    """ Make an issue's cover from one of its pages. Returns what happened """
    passed, _failed, title = mark_issues(f'reCover{page}', [issueid])
    if not title:
        raise NotFoundError(f"Missing issue {issueid}")
    if not passed:
        raise InvalidRequestError(f"There's no page {page} to make a cover from")
    return f"The cover is page {page} now"


def mark_issues(action: str, issueids, swap_page: int = 2) -> tuple[int, int, str]:
    """ Make a new cover from a page (reCover then the page number), make a page the first one and the
        cover (coverswap, swap_page), tag the file (tag), delete the file and forget the issue (Delete) or
        just forget it (Remove). Stops early after abort_marking. Returns (passed, failed, the magazine
        title) """
    logger = logging.getLogger(__name__)
    passed = failed = 0
    title = ''
    lazylibrarian.MARK_ISSUES = True
    if not action:
        return passed, failed, title
    issueids = list(issueids)
    db = database.DBConnection()
    try:
        for current, itm in enumerate(issueids, start=1):
            if not lazylibrarian.MARK_ISSUES:
                break
            set_issue_progress(current, len(issueids))
            issue = db.match('SELECT IssueFile,Title,IssueDate,Cover from issues WHERE IssueID=?', (itm,))
            if not issue:
                continue
            issue = dict(issue)
            title = issue['Title']
            issuefile = issue['IssueFile']
            if not issuefile or not path_exists(issuefile):
                logger.error(f"No IssueFile found for IssueID {itm}")
                issuefile = None

            if ('reCover' in action or action == 'coverswap') and issuefile:
                coverfile = None
                if 'reCover' in action:
                    coverfile = page_cover(issuefile, check_int(action[len('reCover'):], 1))
                elif CONFIG['MAG_COVERSWAP']:
                    params = [CONFIG['MAG_COVERSWAP'], issuefile]
                    logger.debug(f"Coverswap {params}")
                    try:
                        logger.info(subprocess.check_output(params, stderr=subprocess.STDOUT))
                        coverfile = create_mag_cover(issuefile, refresh=True, pagenum=1)
                    except subprocess.CalledProcessError as e:
                        logger.warning(e.output)
                elif coverswap(issuefile, swap_page):  # cover from that page (counted from 1)
                    coverfile = create_mag_cover(issuefile, refresh=True, pagenum=1)
                if coverfile:
                    title = new_issue_cover(db, issue, title, coverfile)
                    passed += 1
                else:
                    failed += 1
                    logger.warning(f"No coverfile created for IssueID {itm} {issuefile}")

            if action == 'tag' and issuefile:
                logger.debug(f"Tagging {issuefile}")
                entry = db.match('SELECT Language,Genre FROM magazines where Title=?', (title,))
                if tag_issue(issuefile, title, issue['IssueDate'], itm, entry[0], entry[1]):
                    passed += 1
                else:
                    failed += 1

            if action == "Delete" and issuefile:
                if delete_issue_file(issuefile):
                    passed += 1
                    logger.info(f'Issue {issue["IssueDate"]} of {issue["Title"]} deleted from disc')
                    if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                        remove_from_calibre(issue)
                else:
                    failed += 1
            if action in ("Remove", "Delete"):
                db.action('DELETE from issues WHERE IssueID=?', (itm,))
                logger.info(f'Issue {issue["IssueDate"]} of {issue["Title"]} removed from database')
                set_latest(title)
                passed += 1
    finally:
        db.close()
        set_issue_progress(0, 0)
    logger.debug(f"{action.title()}: Pass {passed}, Fail {failed}")
    return passed, failed, title


def set_latest(title) -> str:
    """ Set the magazine's latest issue date and cover from its newest issue, when it was last acquired
        from that issue's file and when it was added from its oldest issue's file. Returns the latest
        issue date, empty if there are no issues """
    db = database.DBConnection()
    try:
        cmd = "select IssueDate,IssueAcquired,IssueFile,Cover from issues where title=? order by IssueDate "
        newest = db.match(cmd + 'DESC', (title,))
        oldest = db.match(cmd + 'ASC', (title,))
        if newest and oldest:
            new_value_dict = {'IssueDate': newest['IssueDate'], 'LatestCover': newest['Cover'],
                              'LastAcquired': file_date(newest['IssueFile']),
                              'MagazineAdded': file_date(oldest['IssueFile'])}
        else:  # there are no issues
            new_value_dict = {'IssueDate': '', 'LastAcquired': '', 'LatestCover': '', 'MagazineAdded': ''}
        db.upsert("magazines", new_value_dict, {'Title': title})
    finally:
        db.close()
    return new_value_dict['IssueDate']


def file_date(filename) -> str:
    """ When a file was last changed, as YYYY-MM-DD, empty if it doesn't exist """
    if not path_exists(filename):
        return ''
    return datetime.date.isoformat(datetime.date.fromtimestamp(os.path.getmtime(syspath(filename))))


def mark_magazines(action: str, titles, userid=None) -> tuple[int, int]:
    """ Pause or activate magazines, delete their issue files and forget them (Delete) or just forget them
        (Remove), tag their issues, scan or search for them, reset their latest issue, or subscribe or
        unsubscribe the user. Stops early after abort_marking. Returns (passed, failed) """
    logger = logging.getLogger(__name__)
    lazylibrarian.MARK_ISSUES = True
    passed = failed = 0
    total_items = current_item = 0
    title = ''
    titles = list(titles)
    logger.debug(f"Marking {len(titles)} {action}")
    db = database.DBConnection()
    try:
        for title in titles:
            try:
                if not lazylibrarian.MARK_ISSUES:
                    break
                if action in ("Paused", "Active"):
                    db.upsert("magazines", {"Status": action}, {"Title": title})
                    logger.info(f'Status of magazine {title} changed to {action}')
                    passed += 1

                if action == "Delete":
                    logger.debug(f'Deleting magazine {title} from disc')
                    issuedir = ''
                    for issue in db.select('SELECT * from issues WHERE Title=?', (title,)):
                        if delete_issue_file(issue['IssueFile']):
                            passed += 1
                            logger.debug(f'Issue {issue["IssueFile"]} deleted from disc')
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                remove_from_calibre(issue)
                            issuedir = os.path.dirname(issue['IssueFile'])
                        else:
                            failed += 1
                            logger.debug(f'Failed to delete {issue["IssueFile"]}')
                    # if no magazine issues left in the folder, delete it (removes any trailing cover images, opf etc)
                    if issuedir and CONFIG.get_bool('MAG_DELFOLDER'):
                        remove_if_empty(os.path.dirname(issuedir), booktype='mag')
                        logger.info(f'Magazine {title} deleted from disc')

                if action == 'tag':
                    issues = db.select('SELECT * from issues WHERE Title=?', (title,))
                    mag = db.match('SELECT Language,Genre FROM magazines where Title=?', (title,))
                    total_items += len(issues)
                    for issue in issues:
                        logger.debug(f"Tagging {issue['IssueFile']}")
                        current_item += 1
                        lazylibrarian.magazinescan_data = (f"{current_item}/{total_items}/"
                                                           f"{int(current_item * 100 / total_items)}")
                        if tag_issue(issue['IssueFile'], title, issue["IssueDate"], issue["IssueID"], mag[0], mag[1]):
                            passed += 1
                        else:
                            failed += 1

                if action == 'Scan':
                    magazine_scan(title)
                    passed += 1

                if action == 'Search':
                    if CONFIG.use_any():
                        logger.debug(f"Searching for magazine: {title}")
                        search_magazines([{"bookid": title}], False, False)
                        passed += 1
                    else:
                        logger.warning("Not searching for magazine, no download methods set, check config")

                if action in ("Remove", "Delete"):
                    db.action('DELETE from magazines WHERE Title=? COLLATE NOCASE', (title,))
                    db.action('DELETE from pastissues WHERE BookID=? COLLATE NOCASE', (title,))
                    db.action('DELETE from wanted where BookID=? COLLATE NOCASE', (title,))
                    logger.info(f'Magazine {title} removed from database')
                    passed += 1
                elif action == "Reset":
                    db.upsert("magazines", {"LastAcquired": '', "IssueDate": '', "LatestCover": '',
                                            "IssueStatus": "Wanted"}, {"Title": title})
                    logger.info(f'Magazine {title} details reset')
                    passed += 1
                elif action == 'Subscribe' and userid:
                    if db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                (userid, 'magazine', title)):
                        logger.debug(f"User {userid} is already subscribed to {title}")
                        failed += 1
                    else:
                        db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                  (userid, 'magazine', title))
                        logger.debug(f"Subscribe {userid} to magazine {title}")
                        passed += 1
                elif action == 'Unsubscribe':
                    if userid:
                        db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                  (userid, 'magazine', title))
                        for iss in db.select('SELECT issueid from issues where title=?', (title,)):
                            db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                      (userid, 'magazine', iss['issueid']))
                        logger.debug(f"Unsubscribe {userid} to magazine {title}")
                    passed += 1
            except Exception as e:
                logger.error(f'Unable to {action} {title}: {type(e).__name__} {str(e)}')
    finally:
        logger.debug(f"{action}:{title}: Pass {passed}, Fail {failed}")
        db.close()
    return passed, failed


def start_search(mags: list) -> bool:
    """ Search for these magazines ({'bookid': title} each), in the background """
    logger = logging.getLogger(__name__)
    if not mags:
        logger.debug("MagazineSearch called with no magazines")
        return False
    if not CONFIG.use_any():
        logger.warning("Not searching for magazine, no download methods available. Check config and blocklist")
        return False
    threading.Thread(target=search_magazines, name='SEARCHMAG', args=[mags, False, False]).start()
    logger.debug(f"Searching for magazine with title: {mags[0]['bookid']}")
    return True


def search_for_magazine(title):
    """ Search for one magazine now """
    try:
        magazine = get_magazine(title)
    except NotFoundError:
        logging.getLogger(__name__).warning(f"Magazine {title} was not found in the library")
        raise
    start_search([{"bookid": magazine['Title']}])


# --- missing and expected issues

MAX_MISSING = 60


def _issue_day(text: str) -> datetime.date | None:
    """ An issue date as a day: YYYY-MM-DD, or YYYY-MM as its first day """
    text = str(text or '')
    try:
        if len(text) >= 10:
            return datetime.date.fromisoformat(text[:10])
        if len(text) == 7:
            return datetime.date.fromisoformat(f"{text}-01")
    except ValueError:
        pass
    return None


def _step(day: datetime.date, frequency: int, times: int = 1) -> datetime.date:
    """ The day so many issues after another: calendar months for a magazine that comes out every
    month or few, days otherwise """
    months = round(frequency / 30.44)
    if frequency >= 28 and abs(months * 30.44 - frequency) <= 4:
        total = day.month - 1 + months * times
        year, month = day.year + total // 12, total % 12 + 1
        return day.replace(year=year, month=month, day=min(day.day, 28))
    return day + datetime.timedelta(days=frequency * times)


def issue_schedule(issue_dates: list[str], frequency: int = 0, today: datetime.date | None = None) -> dict:
    """ What a magazine's issues say about the ones it hasn't got: for issues known by number, the
    numbers missing between the first and last and the next one; for issues known by date, the
    issues missing between them and when the next is due, every frequency days (taken from the gaps
    between the issues when it isn't known). Returns frequency (0 when it can't be told), inferred
    (it was taken from the issues), missing, next and overdue """
    today = today or datetime.date.today()
    found = {'frequency': frequency, 'inferred': False, 'missing': [], 'next': '', 'overdue': False}
    dates = sorted({str(d).strip() for d in issue_dates if str(d or '').strip()})
    if dates and all(d.isdigit() for d in dates):
        numbers = sorted({int(d) for d in dates})
        have = set(numbers)
        found['missing'] = [str(n) for n in range(numbers[0], numbers[-1]) if n not in have][:MAX_MISSING]
        found['next'] = str(numbers[-1] + 1)
        return found
    days = sorted({day for day in (_issue_day(d) for d in dates) if day})
    if not days:
        return found
    if not frequency and len(days) >= 3:
        gaps = sorted((b - a).days for a, b in zip(days, days[1:], strict=False))
        frequency = gaps[len(gaps) // 2]
        found.update({'frequency': frequency, 'inferred': True})
    if frequency <= 0:
        return found
    for before, after in zip(days, days[1:], strict=False):
        expected = _step(before, frequency)
        # an issue more than half a step late is a gap
        while len(found['missing']) < MAX_MISSING and (after - expected).days > frequency / 2:
            found['missing'].append(expected.isoformat())
            expected = _step(expected, frequency)
    upcoming = _step(days[-1], frequency)
    found['next'] = upcoming.isoformat()
    found['overdue'] = (today - upcoming).days > frequency / 2
    return found


# --- what Wikidata says about a magazine

# the magazines columns Wikidata's details fill, by the details' names
WIKIDATA_COLUMNS = {'id': 'WikidataID', 'description': 'Description', 'publisher': 'Publisher', 'issn': 'ISSN',
                    'country': 'Country', 'frequency': 'Frequency', 'website': 'Website', 'logo': 'Logo',
                    'started': 'Started'}


def _language(magazine: dict) -> str:
    return (magazine.get('Language') or CONFIG['PREF_MAGLANG'] or 'en')[:2].lower()


def wikidata_matches(title: str) -> list[dict]:
    """ The periodicals on Wikidata a magazine's title finds, best first """
    magazine = get_magazine(title)
    return wikidata.search(magazine['Title'], _language(magazine))


def set_wikidata(title: str, item_id: str) -> str:
    """ Link a magazine to its Wikidata item and take its details from it: description, publisher,
    ISSN, country, how often it comes out, website, logo, when it started, and its subjects as its
    genres when it has none. An empty item_id unlinks it and clears them. Returns what happened """
    magazine = get_magazine(title)
    title = magazine['Title']
    if not item_id:
        found = {column: 0 if column == 'Frequency' else '' for column in WIKIDATA_COLUMNS.values()}
    else:
        details = wikidata.details(item_id, _language(magazine))
        if not details:
            raise InvalidRequestError(f"Wikidata has no item {item_id}, or couldn't be reached")
        found = {column: details[key] for key, column in WIKIDATA_COLUMNS.items()}
        if details['logo']:
            link, ok, _ = cache_img(ImageType.MAG, f"wikidata_{item_id}", details['logo'], refresh=True)
            found['Logo'] = link if ok else ''
        if not magazine.get('Genre') and details['subjects']:
            found['Genre'] = ', '.join(details['subjects'][:3])
    db = database.DBConnection()
    try:
        db.upsert('magazines', found, {'Title': title})
    finally:
        db.close()
    if not item_id:
        return f"{title} isn't linked to Wikidata now"
    return f"{title} is {details['label']} on Wikidata ({item_id})"


def refresh_magazine(title: str) -> str:
    """ Take a magazine's details from Wikidata again, or link it to the periodical called exactly
    its title when it isn't linked yet. Returns what happened """
    magazine = get_magazine(title)
    if magazine.get('WikidataID'):
        return set_wikidata(magazine['Title'], magazine['WikidataID'])
    matches = wikidata_matches(magazine['Title'])
    exact = [item for item in matches if item['label'].casefold() == magazine['Title'].casefold()]
    if len(exact) != 1:
        hint = f"{len(exact)} are called that" if exact else f"{len(matches)} close ones"
        return f"{magazine['Title']} wasn't linked to Wikidata, {hint}, choose one in Edit"
    return set_wikidata(magazine['Title'], exact[0]['id'])


def clean_title(title: str) -> tuple[str, str | None]:
    """ A magazine title as it's stored: ascii quotes, & and + as and, and any reject words after a ~
        split off. Returns (title, reject words or None) """
    reject = None
    if '~' in title:  # separate out the "reject words" list
        title, reject = (part.strip() for part in title.split('~', 1))
    # replace any non-ascii quotes/apostrophes with ascii ones eg "Collector's"
    title = replace_all(title, lazylibrarian.DICTS.get('apostrophe_dict', {}))
    return ' '.join('and' if word in ('&', '+') else word for word in title.split()), reject


def add_magazine(title: str, search: bool | None = None) -> tuple[str, bool]:
    """ Add a magazine, title may end with ~ and words that rule out a search result. Searches for it straight
        away if search, or if IMP_AUTOSEARCH is set when search is None. Returns (the title as stored,
        whether it's new, the one there is if not) """
    logger = logging.getLogger(__name__)
    title, reject = clean_title(title)
    db = database.DBConnection()
    try:
        exists = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (title,))
        if exists:
            logger.debug(f"Magazine {title} already exists ({exists['Title']})")
            return exists['Title'], False
        db.upsert("magazines", {"Reject": reject, "Genre": "", "DateType": "", "Status": "Active",
                                "MagazineAdded": today(), "LastAcquired": None, "LatestCover": None,
                                "IssueDate": None, "IssueStatus": "Wanted", "Regex": None, "CoverPage": 1,
                                "Language": CONFIG['PREF_MAGLANG']}, {"Title": title})
    finally:
        db.close()
    if CONFIG.get_bool('IMP_AUTOSEARCH') if search is None else search:
        start_search([{"bookid": title}])
    return title, True
