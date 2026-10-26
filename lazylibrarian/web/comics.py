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

""" The comic list, comic issues, finding and adding comics and marking them """

import datetime
import logging
import os
import threading
import traceback

import cherrypy
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import comicscan, database, i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.comicid import cv_identify, cx_identify, name_words, title_words
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, path_exists, path_isfile, splitext, syspath
from lazylibrarian.formatter import check_int, check_year, date_format, now, strip_quotes
from lazylibrarian.images import createthumb
from lazylibrarian.magazinescan import remove_if_empty
from lazylibrarian.web.common import BasePages, fold, serve_template

lastcomic = ''


class ComicPages(BasePages):
    """ The comic list, comic issues, finding and adding comics and marking them """

    @cherrypy.expose
    @require_auth()
    def edit_comic(self, comicid=None):
        self.label_thread('EDIT_COMIC')
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            data = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        finally:
            db.close()
        if data:
            return serve_template(templatename="editcomic.html", title=i18n.gettext("Edit Comic"), config=data)
        logger.info(f'Missing comic {comicid}:')
        raise cherrypy.HTTPError(404, f"Comic ID {comicid} not found")

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    def comic_update(self, comicid='', new_name='', new_id='', aka='', editordata='', **kwargs):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        comicdata = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        if comicdata:
            edited = ""
            if comicdata["Title"] != new_name:
                edited += "Title "
            if comicdata["aka"] != aka:
                edited += "aka "
            if comicdata["Description"] != editordata:
                edited += "Description "

            if comicid != new_id:
                match = db.match('SELECT ComicID from comics where ComicID=?', (new_id,))
                if match:
                    logger.debug(f"Unable to use new ID, {new_id} already exists")
                else:
                    db.action('PRAGMA foreign_keys = OFF')
                    db.action("UPDATE comics SET comicid=? WHERE comicid=?", (new_id, comicid))
                    db.action("UPDATE comicissues SET comicid=? WHERE comicid=?", (new_id, comicid))
                    db.action('PRAGMA foreign_keys = ON')
                    logger.debug(f"Updated comicid {comicid} to {new_id}")
                    comicid = new_id

            if edited:
                control_value_dict = {'ComicID': comicid}
                new_value_dict = {
                    'Title': new_name,
                    'aka': aka,
                    'Description': editordata
                }
                db.upsert("comics", new_value_dict, control_value_dict)
                logger.info(f'Updated [ {edited}] for {comicdata["Title"]}')
            else:
                logger.debug(f'Comic [{comicdata["Title"]}] has not been changed')
            db.close()
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        logger.warning(f"Invalid comicid [{comicid}]")
        db.close()
        raise cherrypy.HTTPError(404, f"Comic ID {comicid} not found")

    @cherrypy.expose
    @require_auth()
    def search_for_comic(self, comicid=None):
        db = database.DBConnection()
        try:
            bookdata = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        finally:
            db.close()
        if bookdata:
            # start searchthreads
            self.start_comic_search(comicid)
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def start_comic_search(self, comicid=None):
        logger = logging.getLogger(__name__)
        if comicid:
            if CONFIG.use_any():
                threading.Thread(target=search_comics, name='SEARCHCOMIC', args=[comicid]).start()
                logger.debug(f"Searching for comic ID {comicid}")
            else:
                logger.warning("Not searching for comic, no download methods available. Check config and blocklist")
        else:
            logger.debug("ComicSearch called with no comic ID")

    @cherrypy.expose
    @require_auth()
    def comics(self, comic_filter=''):
        user = owner_id()
        # use server-side processing
        covers = 1
        if not CONFIG['TOGGLES']:
            covers = 0
        return serve_template(templatename="comics.html", title=i18n.gettext("Comics"), comics=[],
                              covercount=covers, user=user, comic_filter=comic_filter)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_comics(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
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
                cmd = ("select comics.*,(select count(*) as counter from comicissues where "
                       "comics.comicid = comicissues.comicid) as Iss_Cnt from comics")

                mycomics = []
                args = ''
                if userid and userprefs & lazylibrarian.pref_mycomics:
                    res = db.select("SELECT WantID from subscribers WHERE Type='comic' and UserID=?", (userid,))
                    serversidelogger.debug(f"User subscribes to {len(res)} comics")
                    for mag in res:
                        mycomics.append(mag['WantID'])
                    cmd += " WHERE comics.comicid in (?)"
                    args = ", ".join(f"'{w}'" for w in mycomics)
                cmd += " order by Title"
                if args:
                    rowlist = db.select(cmd, (args, ))
                else:
                    rowlist = db.select(cmd)
            finally:
                db.close()

            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [mag['ComicID'], mag['LatestCover'], mag['Title'], mag['Iss_Cnt'], mag['LastAcquired'],
                             mag['LatestIssue'], mag['Status'], mag['IssueStatus'], mag['Start'],
                             mag['Publisher'], mag['Link'], mag['Genre']]
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
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
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
                    if not row[1] or not row[1].startswith('cache/'):
                        row[1] = 'images/nocover.jpg'
                    else:
                        fname, extn = splitext(row[1])
                        imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                        if path_isfile(imgfile):
                            row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                        else:
                            imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                            imgthumb = createthumb(imgfile, 200, False)
                            if imgthumb:
                                row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
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

            serversidelogger.debug(f"get_comics returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_comics filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_comics: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.COMIC_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def comic_scan(self, **kwargs):
        logger = logging.getLogger(__name__)
        comicid = kwargs.get('comicid')

        name = 'COMICSCAN'
        if comicid:
            name = f'{name}_{comicid}'
        if name not in [n.name for n in list(threading.enumerate())]:
            try:
                if comicid:
                    threading.Thread(target=comicscan.comic_scan, name=name, args=[comicid]).start()
                else:
                    threading.Thread(target=comicscan.comic_scan, name=name, args=[]).start()
            except Exception as e:
                logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{name} already running')
        if comicid:
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def comicissue_page(self, comicid):
        global lastcomic
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            mag_data = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        finally:
            db.close()
        if not mag_data:
            logger.warning(f"Invalid comic ID: {comicid}")
            raise cherrypy.HTTPError(404, f"Comic ID {comicid} not found")

        title = mag_data['Title']
        if title and '&' in title and '&amp;' not in title:
            safetitle = title.replace('&', '&amp;')
        else:
            safetitle = title

        user = owner_id()
        # use server-side processing
        if not CONFIG['TOGGLES']:
            covercount = 0
        else:
            covercount = 1

        # if we've changed comic, reset to first page of new comics issues
        if comicid == lastcomic:
            firstpage = 'false'
        else:
            lastcomic = comicid
            firstpage = 'true'

        return serve_template(templatename="comicissues.html", comicid=comicid,
                              title=safetitle, issues=[], covercount=covercount, user=user,
                              firstpage=firstpage)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_comic_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0,
                         sSortDir_0="desc", sSearch="", **kwargs):
        rows = []
        filtered = []
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')

        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            comicid = kwargs['comicid']
            db = database.DBConnection()
            try:
                mag_data = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
                title = mag_data['Title']
                rowlist = db.select('SELECT * from comicissues WHERE ComicID=? order by IssueID DESC', (comicid,))
            finally:
                db.close()
            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [title, mag['Cover'], mag['IssueID'], mag['IssueAcquired'], f"{comicid}_{mag['IssueID']}"]
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
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
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
                    if path_isfile(imgfile):
                        row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                    else:
                        imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                        imgthumb = createthumb(imgfile, 200, False)
                        if imgthumb:
                            row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                row[3] = date_format(row[3], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                row[2] = date_format(row[2], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

            serversidelogger.debug(f"get_comic_issues returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_comic_issues filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_comic_issues: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.COMIC_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def find_comic(self, title=None, **kwargs):
        # search for a comic title and produce a list of likely matches
        # noinspection PyGlobalUndefined
        global comicresults
        logger = logging.getLogger(__name__)
        comicresults = []
        if not title or title == 'None':
            raise cherrypy.HTTPRedirect("comics")
        title = strip_quotes(title)
        db = database.DBConnection()
        exists = db.match('SELECT Title from comics WHERE Title=?', (title,))
        if exists:
            logger.debug(f"Comic {title} already exists ({exists['Title']})")
        else:
            cvres = cv_identify(title, best=False)
            if title.startswith('CV'):
                for itm in cvres:
                    itm['fuzz'] = fuzz.token_sort_ratio(title, itm['seriesid'], processor=default_process)
                    comicresults.append(itm)
            else:
                cxres = cx_identify(title, best=False)
                words = name_words(title)
                titlewords = ' '.join(title_words(words))
                for itm in cvres:
                    itm['fuzz'] = fuzz.token_sort_ratio(titlewords, itm['title'], processor=default_process)
                    comicresults.append(itm)
                for itm in cxres:
                    itm['fuzz'] = fuzz.token_sort_ratio(titlewords, itm['title'], processor=default_process)
                    comicresults.append(itm)
                comicresults = sorted(comicresults, key=lambda x: -(check_int(x["fuzz"], 0)))
            comicids = db.select("SELECT ComicID from comics")
            comiclist = []
            for itm in comicids:
                comiclist.append(itm['ComicID'])
            return serve_template(templatename="comicresults.html", title=i18n.gettext("Comics"),
                                  results=comicresults, comicids=comiclist)
        db.close()

        if kwargs.get('comicfilter'):
            raise cherrypy.HTTPRedirect("comics?comic_filter=" + kwargs.get('comicfilter'))
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def add_comic(self, comicid=None, **kwargs):
        # add a comic from a list in comicresults.html
        global comicresults
        logger = logging.getLogger(__name__)
        apikey = CONFIG['CV_APIKEY']
        if not comicid or comicid == 'None':
            raise cherrypy.HTTPRedirect("comics")
        if comicid.startswith('CV') and not apikey:
            msg = "Please obtain an apikey from https://comicvine.gamespot.com/api/"
            logger.warning(msg)
            raise cherrypy.HTTPError(403, msg)

        self.validate_param("comicid", comicid, ['<', '&', '>', '=', '"', "'", '+', '(', ')'], 404)
        db = database.DBConnection()
        match = False
        exists = db.match('SELECT Title from comics WHERE ComicID=?', (comicid,))
        if exists:
            logger.debug(f"Comic {exists['Title']} already exists ({exists['comicid']})")
        else:
            try:
                for itm in comicresults:
                    if itm['seriesid'] == comicid:
                        aka = ''
                        akares = cv_identify(itm['title'])
                        if not akares:
                            akares = cx_identify(itm['title'])
                        if akares and akares[3]['seriesid'] != comicid:
                            aka = akares[3]['seriesid']
                        db.action('INSERT INTO comics (ComicID, Title, Status, Added, LastAcquired, ' +
                                  'Updated, LatestIssue, IssueStatus, LatestCover, SearchTerm, Start, ' +
                                  'First, Last, Publisher, Link, aka) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                  (comicid, itm['title'], 'Active', now(), None,
                                   now(), None, 'Wanted', None, itm['searchterm'], itm['start'],
                                   itm['first'], itm['last'], itm['publisher'], itm['link'], aka))
                        match = True
                        break
            except NameError:
                match = False
            if not match:
                msg = f"Failed to get data for {comicid}"
                logger.warning(msg)
                raise cherrypy.HTTPError(404, msg)

        if match and CONFIG.get_bool('IMP_AUTOSEARCH'):
            self.start_comic_search(comicid)
        db.close()
        if kwargs.get('comicfilter'):
            raise cherrypy.HTTPRedirect("comics?comic_filter=" + kwargs.get('comicfilter'))
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def mark_comics(self, action=None, **args):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        args.pop('book_table_length', None)
        for itm in args:
            if action == "Paused" or action == "Active":
                control_value_dict = {"ComicID": itm}
                new_value_dict = {"Status": action}
                db.upsert("comics", new_value_dict, control_value_dict)
                logger.info(f'Status of comic {itm} changed to {action}')
            if action == "Delete":
                issues = db.select('SELECT IssueFile from comicissues WHERE ComicID=?', (itm,))
                logger.debug(f'Deleting comic {itm} from disc')
                issuedir = ''
                for issue in issues:  # delete all issues of this comic
                    result = self.delete_issue(issue['IssueFile'])
                    if result:
                        logger.debug(f'Issue {issue["IssueFile"]} deleted from disc')
                        issuedir = os.path.dirname(issue['IssueFile'])
                    else:
                        logger.debug(f'Failed to delete {issue["IssueFile"]}')

                # if the directory is now empty, delete that too
                if issuedir and CONFIG.get_bool('COMIC_DELFOLDER'):
                    magdir = os.path.dirname(issuedir)
                    # if no magazine issues left in the folder, delete it
                    # (removes any trailing cover images, opf etc)
                    remove_if_empty(magdir, booktype='comic')
                    logger.info(f'Comic {itm} deleted from disc')

            if action == "Remove" or action == "Delete":
                db.action('DELETE from comics WHERE ComicID=?', (itm,))
                db.action('DELETE from wanted where BookID=?', (itm,))
                logger.info(f'Comic {itm} removed from database')
            if action == "Reset":
                control_value_dict = {"ComicID": itm}
                new_value_dict = {
                    "LastAcquired": '',
                    "LatestIssue": '',
                    "LatestCover": '',
                    "IssueStatus": "Wanted"
                }
                db.upsert("comics", new_value_dict, control_value_dict)
                logger.info(f'Comic {itm} details reset')

            if action == 'Subscribe':
                userid = owner_id()
                if userid:
                    res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                   (userid, 'comic', itm))
                    if res:
                        logger.debug(f"User {userid} is already subscribed to {itm}")
                    else:
                        db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                  (userid, 'comic', itm))
                        logger.debug(f"Subscribe {userid} to comic {itm}")
            if action == 'Unsubscribe':
                userid = owner_id()
                if userid:
                    db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                              (userid, 'comic', itm))
                    res = db.select('SELECT issueid from comicissues where comicid=?', (itm,))
                    for iss in res:
                        db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                  (userid, 'comic', iss['issueid']))
                    logger.debug(f"Unsubscribe {userid} to comic {itm}")
        db.close()
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def mark_comic_issues(self, action=None, **args):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        args.pop('book_table_length', None)
        comicid = None
        for itm in args:
            comicid, issueid = itm.split('_')
            cmd = ("SELECT IssueFile,Title,comics.ComicID from comics,comicissues WHERE "
                   "comics.ComicID = comicissues.ComicID and comics.ComicID=? and IssueID=?")
            issue = db.match(cmd, (comicid, issueid))
            if issue:
                if action == "Delete":
                    result = self.delete_issue(issue['IssueFile'])
                    if result:
                        logger.info(f'Issue {issueid} of {issue["Title"]} deleted from disc')
                if action == "Remove" or action == "Delete":
                    db.action('DELETE from comicissues WHERE ComicID=? and IssueID=?', (comicid, issueid))
                    logger.info(f'Issue {issueid} of {issue["Title"]} removed from database')
                    # Set issuedate to issuedate of most recent issue we have
                    # Set latestcover to most recent issue cover
                    # Set lastacquired to acquired date of most recent issue we have
                    # Set added to acquired date of the earliest issue we have
                    cmd = ("select IssueID,IssueAcquired,IssueFile from comicissues where ComicID=?"
                           " order by IssueID ")
                    newest = db.match(cmd + 'DESC', (comicid,))
                    oldest = db.match(cmd + 'ASC', (comicid,))
                    control_value_dict = {'ComicID': comicid}
                    if newest and oldest:
                        old_acquired = ''
                        new_acquired = ''
                        cover = ''
                        issuefile = newest['IssueFile']
                        if path_exists(issuefile):
                            cover = splitext(issuefile)[0] + '.jpg'
                            mtime = os.path.getmtime(syspath(issuefile))
                            new_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))
                        issuefile = oldest['IssueFile']
                        if path_exists(issuefile):
                            mtime = os.path.getmtime(syspath(issuefile))
                            old_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))

                        new_value_dict = {
                            'LatestIssue': newest['IssueID'],
                            'LatestCover': cover,
                            'LastAcquired': new_acquired,
                            'Added': old_acquired
                        }
                    else:
                        new_value_dict = {
                            'LatestIssue': '',
                            'LastAcquired': '',
                            'LatestCover': '',
                            'Added': ''
                        }
                    db.upsert("comics", new_value_dict, control_value_dict)
        db.close()
        if comicid:
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")

        raise cherrypy.HTTPRedirect("comics")
