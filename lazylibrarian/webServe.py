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


import ast
import contextlib
import datetime
import logging
import os
import re
import subprocess
import threading
import traceback
import uuid
from shutil import copyfile
from urllib.parse import quote, urlsplit, urlunsplit

import cherrypy
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import comicscan, database, grsync, hc, i18n, magazinescan, versioncheck
from lazylibrarian.auth import AuthController, owner_id, require_auth
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.calibre import calibredb, get_calibre_id, sync_calibre_list
from lazylibrarian.calibre_integration import send_mag_issue_to_calibre
from lazylibrarian.comicid import cv_identify, cx_identify, name_words, title_words
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.common import create_support_zip, log_header
from lazylibrarian.config2 import CONFIG
from lazylibrarian.csvfile import export_csv, import_csv
from lazylibrarian.download_client import get_download_progress
from lazylibrarian.filesystem import (
    DIRS,
    csv_file,
    path_exists,
    path_isfile,
    remove_file,
    setperm,
    splitext,
    syspath,
)
from lazylibrarian.formatter import (
    check_int,
    check_year,
    date_format,
    get_list,
    make_unicode,
    now,
    plural,
    replace_all,
    strip_quotes,
    today,
)
from lazylibrarian.images import (
    coverswap,
    create_mag_cover,
    createthumb,
    read_pdf_tags,
    write_pdf_tags,
)
from lazylibrarian.librarysync import library_scan
from lazylibrarian.logconfig import LOGCONFIG
from lazylibrarian.magazinescan import get_dateparts, magazine_scan, remove_if_empty, rename_issue
from lazylibrarian.manual_import import process_alternate, process_issues
from lazylibrarian.oldump import update_openlibrary_dump
from lazylibrarian.opds import OPDS
from lazylibrarian.postprocess import process_dir
from lazylibrarian.processcontrol import get_info_on_caller
from lazylibrarian.rssfeed import gen_feed
from lazylibrarian.scheduling import (
    SchedulerCommand,
    all_author_update,
    restart_jobs,
    schedule_job,
    show_jobs,
    show_stats,
)
from lazylibrarian.searchmag import download_maglist, search_magazines
from lazylibrarian.searchrss import search_wishlist
from lazylibrarian.web.authors import AuthorPages
from lazylibrarian.web.books import BookPages
from lazylibrarian.web.common import BasePages, fold, mark_summary, serve_template
from lazylibrarian.web.connection_tests import ConnectionTestPages
from lazylibrarian.web.files import FilePages
from lazylibrarian.web.series import SeriesPages
from lazylibrarian.web.settings import SettingsPages
from lazylibrarian.web.users import UserPages
from lazylibrarian.web.wall import WallPages

lastmagazine = ''
lastcomic = ''


# noinspection PyProtectedMember,PyGlobalUndefined,PyGlobalUndefined
class WebInterface(UserPages, SeriesPages, SettingsPages, ConnectionTestPages, AuthorPages, BookPages, FilePages, WallPages, BasePages):
    _cp_config = {'tools.ui_language.on': True}

    auth = AuthController()
    issues_data = ''

    @cherrypy.expose
    @require_auth()
    def index(self):
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    def login(self):
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    def home(self):
        logger = logging.getLogger(__name__)
        home = CONFIG.get_str('HOMEPAGE')
        logger.debug(f"Homepage [{home}]")
        if home == 'eBooks':
            raise cherrypy.HTTPRedirect("books")
        if home == 'Series':
            raise cherrypy.HTTPRedirect("series")
        if home == 'AudioBooks':
            raise cherrypy.HTTPRedirect("audio")
        if home == 'Magazines':
            raise cherrypy.HTTPRedirect("magazines")
        if home == 'Comics':
            raise cherrypy.HTTPRedirect("comics")
        raise cherrypy.HTTPRedirect("authors")

    # AUTHOR ############################################################

    # GoodReads prefixes its 'about' field with an editorial note like:
    # "<i>Librarian Note: There is more than one author in the Goodreads
    # database with this name.</i><br /><br />actual bio..." when applicable
    # (duplicate-author disambiguation, merged records, etc.) - GR's own
    # convention, not a separate structured API field. get_all_author_details()
    # stores 'about' verbatim, so this is detectable straight from what's
    # already in the authors table, no extra fetch or schema change needed.
    LIBRARIAN_NOTE_RE = re.compile(
        r'^\s*<i>\s*Librarian Note:\s*(?P<note>.*?)\s*</i>\s*(?:<br\s*/?>\s*)*', re.IGNORECASE | re.DOTALL)

    # COMICS #########################################################

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

    # MAGAZINES #########################################################

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
    def libraryscan_progress(self):
        try:
            current, total, percent = lazylibrarian.libraryscan_data.split('/')
        except ValueError:
            return lazylibrarian.libraryscan_data

        bar = ('<div class="text-center">Scanning Library Folders<br></div>'
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

    # UPDATES ###########################################################

    @cherrypy.expose
    @require_auth()
    def check_for_updates(self):
        self.label_thread('UPDATES')
        versioncheck.check_for_updates()
        behind = CONFIG.get_int('COMMITS_BEHIND')
        if behind == 0:
            if lazylibrarian.COMMIT_LIST:
                message = i18n.gettext("LazyLibrarian status is unknown")
                messages = lazylibrarian.COMMIT_LIST.replace('\n', '<br>')
                message = message + '<br><small>' + messages
            else:
                message = i18n.gettext("LazyLibrarian is up to date")
        elif behind > 0:
            message = i18n.ngettext("LazyLibrarian is behind by %(count)s commit",
                                    "LazyLibrarian is behind by %(count)s commits", behind) % {'count': behind}
            messages = lazylibrarian.COMMIT_LIST.replace('\n', '<br>')
            message = message + '<br><small>' + messages

            if '** MANUAL **' in lazylibrarian.COMMIT_LIST:
                message += i18n.gettext("Update needs manual installation")
        else:
            message = i18n.gettext("LazyLibrarian version is unknown")
            messages = i18n.gettext("Your version (%(version)s) is not recognized at %(repo)s") % {
                'version': CONFIG['CURRENT_VERSION'],
                'repo': f"https://{CONFIG['GIT_HOST']}/{CONFIG['GIT_USER']}/{CONFIG['GIT_REPO']}"}
            messages += '  ' + i18n.gettext('Branch: %(branch)s') % {'branch': CONFIG['GIT_BRANCH']}
            message = message + '<br><small>' + messages

        return message

    @cherrypy.expose
    @require_auth()
    def force_update(self):
        logger = logging.getLogger(__name__)
        if 'AAUPDATE' not in [n.name for n in list(threading.enumerate())]:
            threading.Thread(target=all_author_update, name='AAUPDATE', args=[False]).start()
        else:
            logger.debug('AAUPDATE already running')
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def force_openlibrary_dump(self):
        """ AJAX: manually trigger an OpenLibrary bulk-dump sync right now instead of
        waiting for its next scheduled run. Resumes any partially-downloaded file left
        from a previous interrupted run via the same Range-resume logic the scheduled
        job itself uses - see oldump.download_dump_file. """
        logger = logging.getLogger(__name__)
        if not CONFIG['OL_USE_DUMP']:
            return {'error': 'OpenLibrary local dump indexing is not enabled in Config -> Importing'}
        if 'OLDUMPUPDATE' in [n.name for n in list(threading.enumerate())]:
            return {'error': 'OpenLibrary dump sync is already running'}
        threading.Thread(target=update_openlibrary_dump, name='OLDUMPUPDATE', args=[]).start()
        logger.info("Manually triggered OpenLibrary bulk dump sync")
        return {'success': True}

    @cherrypy.expose
    @require_auth()
    def update(self):
        logger = logging.getLogger(__name__)
        self.label_thread('UPDATING')
        logger.debug('(webServe-Update) - Performing update')
        remove_file(os.path.join(DIRS.CACHEDIR, 'alive.png'))
        lazylibrarian.SIGNAL = 'update'
        message = i18n.gettext('LazyLibrarian is updating...')
        return serve_template(templatename="shutdown.html", prefix='', title=i18n.gettext("Updating"),
                              message=message, timer=90)

    # IMPORT/EXPORT #####################################################

    @cherrypy.expose
    @require_auth()
    def library_scan(self, **kwargs):
        logger = logging.getLogger(__name__)
        types = []
        if CONFIG.get_bool('EBOOK_TAB'):
            types.append('eBook')
        if CONFIG.get_bool('AUDIO_TAB'):
            types.append('AudioBook')
        if not types:
            raise cherrypy.HTTPRedirect('authors')
        library = types[0]
        if 'library' in kwargs and kwargs['library'] in types:
            library = kwargs['library']

        removed = CONFIG.get_bool('FULL_SCAN')
        threadname = f"{library.upper()}_SCAN"
        if threadname not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=library_scan, name=threadname, args=[None, library, None, removed]).start()
            except Exception as e:
                logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{threadname} already running')
        if library == 'AudioBook':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def clean_magazine_library(self):
        magazinescan.clean_maglibrary()
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def magazine_scan(self, **kwargs):
        logger = logging.getLogger(__name__)
        if 'title' in kwargs:
            title = kwargs['title']
            title = title.replace('&amp;', '&')
        else:
            title = ''

        threadname = "MAGAZINE_SCAN"
        if title:
            threadname = f'{threadname}_{title}'
        if threadname not in [n.name for n in list(threading.enumerate())]:
            try:
                if title:
                    threading.Thread(target=magazinescan.magazine_scan, name=threadname, args=[title]).start()
                else:
                    threading.Thread(target=magazinescan.magazine_scan, name=threadname, args=[]).start()
            except Exception as e:
                logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{threadname} already running')
        if title:
            raise cherrypy.HTTPRedirect(f"issue_page?title={quote(title)}")
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def include_alternate(self, library='eBook'):
        logger = logging.getLogger(__name__)
        if 'ALT-LIBRARYSCAN' not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=library_scan, name='ALT-LIBRARYSCAN',
                                 args=[CONFIG['ALTERNATE_DIR'], library, None, False]).start()
            except Exception as e:
                logger.error(f'Unable to complete the libraryscan: {type(e).__name__} {str(e)}')
        else:
            logger.debug('ALT-LIBRARYSCAN already running')
        raise cherrypy.HTTPRedirect(f"manage?library={library}")

    @cherrypy.expose
    @require_auth()
    def import_issues(self, title=None):
        logger = logging.getLogger(__name__)
        if not title:
            logger.error("No title to import")
            raise cherrypy.HTTPRedirect("magazines")
        threadname = f"IMPORTISSUES_{title}"
        if threadname not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=process_issues, name=threadname,
                                 args=[CONFIG['ALTERNATE_DIR'], title]).start()
            except Exception as e:
                logger.error(f'Unable to complete the import: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{threadname} already running')
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(title)}")

    @cherrypy.expose
    @require_auth()
    def import_alternate(self, library='eBook'):
        self.validate_param("library name", library, ['<', '>', '='], 404)
        logger = logging.getLogger(__name__)
        if f'IMPORTALT_{library}' not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=process_alternate, name=f'IMPORTALT_{library}',
                                 args=[CONFIG['ALTERNATE_DIR'], library]).start()
            except Exception as e:
                logger.error(f'Unable to complete the import: {type(e).__name__} {str(e)}')
        else:
            logger.debug('IMPORTALT already running')
        raise cherrypy.HTTPRedirect(f"manage?library={library}")

    @cherrypy.expose
    def rss_feed(self, **kwargs):
        logger = logging.getLogger(__name__)
        self.label_thread('RSSFEED')
        if 'type' in kwargs:
            ftype = kwargs['type']
        else:
            return ''

        limit = kwargs.get('limit', '10')
        authorid = kwargs.get('authorid')
        onetitle = kwargs.get('onetitle')

        # url might end in .xml
        if not limit.isdigit():
            try:
                limit = int(limit.split('.')[0])
            except (IndexError, ValueError):
                limit = 10

        userid = 0
        if 'user' in kwargs:
            userid = kwargs['user']
        else:
            userid = owner_id()

        scheme, netloc, path, qs, anchor = urlsplit(cherrypy.url())

        my_ip = CONFIG['RSS_HOST']
        if not my_ip:
            my_ip = cherrypy.request.headers.get('X-Forwarded-Host')
        if not my_ip:
            my_ip = cherrypy.request.headers.get('Host')
        if not my_ip:
            my_ip = netloc
        path = path.replace('rss_feed', '').rstrip('/')

        baseurl = urlunsplit((scheme, my_ip, path, qs, anchor))

        remote_ip = cherrypy.request.headers.get('X-Forwarded-For')  # apache2
        if not remote_ip:
            remote_ip = cherrypy.request.headers.get('X-Host')  # lighthttpd
        if not remote_ip:
            remote_ip = cherrypy.request.headers.get('Remote-Addr')
        if not remote_ip:
            remote_ip = cherrypy.request.remote.ip
        remote_ip = remote_ip.split(',')[0]

        if onetitle:
            filename = f'LazyLibrarian_RSS_{onetitle.replace("&amp;", "&")}.xml'
        else:
            filename = f'LazyLibrarian_RSS_{ftype}.xml'
        logger.debug(f"rss Feed request {limit} {ftype}{plural(limit)}: {remote_ip} {userid}")
        cherrypy.response.headers["Content-Type"] = 'application/rss+xml'
        cherrypy.response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        res = gen_feed(ftype, limit=limit, user=userid, baseurl=baseurl, authorid=authorid, onetitle=onetitle)
        return res.encode('UTF-8')

    @cherrypy.expose
    @require_auth()
    def import_csv(self, library=''):
        self.validate_param("library name", library, ['<', '>', '='], 404)
        logger = logging.getLogger(__name__)
        if f'IMPORTCSV_{library}' not in [n.name for n in list(threading.enumerate())]:
            self.label_thread('IMPORTCSV')
            try:
                csvfile = csv_file(CONFIG['ALTERNATE_DIR'], library=library)
                if path_exists(csvfile):
                    message = i18n.gettext("Importing csv (background task) from %(file)s") % {'file': csvfile}
                    threading.Thread(target=import_csv, name=f'IMPORTCSV_{library}',
                                     args=[CONFIG['ALTERNATE_DIR'], 'Wanted', library]).start()
                else:
                    message = i18n.gettext("No %(library)s CSV file in [%(folder)s]") % {
                        'library': i18n.status_label(library), 'folder': CONFIG['ALTERNATE_DIR']}
            except Exception as e:
                logger.error(f'Unable to complete the import: {type(e).__name__} {str(e)}')
                message = i18n.gettext('Unable to complete the import: %(error)s') % {
                    'error': f'{type(e).__name__} {str(e)}'}
        else:
            logger.debug('IMPORTCSV already running')
            message = i18n.gettext('CSV import is already running')
        return message

    @cherrypy.expose
    @require_auth()
    def export_csv(self, library=''):
        self.validate_param("library name", library, ['<', '>', '='], 404)
        self.label_thread('EXPORTCSV')
        message = export_csv(CONFIG['ALTERNATE_DIR'], library=library)
        message = message.replace('\n', '<br>')
        return message

    # JOB CONTROL #######################################################

    @cherrypy.expose
    @require_auth()
    def shutdown(self):
        self.label_thread('SHUTDOWN')
        # lazylibrarian.config_write()
        remove_file(os.path.join(DIRS.CACHEDIR, 'alive.png'))
        lazylibrarian.SIGNAL = 'shutdown'
        message = i18n.gettext('LazyLibrarian is closed')
        return serve_template(templatename="shutdown.html", prefix='', title=i18n.gettext("Close library"),
                              message=message, timer=0)

    @cherrypy.expose
    @require_auth()
    def restart(self):
        self.label_thread('RESTART')
        remove_file(os.path.join(DIRS.CACHEDIR, 'alive.png'))
        lazylibrarian.SIGNAL = 'restart'
        message = i18n.gettext('LazyLibrarian is reopening...')
        return serve_template(templatename="shutdown.html", prefix='', title=i18n.gettext("Reopen library"),
                              message=message, timer=50)

    @cherrypy.expose
    @require_auth()
    def show_jobs(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        # show the current status of LL cron jobs
        resultlist = show_jobs()
        result = ''
        for line in resultlist:
            result = result + line + '\n'
        return result

    @cherrypy.expose
    @require_auth()
    def show_apprise(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # show the available notifiers
        apprise_list = lazylibrarian.notifiers.apprise_notify.AppriseNotifier.notify_types()
        result = ''
        results = []
        try:
            for entry in apprise_list:
                if isinstance(entry, str):
                    results.append(entry)
            results.sort(key=str.casefold)
            result = "\n".join(results)
        except Exception as e:
            logger.debug(str(e))
        return result

    @cherrypy.expose
    @require_auth()
    def show_stats(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        # show some database status info
        resultlist = show_stats()
        result = ''
        for line in resultlist:
            result = result + line + '\n'
        return result

    @cherrypy.expose
    @require_auth()
    def restart_jobs(self):
        restart_jobs(command=SchedulerCommand.RESTART)

    @cherrypy.expose
    @require_auth()
    def stop_jobs(self):
        restart_jobs(command=SchedulerCommand.STOP)

    # LOGGING ###########################################################

    @cherrypy.expose
    @require_auth()
    def clear_log(self):
        logger = logging.getLogger(__name__)
        LOGCONFIG.clear_ui_log()
        logger.info('Screen log cleared')
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def toggle_detailed_logs(self):
        detail = CONFIG.get_bool('DETAILEDUILOG')
        CONFIG.set_bool('DETAILEDUILOG', not detail)
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def delete_logs(self):
        logger = logging.getLogger(__name__)
        result = LOGCONFIG.delete_log_files(CONFIG['LOGDIR'])
        logger.info(result)
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def get_support_zip(self):
        # Save the redacted log and config to a zipfile
        self.label_thread('SAVELOG')
        logger = logging.getLogger(__name__)
        msg, zipfile = create_support_zip()
        logger.info(msg)
        return cherrypy.lib.static.serve_file(zipfile, 'application/x-download', 'attachment',
                                              os.path.basename(zipfile))
        # raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def log_header(self):
        # Return the log header info
        result = log_header()
        return result

    @cherrypy.expose
    @require_auth()
    def logs(self):
        return serve_template(templatename="logs.html", title=i18n.gettext("Log"), lineList=[])  # lazylibrarian.LOGLIST)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_log(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        # kwargs is used by datatables to pass params
        logger = logging.getLogger(__name__)
        rows = filtered = []
        total = 0

        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            filtered, total = LOGCONFIG.get_ui_logrows(sSearch)

            sortcolumn = int(iSortCol_0)
            filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                          reverse=sSortDir_0 == "desc")
            rows = filtered if displaylength < 0 else filtered[displaystart:(displaystart + displaylength)]
        except Exception:
            logger.error(f'Unhandled exception in get_log: {traceback.format_exc()}')
            rows = filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': total,
                  'aaData': rows,
                  }
        return mydict

    # HISTORY ###########################################################

    @cherrypy.expose
    @require_auth()
    def history(self):
        return serve_template(templatename="history.html", title=i18n.gettext("History"), history=[])

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_history(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        rows = []
        filtered = []
        rowlist = []
        self.label_thread('WEBSERVER')
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            snatching = 0
            cmd = "SELECT NZBTitle,AuxInfo,BookID,NZBProv,NZBDate,NZBSize,Status,Source,DownloadID,rowid from wanted "
            cmd += "where BookID is not null and AuxInfo is not null"
            rowlist = db.select(cmd)
            # turn the sqlite rowlist into a list of dicts
            if len(rowlist):
                # the masterlist to be filled with the row data
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)  # turn sqlite objects into lists
                    rows.append(entry)  # add the rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    q = fold(sSearch)
                    filtered = [x for x in rows if q in fold(x)]
                    #filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                # use rowid to get most recently added first (monitoring progress)
                if sortcolumn == 6:
                    sortcolumn = 9

                if sortcolumn == 5:
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    nrows = filtered
                else:
                    nrows = filtered[displaystart:(displaystart + displaylength)]

                lazylibrarian.HIST_REFRESH = 0
                rows = []
                for row in nrows:
                    row = list(row)
                    row[8] = make_unicode(row[8])  # delugerpc returns bytes
                    # title needs spaces, not dots, for column resizing
                    title = row[0]  # type: str
                    if title:
                        title = title.replace('.', ' ')
                        row[0] = title
                    # provider name needs to be shorter and with spaces for column resizing
                    if row[3]:
                        row[3] = CONFIG.disp_name(row[3].strip('/'))
                    # separate out rowid and other additions, so we don't break legacy interface
                    rowid = row[9]
                    row = row[:9]
                    if row[6] == 'Snatched':
                        snatching += 1
                        if snatching <= 5:
                            progress, _ = get_download_progress(row[7], row[8])
                            row.append(progress)
                            if progress < 100:
                                lazylibrarian.HIST_REFRESH = CONFIG.get_int('HIST_REFRESH')
                        else:
                            row.append(-1)
                    else:
                        row.append(-1)
                    row.append(rowid)
                    row.append(row[4])  # keep full datetime for tooltip
                    row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

                    if row[1] in ['eBook', 'AudioBook']:
                        btn = '<button onclick="bookinfo(\'' + row[2]
                        btn += '\')" class="button btn-link text-left" type="button" '
                        btn += '>' + row[1] + '</button>'
                        row[1] = btn
                        auth = db.match('SELECT authorid from books where bookid=?', (row[2],))
                        if auth:
                            # noinspection PyBroadException
                            try:
                                btn = '<a href=\'author_page?authorid='
                                btn += auth['authorid']
                                btn += '\'">' + row[2] + '</a>'
                                row[2] = btn
                            except Exception:
                                logger.debug(f"Unexpected authorid [{auth}]")
                    elif row[1] == 'comic':
                        btn = '<a href=\'open_comic?comicid=' + row[2].split('_')[0] + '\'">' + row[2] + '</a>'
                        row[2] = btn
                    else:
                        # noinspection PyBroadException
                        try:
                            if row[1] and re.match(r"^[0-9.-]+$", row[1]) is not None:  # Magazine
                                btn = '<a href=\'open_mag?bookid=' + row[2] + '\'">' + row[2] + '</a>'
                                row[2] = btn
                        except Exception:
                            logger.debug(f"Unexpected auxinfo [{row[1]}] {row[2]}")
                            continue
                    rows.append(row)

            serversidelogger.debug(
                f"get_history returning {displaystart} to {displaystart + displaylength}, snatching {snatching}")
            serversidelogger.debug(f"get_history filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_history: {traceback.format_exc()}')
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
    def show_running(self):
        """ return a list of currently running tasks """
        return lazylibrarian.scheduling.show_running()


    @cherrypy.expose
    @require_auth()
    def dlinfo(self, target=None):
        if '^' not in target:
            return ''
        db = database.DBConnection()
        status, rowid = target.split('^')
        if status == 'Ignored':
            match = db.match('select ScanResult from books WHERE bookid=?', (rowid,))
            message = i18n.gettext('Reason: %(reason)s') % {'reason': match["ScanResult"]} + '<br>'
        else:
            cmd = ("select NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,DLResult,Source,"
                   "DownloadID from wanted where rowid=?")
            match = db.match(cmd, (rowid,))
            dltype = match['AuxInfo']
            if dltype not in ['eBook', 'AudioBook']:
                if not dltype:
                    dltype = 'eBook'
                else:
                    dltype = 'Magazine'
            lines = [
                i18n.gettext("Title: %(value)s") % {'value': match['NZBtitle']},
                i18n.gettext("Type: %(value)s") % {'value': f"{match['NZBmode']} {i18n.status_label(dltype)}"},
                i18n.gettext("Date: %(value)s") % {'value': match['NZBdate']},
                i18n.gettext("Size: %(value)s Mb") % {'value': match['NZBsize']},
                i18n.gettext("Provider: %(value)s") % {'value': CONFIG.disp_name(match['NZBprov'])},
                i18n.gettext("Downloader: %(value)s") % {'value': match['Source']},
                i18n.gettext("DownloadID: %(value)s") % {'value': match['DownloadID']},
                i18n.gettext("URL: %(value)s") % {'value': match['NZBurl']},
            ]
            message = '<br>'.join(lines) + '<br>'
            if status == 'Processed':
                message += i18n.gettext("File: %(value)s") % {'value': match['DLResult']} + '<br>'
            elif status == 'Seeding':
                message += i18n.status_label(status)
            else:
                message += i18n.gettext("Error: %(value)s") % {'value': match['DLResult']} + '<br>'
        db.close()
        return message

    @cherrypy.expose
    @require_auth()
    def deletehistory(self, rowid=None):
        logger = logging.getLogger(__name__)
        if not rowid:
            logger.warning("No rowid in deletehistory")
        else:
            db = database.DBConnection()
            try:
                match = db.match('SELECT NZBtitle,Status from wanted WHERE rowid=?', (rowid,))
                if match:
                    logger.debug(f'Deleting {match["Status"]} history item {match["NZBtitle"]}')
                    db.action('DELETE from wanted WHERE rowid=?', (rowid,))
                else:
                    logger.warning(f"No rowid {rowid} in history")
            finally:
                db.close()

    @cherrypy.expose
    @require_auth()
    def markhistory(self, rowid=None):
        logger = logging.getLogger(__name__)
        if not rowid:
            return
        db = database.DBConnection()
        match = db.match('SELECT NZBtitle,Status,BookID,AuxInfo from wanted WHERE rowid=?', (rowid,))
        logger.debug(f'Marking {match["Status"]} history item {match["NZBtitle"]} as Failed')
        db.action("UPDATE wanted SET Status='Failed' WHERE rowid=?", (rowid,))
        book_type = match['AuxInfo']
        if book_type not in ['AudioBook', 'eBook']:
            if not book_type:
                book_type = 'eBook'
            else:
                book_type = 'Magazine'
        if book_type == 'AudioBook':
            db.action("UPDATE books SET audiostatus='Wanted' WHERE BookID=?", (match["BookID"],))
        else:
            db.action("UPDATE books SET status='Wanted' WHERE BookID=?", (match["BookID"],))
        db.close()

    @cherrypy.expose
    @require_auth()
    def clearhistory(self, status=None):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        if not status or status == 'all':
            logger.info("Clearing all history")
            # Reset Snatched books back to Wanted so they get searched again
            status = "Snatched"
            cmd = "SELECT BookID,AuxInfo from wanted WHERE Status=?"
            rowlist = db.select(cmd, (status,))
            for book in rowlist:
                if book['BookID'] != 'unknown':
                    if book['AuxInfo'] == 'eBook':
                        db.action("UPDATE books SET Status='Wanted' WHERE Bookid=? AND Status=?",
                                  (book['BookID'], status))
                    elif book['AuxInfo'] == 'AudioBook':
                        db.action("UPDATE books SET AudioStatus='Wanted' WHERE Bookid=? AND AudioStatus=?",
                                  (book['BookID'], status))
            db.action("DELETE from wanted")
        else:
            logger.info(f"Clearing history where status is {status}")
            if status == 'Snatched':
                # Reset Snatched books back to Wanted so they get searched again
                cmd = "SELECT BookID,AuxInfo from wanted WHERE Status in ('Snatched', 'Matched')"
                rowlist = db.select(cmd)
                for book in rowlist:
                    if book['BookID'] != 'unknown':
                        if book['AuxInfo'] == 'eBook':
                            db.action("UPDATE books SET Status='Wanted' WHERE Bookid=? AND Status=?",
                                      (book['BookID'], status))
                        elif book['AuxInfo'] == 'AudioBook':
                            db.action("UPDATE books SET AudioStatus='Wanted' WHERE Bookid=? AND AudioStatus=?",
                                      (book['BookID'], status))
                db.action("DELETE from wanted WHERE Status='Matched'")
            db.action('DELETE from wanted WHERE Status=?', (status,))
        db.close()
        raise cherrypy.HTTPRedirect("history")

    @cherrypy.expose
    @require_auth()
    def clearblocked(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # clear any currently blocked providers
        num = BLOCKHANDLER.clear_all()
        logger.debug(f'Cleared {num} blocked {plural(num, "provider")}')
        return i18n.ngettext('Cleared %(count)s blocked provider', 'Cleared %(count)s blocked providers',
                             num) % {'count': num}

    @cherrypy.expose
    @require_auth()
    def showblocked(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # show any currently blocked providers
        result = BLOCKHANDLER.get_text_list_of_blocks()
        logger.debug(result)
        return result

    @cherrypy.expose
    @require_auth()
    def cleardownloads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # clear download counters
        db = database.DBConnection()
        try:
            count = db.match('SELECT COUNT(*) as counter FROM downloads')
            if count:
                num = count['counter']
            else:
                num = 0
            db.action('DELETE from downloads')
        finally:
            db.close()
        logger.debug(f'Deleted download counter for {num} {plural(num, "provider")}')
        return i18n.ngettext('Deleted download counter for %(count)s provider',
                             'Deleted download counter for %(count)s providers', num) % {'count': num}

    @cherrypy.expose
    @require_auth()
    def showdownloads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        # show provider download totals
        result = ''
        db = database.DBConnection()
        try:
            downloads = db.select('SELECT Count,Provider FROM downloads ORDER BY Count DESC')
        finally:
            db.close()
        for line in downloads:
            provname = CONFIG.disp_name(line['Provider'].strip('/'))
            new_entry = f"{line['Count']:4d} - {provname}\n"
            result += new_entry

        if result == '':
            result = i18n.gettext('No downloads')
        return result

    @cherrypy.expose
    @require_auth()
    def sync_to_calibre(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'CalSync' in [n.name for n in list(threading.enumerate())]:
            msg = i18n.gettext('Calibre Sync is already running')
        else:
            self.label_thread('CalSync')
            userid = owner_id()
            if userid:
                msg = sync_calibre_list(userid=userid)
                self.label_thread('WEBSERVER')
            else:
                msg = i18n.gettext("No userid found")
        return msg

    @cherrypy.expose
    @require_auth()
    def sync_to_hardcover(self, confirmed=False, readonly=False, ignore=False):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('WEB-HCSYNC')
        # Convert string parameters to boolean
        if isinstance(confirmed, str):
            confirmed = confirmed.lower() in ('true', '1', 'yes')
        if isinstance(readonly, str):
            readonly = readonly.lower() in ('true', '1', 'yes')
        if isinstance(ignore, str):
            ignore = ignore.lower() in ('true', '1', 'yes')
        # If ignore is True, set readonly to True to prevent sending updates to HC
        if ignore:
            readonly = True
        msg = hc.hc_sync(library='', userid=None, confirmed=confirmed, readonly=readonly)
        self.label_thread('WEBSERVER')
        return msg

    @cherrypy.expose
    @require_auth()
    def sync_to_goodreads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('WEB-GRSYNC')
        msg = grsync.sync_to_gr()
        self.label_thread('WEBSERVER')
        return msg

    # API ###############################################################

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def ping(self):
        """ Health check for Docker and monitoring tools, like Sonarr's /ping. It needs no
        login, so it only says whether LazyLibrarian is up and can read its database """
        db = database.DBConnection()
        try:
            db.match('SELECT 1')
        except Exception:
            cherrypy.response.status = 503
            return {'status': 'Error'}
        finally:
            db.close()
        return {'status': 'OK'}

    @cherrypy.expose
    def api(self, **kwargs):
        from lazylibrarian.api import Api
        a = Api()
        # noinspection PyArgumentList
        a.check_params(**kwargs)
        return a.fetch_data

    # ALL ELSE ##########################################################

    @cherrypy.expose
    @require_auth()
    def force_process(self, source=None):
        logger = logging.getLogger(__name__)
        if 'POSTPROCESSOR' not in [n.name for n in list(threading.enumerate())]:
            threading.Thread(target=process_dir, name='POSTPROCESSOR', args=[True]).start()
            schedule_job(action=SchedulerCommand.RESTART, target='PostProcessor')
        else:
            logger.debug('POSTPROCESSOR already running')
        if self.valid_source(source):
            raise cherrypy.HTTPRedirect(source)
        raise cherrypy.HTTPRedirect('index')

    @cherrypy.expose
    @require_auth()
    def force_wish(self, source=None):
        logger = logging.getLogger(__name__)
        if CONFIG.use_wishlist():
            search_wishlist()
        else:
            logger.warning('WishList search called but no wishlist providers set')
        if self.valid_source(source):
            raise cherrypy.HTTPRedirect(source)
        raise cherrypy.HTTPRedirect('index')

    @cherrypy.expose
    @require_auth()
    def force_search(self, source=None, title=None):
        self.validate_param("search title", title, ['<', '>', '='], 404)
        logger = logging.getLogger(__name__)
        if source in ["magazines", 'comics']:
            if CONFIG.use_any():
                if title:
                    title = title.replace('&amp;', '&')
                    if source == 'magazines':
                        self.search_for_mag(bookid=title)
                    elif source == 'comics':
                        self.search_for_comic(comicid=title)
                elif source == 'magazines' and 'SEARCHALLMAG' not in [
                        n.name for n in list(threading.enumerate())]:
                    threading.Thread(target=search_magazines, name='SEARCHALLMAG', args=[]).start()
                    schedule_job(action=SchedulerCommand.RESTART, target='search_magazines')
                elif source == 'comics' and 'SEARCHALLCOMICS' not in [
                        n.name for n in list(threading.enumerate())]:
                    threading.Thread(target=search_comics, name='SEARCHALLCOMICS', args=[]).start()
                    schedule_job(action=SchedulerCommand.RESTART, target='search_comics')
            else:
                logger.warning('Search called but no download providers set')
        elif source in ["books", "audio"]:
            if CONFIG.use_any():
                if 'SEARCHALLBOOKS' not in [n.name for n in list(threading.enumerate())]:
                    schedule_job(SchedulerCommand.STOP, "search_book")
                    schedule_job(SchedulerCommand.STARTNOW, "search_book")
                if CONFIG.use_rss():
                    schedule_job(SchedulerCommand.STOP, "search_rss_book")
                    schedule_job(SchedulerCommand.STARTNOW, "search_rss_book")
            else:
                logger.warning('Search called but no download providers set')

        if not self.valid_source(source):
            raise cherrypy.HTTPRedirect('index')
        raise cherrypy.HTTPRedirect(source)

    @cherrypy.expose
    def opds(self, **kwargs):
        self.label_thread('OPDS Server')
        op = OPDS()
        op.check_params(**kwargs)
        data = op.fetch_data()
        return data
