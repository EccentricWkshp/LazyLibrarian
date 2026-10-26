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

""" The magazine list, issues, past issues, adding magazines and marking them """

import ast
import contextlib
import datetime
import logging
import os
import subprocess
import threading
import traceback
import uuid
from shutil import copyfile
from urllib.parse import quote

import cherrypy

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.calibre import calibredb, get_calibre_id
from lazylibrarian.calibre_integration import send_mag_issue_to_calibre
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, path_exists, path_isfile, setperm, splitext, syspath
from lazylibrarian.formatter import (
    check_int,
    check_year,
    date_format,
    fold,
    get_list,
    make_unicode,
    natural_sort,
    now,
    plural,
    replace_all,
    today,
)
from lazylibrarian.images import (
    coverswap,
    create_mag_cover,
    createthumb,
    read_pdf_tags,
    write_pdf_tags,
)
from lazylibrarian.magazinescan import get_dateparts, magazine_scan, remove_if_empty, rename_issue
from lazylibrarian.processcontrol import get_info_on_caller
from lazylibrarian.searchmag import download_maglist, search_magazines
from lazylibrarian.web.common import BasePages, mark_summary, serve_template

lastmagazine = ''


class MagazinePages(BasePages):
    """ The magazine list, issues, past issues, adding magazines and marking them """

    issues_data = ''

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_mags(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        filtered = []
        rowlist = []
        userid = None
        userprefs = 0
        cookie = cherrypy.request.cookie
        userid = owner_id()
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            db = database.DBConnection()
            try:
                cmd = ("select magazines.*,(select count(*) as counter from issues where "
                       "magazines.title = issues.title) as Iss_Cnt from magazines")

                maglist = ''
                if userid and userprefs & lazylibrarian.pref_mymags:
                    res = db.select("SELECT WantID from subscribers WHERE Type='magazine' and UserID=?", (userid,))
                    serversidelogger.debug(f"User subscribes to {len(res)} magazines")
                    for mag in res:
                        if maglist:
                            maglist += ', '
                        maglist += f'"{mag["WantID"]}"'
                    cmd += " WHERE Title in (?)"
                cmd += " order by Title"
                if maglist:
                    serversidelogger.debug(cmd + str(maglist))
                    rowlist = db.select(cmd, (maglist, ))
                else:
                    serversidelogger.debug(cmd)
                    rowlist = db.select(cmd)
            finally:
                db.close()

            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [mag['Title'], mag['LatestCover'], quote(mag['Title']), mag['Iss_Cnt'], mag['LastAcquired'],
                             mag['IssueDate'], mag['Status'], mag['IssueStatus'], mag['Genre']]

                    newrowlist.append(entry)  # add each rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    q = fold(sSearch)
                    filtered = [x for x in newrowlist if q in fold(x)]
                    #filtered = [x for x in newrowlist if sSearch.lower() in str(x).lower()]
                else:
                    filtered = newrowlist

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                if sortcolumn in [4, 5]:  # dates
                    natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                elif sortcolumn == 2:  # title
                    filtered.sort(key=lambda y: y[sortcolumn].lower() if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

                for row in rows:
                    row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                    if row[5] and row[5].isdigit():
                        if len(row[5]) == 8:
                            if check_year(row[5][:4]):
                                row[5] = f'Issue {int(row[5][4:])} {row[5][:4]}'
                            else:
                                row[5] = f'Vol {int(row[5][:4])} #{int(row[5][4:])}'
                        elif len(row[5]) == 12:
                            row[5] = f'Vol {int(row[5][4:8])} #{int(row[5][8:])} {row[5][:4]}'
                    else:
                        row[5] = date_format(row[5], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

                    if not row[1] or not row[1].startswith('cache/'):
                        row[1] = 'images/nocover.jpg'
                        row.append('images/nocover.jpg')
                    else:
                        fname, extn = splitext(row[1])
                        imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                        fullsize = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}{extn}')
                        if path_isfile(imgfile):
                            row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                        else:
                            imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                            imgthumb = createthumb(imgfile, 200, False)
                            if imgthumb:
                                row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                        row.append(f"cache/{fullsize[len(DIRS.CACHEDIR):].lstrip(os.sep)}")

            serversidelogger.debug(f"get_mags returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_mags filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_mags: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.MAG_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def magazines(self, mag_filter=''):
        db = database.DBConnection()
        user = owner_id()
        if user:
            res = db.match('SELECT SendTo from users where UserID=?', (user,))
            if res and res['SendTo']:
                email = res['SendTo']
            else:
                email = ''
        else:
            user = 0
            email = ''
        db.close()
        # use server-side processing
        covers = 1
        if not CONFIG['TOGGLES']:
            covers = 0
        return serve_template(templatename="magazines.html", title=i18n.gettext("Magazines"), magazines=[],
                              covercount=covers, user=user, email=email, mag_filter=mag_filter)

    @cherrypy.expose
    @require_auth()
    def edit_mag(self, mag=None):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_MAG')
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            magdata = db.match("SELECT Title from magazines WHERE Title=? COLLATE NOCASE", (mag,))
        finally:
            db.close()

        if magdata:
            return serve_template(templatename="editmag.html", title=i18n.gettext('Rename Magazine %(title)s') % {'title': magdata['Title']},
                                  config=magdata)
        logger.error(f'Missing magazine {mag}')
        raise cherrypy.HTTPRedirect("magazines")

    # noinspection PyBroadException
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def magazine_update_ajax(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        summary = ''
        passed = 0
        failed = 0
        new_title = kwargs.get('new_title')
        old_title = kwargs.get('old_title')
        if not old_title and not new_title:
            summary = i18n.gettext('Insufficient information, need Old and New Title')
        if not summary and old_title == new_title:
            summary = i18n.gettext('Title for %(title)s unchanged') % {'title': old_title}
        if not summary:
            valid = self.validate_param("magazine title", new_title, ['<', '>', '='], None)
            if not valid:
                summary = i18n.gettext('Invalid new title, unable to rename')
        if not summary:
            db = database.DBConnection()
            res = db.match("SELECT Title from magazines WHERE Title=? COLLATE NOCASE", (new_title,))
            if res:
                summary = i18n.gettext('Title %(title)s already exists, unable to rename') % {'title': new_title}
            db.close()
        if not summary:
            logger.debug(f"Changing title [{old_title}] to [{new_title}]")
            db = database.DBConnection()
            try:
                db.action('PRAGMA foreign_keys = OFF')
                db.action("UPDATE magazines SET Title=? WHERE Title=? COLLATE NOCASE", (new_title, old_title))
                db.action("UPDATE issues SET Title=? WHERE Title=? COLLATE NOCASE", (new_title, old_title))
                db.action('PRAGMA foreign_keys = ON')
                db.commit()

                summary = i18n.gettext('Renamed %(old)s to %(new)s') % {'old': old_title, 'new': new_title}

                # rename files/folders to match, and issuefile to match new location
                issues = db.select("SELECT IssueDate,IssueFile,IssueID from issues WHERE Title=?", (new_title,))
                total_items = len(issues)
                current_item = 0
                for issue in issues:
                    current_item += 1
                    current_percent = int(current_item * 100 / total_items)
                    self.issues_data = f"{current_item}/{total_items}/{current_percent}"
                    calibre_id = None
                    if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                        dbentry = db.match('SELECT * from issues WHERE IssueID=?', (issue['IssueID'],))
                        data = dict(dbentry)
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
                        res, err, rc = calibredb('remove', [calibre_id])
                        logger.debug(f"Remove result: {res} [{err}] {rc}")
                        dbentry = db.match('SELECT * from issues WHERE IssueID=?', (issue['IssueID'],))
                        data = dict(dbentry)
                        magentry = db.match('SELECT Genre from magazines WHERE Title=?', (data['Title'],))
                        data['mag_genres'] = magentry['Genre']
                        res, filename, pp_path = send_mag_issue_to_calibre(data)
                        logger.debug(f"Add result: {res}")
                        if res and filename:
                            # calibre may have renamed it
                            db.action("UPDATE issues SET IssueFile=? WHERE IssueID=?", (filename, issue['IssueID']))
            except Exception:
                logger.error(f'Unhandled exception in magazine_update: {traceback.format_exc()}')
            finally:
                db.close()
        self.issues_data = ''
        # Return JSON response instead of redirect
        total = passed + failed
        if not summary:
            summary = i18n.gettext("Rename completed.")
        return {
            'success': True,
            'passed': passed,
            'failed': failed,
            'total': total,
            'title': new_title,
            'summary': summary
        }

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        filtered = []
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            perm = lazylibrarian.perm_admin
            title = kwargs['title'].replace('&amp;', '&')
            db = database.DBConnection()
            rowlist = db.select('SELECT * from issues WHERE Title=? order by IssueDate DESC', (title,))
            db.close()
            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [mag['Title'], mag['Cover'], mag['IssueDate'], mag['IssueAcquired'],
                             mag['IssueID']]
                    newrowlist.append(entry)  # add each rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    q = fold(sSearch)
                    filtered = [x for x in newrowlist if q in fold(x)]
                    #filtered = [x for x in newrowlist if sSearch.lower() in str(x).lower()]
                else:
                    filtered = newrowlist

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                if sortcolumn in [2, 3]:  # dates
                    natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

            for row in rows:
                if not row[1] or not row[1].startswith('cache/'):
                    row[1] = 'images/nocover.jpg'
                else:
                    fname, extn = splitext(row[1])
                    imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                    fullsize = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}{extn}')
                    if path_isfile(imgfile):
                        row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                    else:
                        imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                        imgthumb = createthumb(imgfile, 200, False)
                        if imgthumb:
                            row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                    row.append(f"cache/{fullsize[len(DIRS.CACHEDIR):].lstrip(os.sep)}")
                row[3] = date_format(row[3], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                if row[2] and row[2].isdigit():
                    if len(row[2]) == 8:
                        # Year/Issue or Volume/Issue with no year
                        if check_year(row[2][:4]):
                            row[2] = f'{row[2][:4]} Issue {int(row[2][4:])}'
                        else:
                            row[2] = f'Vol {int(row[2][:4])} #{int(row[2][4:])}'
                    elif len(row[2]) == 12:
                        row[2] = f'{row[2][:4]} Vol {int(row[2][4:8])} #{int(row[2][8:])}'
                else:
                    row[2] = date_format(row[2], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                if perm & lazylibrarian.perm_edit:
                    row[2] = row[2] + '<br><a href="edit_issue?issueid=' + row[4] + '"><small><i>Edit</i></a>'

            serversidelogger.debug(f"get_issues returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_issues filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_issues: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.MAG_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def edit_issue(self, issueid=None):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        self.label_thread('EDIT_ISSUE')
        db = database.DBConnection()
        try:
            issuedata = db.match("SELECT Title,IssueDate,IssueID,IssueFile from issues WHERE IssueID=?", (issueid,))
        finally:
            db.close()

        if issuedata:
            tagdict = read_pdf_tags(issuedata['IssueFile'])
            return serve_template(templatename="editissue.html", title=i18n.gettext("Edit Issue"), config=issuedata, tags=tagdict)
        logger.error(f"Missing issue {issueid}")
        return None

    @cherrypy.expose
    @require_auth()
    def issue_update(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        issueid = kwargs.get('issueid')
        if not issueid:
            logger.debug('Invalid or missing IssueID')
            raise cherrypy.HTTPRedirect("magazines")

        magtitle = kwargs.get('magtitle')
        issuenum = kwargs.get('issuenum')
        db = database.DBConnection()
        magazine = db.match("SELECT DateType,IssueDate from magazines WHERE Title=? COLLATE NOCASE", (magtitle,))
        datetype = magazine['DateType']
        mostrecentissue = magazine['IssueDate']
        issue = db.match("SELECT Title,IssueDate,IssueFile,Cover,IssueID from issues WHERE IssueID=?", (issueid,))
        redirect = issue['Title']
        dateparts = get_dateparts(issuenum, datetype=datetype)
        if not dateparts['style']:
            datetype_ok = False
        else:
            datetype_ok = True
            if datetype:
                # check all wanted parts are in the regex result
                # Day Month Year Vol Iss (MM needs two months)

                if 'M' in datetype and dateparts['style'] not in [1, 2, 3, 4, 5, 6, 7, 12]:
                    datetype_ok = False
                if 'D' in datetype and dateparts['style'] not in [3, 5, 6]:
                    datetype_ok = False
                if 'MM' in datetype and dateparts['style'] not in [1]:  # bi monthly
                    datetype_ok = False
                if 'V' in datetype and dateparts['style'] not in [2, 8, 9, 10, 11, 12, 13, 14, 17, 18]:
                    datetype_ok = False
                if 'I' in datetype and dateparts['style'] not in [2, 10, 11, 12, 13, 14, 16, 17, 18]:
                    datetype_ok = False
                if 'Y' in datetype and dateparts['style'] not in [1, 2, 3, 4, 5, 6, 7, 8, 10,
                                                                  12, 13, 15, 16, 18]:
                    datetype_ok = False

        if not datetype_ok:
            response = f'Date {issuenum} not in a recognised date format [{datetype}]'
            logger.debug(response)
            db.close()
            raise cherrypy.HTTPRedirect(f"issue_page?title={quote(redirect)}&response={response}")

        if not magtitle and issuenum:
            response = (f"Issue {issue['IssueDate']} of {issue['Title']} is unchanged. "
                        f"Insufficient information, need Title and valid IssueNum/Date")
            logger.debug(response)
            db.close()
            raise cherrypy.HTTPRedirect(f"issue_page?title={quote(redirect)}&response={response}")

        old_path = os.path.dirname(issue['IssueFile'])
        edited = ''
        if issue["Title"] != magtitle:
            edited = 'Title '
        if issue["IssueDate"] != issuenum:
            edited += 'Date/Num '
        new_tags = {}
        for itm in kwargs:
            if itm.startswith('tags_/'):
                new_tags[itm[5:]] = kwargs[itm]
        try:
            old_tags = ast.literal_eval(kwargs['tagdata'])
        except SyntaxError:
            old_tags = None
        if not isinstance(old_tags, dict):
            logger.warning("Invalid old_tags dictionary")
            old_tags = {}
        if old_tags == new_tags:
            logger.debug("No tag changes")
        else:
            edited += 'Tags '
        if edited:
            if issue["Title"] != magtitle:
                if not magazine:
                    if not magtitle:
                        logger.warning("Missing magazine title")
                        raise cherrypy.HTTPError(404, "Magazine title missing")

                    self.validate_param("magazine title", magtitle, ['<', '>', '='], 404)
                    logger.debug(f"Magazine title [{magtitle}] not found, adding it")
                    control_value_dict = {"Title": magtitle}
                    new_value_dict = {"LastAcquired": today(),
                                      "IssueStatus": CONFIG['FOUND_STATUS'],
                                      "IssueDate": "", "LatestCover": ""}
                    db.upsert("magazines", new_value_dict, control_value_dict)
                db.action("UPDATE issues SET Title=? WHERE IssueID=?", (magtitle, issue['IssueID']))
            db.action("UPDATE issues SET IssueDate=? WHERE IssueID=?", (issuenum, issue['IssueID']))

            fname, err = rename_issue(issue['IssueID'], tags=new_tags)
            response = (f'Issue {issue["IssueDate"]} of {issue["Title"]}, changed to '
                        f'{os.path.basename(fname)} {edited}')
            if err:
                raise cherrypy.HTTPError(404, f"Magazine IssueFile {issue['IssueFile']} move failed: {err}")

            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                calibre_id = get_calibre_id(issue, try_filename=False)
                if calibre_id:
                    logger.debug(f"Found calibre ID {calibre_id} for {issue['Title']} {issue['IssueDate']}")
                    res, err, rc = calibredb('remove', [calibre_id])
                    logger.debug(f"Remove result: {res} [{err}] {rc}")
                    dbentry = db.match('SELECT * from issues WHERE IssueID=?', (issue['IssueID'],))
                    data = dict(dbentry)
                    magentry = db.match('SELECT Genre from magazines WHERE Title=?', (data['Title'],))
                    data['mag_genres'] = magentry['Genre']
                    res, filename, pp_path = send_mag_issue_to_calibre(data)
                    logger.debug(f"Add result: {res}")
                    if res and filename:
                        db.action("UPDATE issues SET IssueFile=? WHERE IssueID=?", (filename, issue['IssueID']))

            # if no magazine issues left in the folder, delete it
            # (removes any trailing cover images, opf etc)
            remove_if_empty(old_path)

            if mostrecentissue:
                if mostrecentissue.isdigit() and str(issuenum).isdigit():
                    older = (int(mostrecentissue) > int(issuenum))  # issuenumber
                else:
                    older = (mostrecentissue > issuenum)  # YYYY-MM-DD
            else:
                older = False

            control_value_dict = {"Title": magtitle}
            if older:
                new_value_dict = {"LastAcquired": today(),
                                  "IssueStatus": CONFIG['FOUND_STATUS']}
            else:
                new_value_dict = {"LastAcquired": today(),
                                  "IssueStatus": CONFIG['FOUND_STATUS'],
                                  "IssueDate": issuenum,
                                  "LatestCover": issue['Cover']}
            db.upsert("magazines", new_value_dict, control_value_dict)
            if self.mag_set_latest(issue['Title']):
                # update latest issue of old mag title, if any issues left, redirect to there
                redirect = issue['Title']
            else:
                # no issues under old title, redirect to new title
                redirect = magtitle
        else:
            response = f'Issue {issue["IssueDate"]} of {issue["Title"]} is unchanged'
            logger.debug(response)
        db.close()
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(redirect)}&response={response}")

    @cherrypy.expose
    @require_auth()
    def issue_page(self, title, response=''):
        global lastmagazine
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        res = db.match('SELECT Title from magazines where Title=? COLLATE NOCASE', (title,))
        if res:
            title = res['Title']
        db.close()
        if not res:
            logger.warning(f"Unknown magazine title: {title}")
            raise cherrypy.HTTPError(404, f"Magazine title {title} not found")

        if title and '&' in title and '&amp;' not in title:  # could use htmlparser but seems overkill for just '&'
            safetitle = title.replace('&', '&amp;')
        else:
            safetitle = title

        # if we've changed magazine, reset to first page of new magazines issues
        if title == lastmagazine:
            firstpage = 'false'
        else:
            lastmagazine = title
            firstpage = 'true'

        # use server-side processing
        if not CONFIG['TOGGLES']:
            covercount = 0
        else:
            covercount = 1

        user = 0
        email = ''
        user = owner_id()
        if user:
            db = database.DBConnection()
            try:
                res = db.match('SELECT SendTo from users where UserID=?', (user,))
            finally:
                db.close()
            if res and res['SendTo']:
                email = res['SendTo']
        self.issues_data = ''
        return serve_template(templatename="issues.html", title=safetitle, issues=[], covercount=covercount,
                              user=user, email=email, firstpage=firstpage, response=response)

    @cherrypy.expose
    @require_auth()
    def abort_progress(self):
        logger = logging.getLogger(__name__)
        lazylibrarian.MARK_ISSUES = False
        logger.warning('Mark Issues/Magazines Aborted by user')
        return False

    @cherrypy.expose
    @require_auth()
    def test_progress(self):
        return lazylibrarian.test_data

    @cherrypy.expose
    @require_auth()
    def issues_progress(self):
        current = '0'
        total = '0'
        percent = '0'
        try:
            current, total, percent = self.issues_data.split('/')
        except ValueError:
            with contextlib.suppress(ValueError):
                current, total, percent = lazylibrarian.magazinescan_data.split('/')
        bar = ('<div class="progress center-block" style="width: 70%;"><div class="progress-bar-info'
               f' progress-bar progress-bar-striped" role="progressbar aria-valuenow="{percent}"'
               f' aria-valuemin="0" aria-valuemax="100" style="width:{percent}%;">'
               f'<span class="progressbar-front-text">{current}/{total}</span></div></div>')
        return bar

    @cherrypy.expose
    @require_auth()
    def magazinescan_progress(self):
        try:
            current, total, percent = lazylibrarian.magazinescan_data.split('/')
        except ValueError:
            return lazylibrarian.magazinescan_data

        bar = ('<div class="text-center">Scanning Library ...<br></div>'
               '<div class="progress center-block" style="width: 90%;"><div class="progress-bar-info'
               f' progress-bar progress-bar-striped" role="progressbar aria-valuenow="{percent}"'
               f' aria-valuemin="0" aria-valuemax="100" style="width:{percent}%;">'
               f'<span class="progressbar-front-text">{current}/{total}</span></div></div>')
        return bar

    @cherrypy.expose
    @require_auth()
    def past_issues(self, mag=None, **kwargs):
        if not mag or mag == 'None':
            title = i18n.gettext('Past Issues')
        else:
            title = mag
        which_status = kwargs.get('whichStatus', '')
        if not which_status or which_status == 'None':
            which_status = "Skipped"
        return serve_template(
            templatename="manageissues.html", title=title, issues=[], whichStatus=which_status, mag=mag)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_past_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc",
                        sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        # kwargs is used by datatables to pass params
        rows = []
        filtered = []
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            # need to filter on whichStatus and optional mag title
            cmd = "SELECT NZBurl, NZBtitle, NZBdate, Auxinfo, NZBprov from pastissues WHERE Status=?"
            args = [kwargs['whichStatus']]
            if 'mag' in kwargs and kwargs['mag'] != 'None':
                cmd += " AND BookID=?"
                args.append(kwargs['mag'].replace('&amp;', '&'))

            serversidelogger.debug(f"get_past_issues {cmd}: {str(args)}")
            rowlist = db.select(cmd, tuple(args))
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)  # turn sqlite objects into lists
                    if entry[1]:
                        entry[1] = entry[1].replace('.', ' ')
                    provider = entry[4] or ''
                    if len(provider) > 20:
                        while len(provider) > 20 and '/' in provider:
                            provider = provider.split('/', 1)[1]
                        provider = provider.replace('/', ' ')
                        entry[4] = provider
                    rows.append(entry)

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    q = fold(sSearch)
                    filtered = [x for x in rows if q in fold(x)]
                    #filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                              reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

            serversidelogger.debug(f"get_past_issues returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_past_issues filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_past_issues: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        db.close()
        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def mark_past_issues(self, action=None, **args):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        maglist = []
        args.pop('book_table_length', None)

        for nzburl in args:
            nzburl = make_unicode(nzburl)
            # some NZBurl have &amp;  some have just & so need to try both forms
            if '&' in nzburl and '&amp;' not in nzburl:
                nzburl2 = nzburl.replace('&', '&amp;')
            elif '&amp;' in nzburl:
                nzburl2 = nzburl.replace('&amp;', '&')
            else:
                nzburl2 = ''

            if not nzburl2:
                title = db.select('SELECT * from pastissues WHERE NZBurl=?', (nzburl,))
            else:
                title = db.select('SELECT * from pastissues WHERE NZBurl=? OR NZBurl=?', (nzburl, nzburl2))

            for itm in title:
                nzburl = itm['NZBurl']
                if action == 'Remove':
                    db.action('DELETE from pastissues WHERE NZBurl=?', (nzburl,))
                    logger.debug(f'Item {itm["NZBtitle"]} removed from past issues')
                    maglist.append({'nzburl': nzburl})
                elif action == 'Wanted':
                    bookid = itm['BookID']
                    nzbprov = itm['NZBprov']
                    nzbtitle = itm['NZBtitle']
                    nzbmode = itm['NZBmode']
                    nzbsize = itm['NZBsize']
                    auxinfo = itm['AuxInfo']
                    maglist.append({
                        'bookid': bookid,
                        'nzbprov': nzbprov,
                        'nzbtitle': nzbtitle,
                        'nzburl': nzburl,
                        'nzbmode': nzbmode
                    })
                    # copy into wanted table
                    control_value_dict = {'NZBurl': nzburl}
                    new_value_dict = {
                        'BookID': bookid,
                        'NZBtitle': nzbtitle,
                        'NZBdate': now(),
                        'NZBprov': nzbprov,
                        'Status': action,
                        'NZBsize': nzbsize,
                        'AuxInfo': auxinfo,
                        'NZBmode': nzbmode
                    }
                    db.upsert("wanted", new_value_dict, control_value_dict)

                elif action in ['Ignored', 'Skipped']:
                    db.action('UPDATE pastissues set status=? WHERE NZBurl=?', (action, nzburl))
                    logger.debug(f'Item {itm["NZBtitle"]} marked {action} in past issues')
                    maglist.append({'nzburl': nzburl})
        db.close()

        if action == 'Remove':
            logger.info(f'Removed {len(maglist)} {plural(len(maglist), "item")} from past issues')
        else:
            logger.info(f'Status set to {action} for {len(maglist)} past {plural(len(maglist), "issue")}')
        # start searchthreads
        if action == 'Wanted':
            threading.Thread(target=download_maglist, name='DL-MAGLIST', args=[maglist, 'wanted']).start()
        raise cherrypy.HTTPRedirect("past_issues")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_issues_ajax(self, action=None, **args):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        passed = 0
        failed = 0
        title = ''
        args.pop('book_table_length', None)
        lazylibrarian.MARK_ISSUES = True
        if action:
            total_items = len(args)
            for current_item, itm in enumerate(args, start=1):
                if not lazylibrarian.MARK_ISSUES:
                    break
                current_percent = int(current_item * 100 / total_items)
                self.issues_data = f"{current_item}/{total_items}/{current_percent}"
                issue = db.match('SELECT IssueFile,Title,IssueDate,Cover from issues WHERE IssueID=?', (itm,))
                if issue:
                    issue = dict(issue)
                    title = issue['Title']
                    issuefile = issue['IssueFile']
                    if not issuefile or not path_exists(issuefile):
                        logger.error(f"No IssueFile found for IssueID {itm}")
                        issuefile = None

                    if 'reCover' in action and issuefile:
                        coverfile = create_mag_cover(issuefile, refresh=True,
                                                     pagenum=check_int(action[-1], 1))
                        if coverfile:
                            myhash = uuid.uuid4().hex
                            hashname = os.path.join(DIRS.CACHEDIR, 'magazine', f'{myhash}.jpg')
                            copyfile(coverfile, hashname)
                            setperm(hashname)
                            control_value_dict = {"IssueFile": issue['IssueFile']}
                            newcover = f'cache/magazine/{myhash}.jpg'
                            new_value_dict = {"Cover": newcover}
                            db.upsert("Issues", new_value_dict, control_value_dict)
                            latest = db.match("select Title,LatestCover,IssueDate from magazines "
                                              "where title=? COLLATE NOCASE", (title,))
                            if latest:
                                title = latest['Title']
                                if latest['IssueDate'] == issue['IssueDate'] and latest['LatestCover'] != newcover:
                                    db.action("UPDATE magazines SET LatestCover=? "
                                              "WHERE Title=? COLLATE NOCASE", (newcover, title))
                            issue['Cover'] = newcover
                            issue['CoverFile'] = coverfile  # for updating calibre cover
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.update_calibre_issue_cover(issue)
                            passed += 1
                        else:
                            failed += 1
                            logger.warning(f"No coverfile created for IssueID {itm} {issuefile}")

                    if action == 'tag' and issuefile:
                        logger.debug(f"Tagging {issuefile}")
                        entry = db.match('SELECT Language,Genre FROM magazines where Title=?', (title,))
                        genres = entry[1]
                        tags = {}
                        cnt = 1
                        for i in get_list(genres):
                            tags[f'/Genre_{cnt}'] = i
                            cnt += 1
                        try:
                            res = write_pdf_tags(issuefile, title, issue['IssueDate'], tags)
                        except Exception as e:
                            logger.error(f"Failed to tag {issuefile}: {e}")
                            res = False
                        if not res:
                            failed += 1
                        else:
                            passed += 1
                            if CONFIG.get_bool('IMP_MAGOPF'):
                                logger.debug(f"Writing opf for {issuefile}")
                                _, _ = lazylibrarian.metadata_opf.create_mag_opf(issuefile, title,
                                                                                 issue['IssueDate'], itm,
                                                                                 language=entry[0],
                                                                                 genres=genres,
                                                                                 overwrite=True)
                    if action == 'coverswap' and issuefile:
                        coverfile = None
                        if CONFIG['MAG_COVERSWAP']:
                            params = [CONFIG['MAG_COVERSWAP'], issuefile]
                            logger.debug(f"Coverswap {params}")
                            try:
                                res = subprocess.check_output(params, stderr=subprocess.STDOUT)
                                logger.info(res)
                                coverfile = create_mag_cover(issuefile, refresh=True, pagenum=1)
                            except subprocess.CalledProcessError as e:
                                logger.warning(e.output)
                        else:
                            res = coverswap(issuefile, 2)  # cover from page 2 (counted from 1)
                            if res:
                                coverfile = create_mag_cover(issuefile, refresh=True, pagenum=1)
                        if coverfile:
                            myhash = uuid.uuid4().hex
                            hashname = os.path.join(DIRS.CACHEDIR, 'magazine', f'{myhash}.jpg')
                            copyfile(coverfile, hashname)
                            setperm(hashname)
                            control_value_dict = {"IssueFile": issuefile}
                            newcover = f'cache/magazine/{myhash}.jpg'
                            new_value_dict = {"Cover": newcover}
                            db.upsert("Issues", new_value_dict, control_value_dict)
                            latest = db.match("select Title,LatestCover,IssueDate from magazines "
                                              "where title=? COLLATE NOCASE", (title,))
                            if latest:
                                title = latest['Title']
                                if latest['IssueDate'] == issue['IssueDate'] and latest['LatestCover'] != newcover:
                                    db.action("UPDATE magazines SET LatestCover=? "
                                              "WHERE Title=? COLLATE NOCASE", (newcover, title))
                            issue['Cover'] = newcover
                            issue['CoverFile'] = coverfile  # for updating calibre cover
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.update_calibre_issue_cover(issue)
                            passed += 1
                        else:
                            failed += 1
                            logger.warning(f"No coverfile created for IssueID {itm} {issuefile}")

                    if action == "Delete" and issuefile:
                        result = self.delete_issue(issuefile)
                        if result:
                            passed += 1
                            logger.info(f'Issue {issue["IssueDate"]} of {issue["Title"]} deleted from disc')
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.delete_from_calibre(issue)
                        else:
                            failed += 1
                    if action == "Remove" or action == "Delete":
                        db.action('DELETE from issues WHERE IssueID=?', (itm,))
                        logger.info(f'Issue {issue["IssueDate"]} of {issue["Title"]} removed from database')
                        _ = self.mag_set_latest(title)
                        passed += 1
        db.close()

        logger.debug(f"{action.title()}: Pass {passed}, Fail {failed}")

        # Return JSON response instead of redirect
        total = passed + failed
        summary = mark_summary(i18n.gettext("Operation '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)

        self.issues_data = ''
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'title': title,
            'summary': summary
        }

    @staticmethod
    def mag_set_latest(title):
        # Set magazine_issuedate to issuedate of most recent issue we have
        # Set latestcover to most recent issue cover
        # Set magazine_lastacquired to acquired date of most recent issue we have
        # Set magazine_added to acquired date of the earliest issue we have
        # Return the latest issue date, or empty if no issues
        db = database.DBConnection()
        cmd = ("select IssueDate,IssueAcquired,IssueFile,Cover from issues where title=? "
               "order by IssueDate ")
        newest = db.match(cmd + 'DESC', (title,))
        oldest = db.match(cmd + 'ASC', (title,))
        control_value_dict = {'Title': title}
        if newest and oldest:
            old_acquired = ''
            new_acquired = ''
            cover = newest['Cover']
            issuefile = newest['IssueFile']
            if path_exists(issuefile):
                mtime = os.path.getmtime(syspath(issuefile))
                new_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))
            issuefile = oldest['IssueFile']
            if path_exists(issuefile):
                mtime = os.path.getmtime(syspath(issuefile))
                old_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))

            new_value_dict = {
                'IssueDate': newest['IssueDate'],
                'LatestCover': cover,
                'LastAcquired': new_acquired,
                'MagazineAdded': old_acquired
            }
        else:  # there are no issues
            new_value_dict = {
                'IssueDate': '',
                'LastAcquired': '',
                'LatestCover': '',
                'MagazineAdded': ''
            }
        db.upsert("magazines", new_value_dict, control_value_dict)
        db.close()
        return new_value_dict['IssueDate']

    @staticmethod
    def update_calibre_issue_cover(issue):
        logger = logging.getLogger(__name__)
        calibre_id = get_calibre_id(issue)
        if calibre_id:
            res, err, rc = calibredb('set_metadata', ['--field', f'cover:{issue["CoverFile"]}'], [calibre_id])
            logger.debug(f"Update result: {res} [{err}] {rc}")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_magazines_ajax(self, action=None, **args):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        total_items = 0
        current_item = 0
        args.pop('book_table_length', None)
        lazylibrarian.MARK_ISSUES = True
        passed = 0
        failed = 0
        title = ''
        logger.debug(f"Marking {len(args)} {action}")
        for itm in args:
            try:
                if not lazylibrarian.MARK_ISSUES:
                    break
                title = itm
                if action == "Paused" or action == "Active":
                    control_value_dict = {"Title": title}
                    new_value_dict = {"Status": action}
                    db.upsert("magazines", new_value_dict, control_value_dict)
                    logger.info(f'Status of magazine {title} changed to {action}')
                    passed += 1

                if action == "Delete":
                    issues = db.select('SELECT * from issues WHERE Title=?', (title,))
                    logger.debug(f'Deleting magazine {title} from disc')
                    issuedir = ''
                    for issue in issues:  # delete all issues of this magazine
                        result = self.delete_issue(issue['IssueFile'])
                        if result:
                            passed += 1
                            logger.debug(f'Issue {issue["IssueFile"]} deleted from disc')
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.delete_from_calibre(issue)
                            issuedir = os.path.dirname(issue['IssueFile'])
                        else:
                            failed += 1
                            logger.debug(f'Failed to delete {issue["IssueFile"]}')

                    # if the directory is now empty, delete that too
                    if issuedir and CONFIG.get_bool('MAG_DELFOLDER'):
                        magdir = os.path.dirname(issuedir)
                        # if no magazine issues left in the folder, delete it
                        # (removes any trailing cover images, opf etc)
                        remove_if_empty(magdir, booktype='mag')
                        logger.info(f'Magazine {title} deleted from disc')

                if action == 'tag':
                    issues = db.select('SELECT * from issues WHERE Title=?', (title,))
                    mag = db.match('SELECT Language,Genre FROM magazines where Title=?', (title,))
                    total_items += len(issues)
                    for issue in issues:
                        logger.debug(f"Tagging {issue['IssueFile']}")
                        current_item += 1
                        current_percent = int(current_item * 100 / total_items)
                        lazylibrarian.magazinescan_data = f"{current_item}/{total_items}/{current_percent}"
                        genres = mag[1]
                        tags = {}
                        cnt = 1
                        for i in get_list(genres):
                            tags[f'/Genre_{cnt}'] = i
                            cnt += 1
                        try:
                            res = write_pdf_tags(issue['IssueFile'], title, issue["IssueDate"], tags)
                        except Exception as e:
                            logger.error(f"Failed to tag {issue['IssueFile']}: {e}")
                            res = False
                        if not res:
                            failed += 1
                        else:
                            passed += 1
                            if CONFIG.get_bool('IMP_MAGOPF'):
                                logger.debug(f"Writing opf for {issue['IssueFile']}")
                                _, _ = lazylibrarian.metadata_opf.create_mag_opf(issue['IssueFile'], title,
                                                                                 issue["IssueDate"],
                                                                                 issue["IssueID"],
                                                                                 language=mag[0],
                                                                                 genres=genres,
                                                                                 overwrite=True)

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

                if action == "Remove" or action == "Delete":
                    db.action('DELETE from magazines WHERE Title=? COLLATE NOCASE', (title,))
                    db.action('DELETE from pastissues WHERE BookID=? COLLATE NOCASE', (title,))
                    db.action('DELETE from wanted where BookID=? COLLATE NOCASE', (title,))
                    logger.info(f'Magazine {title} removed from database')
                    passed += 1
                elif action == "Reset":
                    control_value_dict = {"Title": title}
                    new_value_dict = {
                        "LastAcquired": '',
                        "IssueDate": '',
                        "LatestCover": '',
                        "IssueStatus": "Wanted"
                    }
                    db.upsert("magazines", new_value_dict, control_value_dict)
                    logger.info(f'Magazine {title} details reset')
                    passed += 1
                elif action == 'Subscribe':
                    userid = owner_id()
                    if userid:
                        res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                       (userid, 'magazine', title))
                        if res:
                            logger.debug(f"User {userid} is already subscribed to {title}")
                            failed += 1
                        else:
                            db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                      (userid, 'magazine', title))
                            logger.debug(f"Subscribe {userid} to magazine {title}")
                            passed += 1
                elif action == 'Unsubscribe':
                    userid = owner_id()
                    if userid:
                        db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                  (userid, 'magazine', title))
                        res = db.select('SELECT issueid from issues where title=?', (title, ))
                        for iss in res:
                            db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                      (userid, 'magazine', iss['issueid']))
                        logger.debug(f"Unsubscribe {userid} to magazine {title}")
                    passed += 1

            except Exception as e:
                logger.error(f'Unable to {action} {title}: {type(e).__name__} {str(e)}')

        logger.debug(f"{action}:{title}: Pass {passed}, Fail {failed}")
        db.close()

        # Return JSON response instead of redirect
        total = passed + failed
        summary = mark_summary(i18n.gettext("Operation '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)

        res = {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary
        }
        logger.debug(f"{res}")
        logger.debug(f"Returning to {get_info_on_caller(depth=1)}")
        return res

    @cherrypy.expose
    @require_auth()
    def search_for_mag(self, bookid=None):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        bookdata = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (bookid,))
        db.close()
        if bookdata:
            # start searchthreads
            mags = [{"bookid": bookdata['Title']}]
            self.start_magazine_search(mags)
            raise cherrypy.HTTPRedirect("magazines")
        logger.warning(f"Magazine {bookid} was not found in the library")
        raise cherrypy.HTTPError(404, f"Magazine {bookid} not found")

    @cherrypy.expose
    @require_auth()
    def start_magazine_search(self, mags=None):
        logger = logging.getLogger(__name__)
        if mags:
            if CONFIG.use_any():
                threading.Thread(target=search_magazines, name='SEARCHMAG', args=[mags, False, False]).start()
                logger.debug(f"Searching for magazine with title: {mags[0]['bookid']}")
            else:
                logger.warning("Not searching for magazine, no download methods available. Check config and blocklist")
        else:
            logger.debug("MagazineSearch called with no magazines")

    @cherrypy.expose
    @require_auth()
    def add_magazine(self, title=None, **kwargs):
        logger = logging.getLogger(__name__)
        if not title or title == 'None':
            raise cherrypy.HTTPRedirect("magazines")

        self.validate_param("magazine title", title, ['<', '>', '='], 404)
        db = database.DBConnection()
        reject = None
        if '~' in title:  # separate out the "reject words" list
            reject = title.split('~', 1)[1].strip()
            title = title.split('~', 1)[0].strip()

        # replace any non-ascii quotes/apostrophes with ascii ones eg "Collector's"
        title = replace_all(title, lazylibrarian.DICTS.get('apostrophe_dict', {}))
        title_exploded = title.split()
        # replace symbols by words
        new_title = []
        for word in title_exploded:
            if word == '&' or word == '+':
                word = 'and'
            new_title.append(word)
        title = ' '.join(new_title)
        exists = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (title,))
        if exists:
            logger.debug(f"Magazine {title} already exists ({exists['Title']})")
        else:
            control_value_dict = {"Title": title}
            new_value_dict = {
                "Reject": reject,
                "Genre": "",
                "DateType": "",
                "Status": "Active",
                "MagazineAdded": today(),
                "LastAcquired": None,
                "LatestCover": None,
                "IssueDate": None,
                "IssueStatus": "Wanted",
                "Regex": None,
                "CoverPage": 1,
                "Language": CONFIG['PREF_MAGLANG'],
            }
            db.upsert("magazines", new_value_dict, control_value_dict)
            mags = [{"bookid": title}]
            if CONFIG.get_bool('IMP_AUTOSEARCH'):
                self.start_magazine_search(mags)
        db.close()
        if kwargs.get('magfilter'):
            raise cherrypy.HTTPRedirect("magazines?mag_filter=" + kwargs.get('magfilter'))
        raise cherrypy.HTTPRedirect("magazines")
