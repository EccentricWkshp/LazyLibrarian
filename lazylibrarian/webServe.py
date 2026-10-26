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
import time
import traceback
import uuid
from shutil import copyfile, rmtree
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit

import cherrypy
from cherrypy.lib.static import serve_file
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import (
    ROLE,
    comicscan,
    database,
    grsync,
    hc,
    i18n,
    magazinescan,
    notifiers,
    versioncheck,
)
from lazylibrarian.auth import AuthController, owner_id, require_auth
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.bookrename import name_vars
from lazylibrarian.bookwork import delete_empty_series, language_from_words, set_series
from lazylibrarian.cache import ImageType, cache_img, gr_xml_request
from lazylibrarian.calibre import calibredb, get_calibre_id, sync_calibre_list
from lazylibrarian.calibre_integration import send_mag_issue_to_calibre
from lazylibrarian.comicid import cv_identify, cx_identify, name_words, title_words
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.common import (
    create_support_zip,
    get_readinglist,
    is_valid_language,
    log_header,
    mime_type,
    set_readinglist,
    zip_audio,
)
from lazylibrarian.config2 import CONFIG
from lazylibrarian.csvfile import export_csv, import_csv
from lazylibrarian.download_client import get_download_progress
from lazylibrarian.downloadmethods import (
    direct_dl_method,
    irc_dl_method,
    nzb_dl_method,
    tor_dl_method,
)
from lazylibrarian.filesystem import (
    DIRS,
    book_file,
    csv_file,
    listdir,
    opf_file,
    path_exists,
    path_isdir,
    path_isfile,
    remove_file,
    safe_copy,
    safe_move,
    setperm,
    splitext,
    syspath,
)
from lazylibrarian.formatter import (
    check_float,
    check_int,
    check_year,
    clean_name,
    date_format,
    get_list,
    make_unicode,
    now,
    plural,
    replace_all,
    sort_definite,
    strip_quotes,
    surname_first,
    thread_name,
    today,
    unaccented,
)
from lazylibrarian.images import (
    coverswap,
    create_mag_cover,
    createthumb,
    get_book_cover,
    read_pdf_tags,
    write_pdf_tags,
)
from lazylibrarian.importer import add_author_to_db, update_totals
from lazylibrarian.librarysync import library_scan
from lazylibrarian.logconfig import LOGCONFIG
from lazylibrarian.magazinescan import get_dateparts, magazine_scan, remove_if_empty, rename_issue
from lazylibrarian.manual_import import process_alternate, process_book_from_dir, process_issues
from lazylibrarian.manualbook import search_item
from lazylibrarian.metadata_opf import create_opf
from lazylibrarian.notifiers import custom_notify_snatch, notify_snatch
from lazylibrarian.oldump import update_openlibrary_dump
from lazylibrarian.opds import OPDS
from lazylibrarian.opfedit import opf_read, opf_write
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
from lazylibrarian.searchbook import search_book
from lazylibrarian.searchmag import download_maglist, search_magazines
from lazylibrarian.searchrss import search_wishlist
from lazylibrarian.web import common
from lazylibrarian.web.authors import AuthorPages
from lazylibrarian.web.common import (
    BasePages,
    fold,
    mark_summary,
    serve_template,
    status_mark_targets,
)
from lazylibrarian.web.connection_tests import ConnectionTestPages
from lazylibrarian.web.series import SeriesPages
from lazylibrarian.web.settings import SettingsPages
from lazylibrarian.web.users import UserPages

lastmagazine = ''
lastcomic = ''


def refresh_book_languages():
    """ Background job: re-evaluates language for books in the database.
    Corrects short-title false positives (e.g. English titles misidentified as German/French/Spanish),
    normalizes English dialects (e.g. en-CA), resolves 'Unknown' languages, and automatically
    un-ignores books that were falsely marked Ignored due to invalid language. """
    logger = logging.getLogger(__name__)
    incoming_threadname = thread_name()
    thread_name('LANGREFRESH')

    def stop_requested():
        return lazylibrarian.STOPTHREADS and thread_name() == 'LANGREFRESH'

    db = database.DBConnection()
    try:
        db.upsert("jobs", {"Start": time.time()}, {"Name": "LANGREFRESH"})
        rows = db.select(
            "SELECT BookID, BookName, BookLang, BookDesc, Status, ScanResult, AuthorID FROM books "
            "WHERE (Status = 'Ignored' AND ScanResult LIKE '%Invalid language%') "
            "OR BookLang = 'Unknown' OR BookLang IS NULL OR BookLang = '' "
            "OR BookLang NOT IN ('en', 'eng', 'en-US', 'en-GB')"
        )
        total = len(rows)
        lazylibrarian.LANG_REFRESH_STATUS = {'checked': 0, 'updated': 0, 'unignored': 0, 'total': total}
        logger.info(f"Language refresh: {total} candidate book{plural(total)} to check")

        valid_langs = get_list(CONFIG['IMP_PREFLANG'])
        checked = 0
        updated = 0
        unignored = 0
        authors_to_update = set()

        for row in rows:
            if stop_requested():
                logger.info(f"Language refresh: stopped after checking {checked}/{total}")
                break

            bookid = row['BookID']
            name = row['BookName'] or ''
            old_lang = row['BookLang'] or 'Unknown'
            desc = row['BookDesc'] or ''
            status = row['Status']
            scan_res = row['ScanResult'] or ''
            author_id = row['AuthorID']

            new_lang, conf = language_from_words(name, desc=desc)
            if new_lang and new_lang not in ['None', 'Disabled', 'Blocked'] and conf > 0.5:
                lang_to_set = new_lang
            else:
                lang_to_set = old_lang

            lang_changed = (lang_to_set != old_lang and lang_to_set != 'Unknown')
            was_ignored_for_lang = (status == 'Ignored' and 'Invalid language' in scan_res)
            is_valid_now = is_valid_language(lang_to_set, valid_langs)

            if lang_changed or (was_ignored_for_lang and is_valid_now):
                updates = {}
                if lang_changed:
                    updates['BookLang'] = lang_to_set
                if was_ignored_for_lang and is_valid_now:
                    new_status = CONFIG['NEWBOOK_STATUS'] if CONFIG['NEWBOOK_STATUS'] != 'Ignored' else 'Skipped'
                    updates['Status'] = new_status
                    updates['ScanResult'] = f"[LangRefresh] Restored: {old_lang} -> {lang_to_set}"
                    unignored += 1
                    if author_id:
                        authors_to_update.add(author_id)
                elif lang_changed and not was_ignored_for_lang:
                    updates['ScanResult'] = f"[LangRefresh] Language: {old_lang} -> {lang_to_set}"

                if updates:
                    set_clause = ', '.join(f"{k}=?" for k in updates.keys())
                    values = list(updates.values()) + [bookid]
                    db.action(f"UPDATE books SET {set_clause} WHERE BookID=?", values)
                    updated += 1

            checked += 1
            lazylibrarian.LANG_REFRESH_STATUS['checked'] = checked
            lazylibrarian.LANG_REFRESH_STATUS['updated'] = updated
            lazylibrarian.LANG_REFRESH_STATUS['unignored'] = unignored

            if checked % 250 == 0:
                db.commit()
                logger.info(f"Language refresh: checked {checked}/{total}, updated {updated}, restored {unignored}")

        db.commit()
        for auth_id in authors_to_update:
            with contextlib.suppress(Exception):
                lazylibrarian.importer.update_totals(auth_id)

        logger.info(f"Language refresh: complete, checked {checked}/{total}, updated {updated}, restored {unignored}")
    finally:
        db.upsert("jobs", {"Finish": time.time()}, {"Name": "LANGREFRESH"})
        db.close()
        thread_name(incoming_threadname)


# noinspection PyProtectedMember,PyGlobalUndefined,PyGlobalUndefined
class WebInterface(UserPages, SeriesPages, SettingsPages, ConnectionTestPages, AuthorPages, BasePages):
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

    @staticmethod
    def book_refresh_source_priority():
        """ Priority order for picking which single source to refresh a book from -
        author-linkable sources (INFOSOURCES's author_key, richer/more curated data)
        before book-search-only ones (GoogleBooks/DNB/BN), each group in INFOSOURCES'
        own order. Every source implements the same add_bookid_to_db(bookid,
        bookstatus, audiostatus, reason) interface (see bookdict.py's docstring), so
        this can dispatch generically rather than needing per-source logic.
        Derived from lazylibrarian.INFOSOURCES at call time, not class-definition
        time - webServe is imported before startup.init_build_lists() populates
        INFOSOURCES. """
        author_linkable = [(name, src['book_key']) for name, src in lazylibrarian.INFOSOURCES.items()
                           if src['author_key'] != 'authorid']
        book_only = [(name, src['book_key']) for name, src in lazylibrarian.INFOSOURCES.items()
                    if src['author_key'] == 'authorid']
        return author_linkable + book_only

    @cherrypy.expose
    @require_auth()
    def refresh_book(self, bookid):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        book = db.match("SELECT BookName,Manual,gr_id,ol_id,hc_id,ran_id,dnb_id,bn_id,dbk_id,gb_id FROM books WHERE BookID=?",
                        (bookid,))
        db.close()
        if not book:
            raise cherrypy.HTTPError(404, f"BookID {bookid} not found")
        locked = book['Manual']
        if locked and str(locked).isdigit():
            locked = bool(int(locked))
        if locked:
            logger.debug(f"Not refreshing {bookid} ({book['BookName']}) - manually locked")
            raise cherrypy.HTTPRedirect(f"book_detail?bookid={bookid}")
        # Deliberately only ever calls ONE source, not all of a book's linked sources -
        # unlike get_all_author_details(), there's no merge-multiple-sources logic at
        # the book level yet, so calling a second source after the first would just
        # overwrite the first source's fields wholesale rather than filling gaps.
        for source_name, id_col in self.book_refresh_source_priority():
            source_id = book[id_col]
            if source_id:
                api = lazylibrarian.INFOSOURCES[source_name]['api']()
                threading.Thread(target=api.add_bookid_to_db, name=f"REFRESHBOOK_{bookid}",
                                 kwargs={'bookid': source_id,
                                         'reason': f"WebServer refresh_book {bookid} via {source_name}"}).start()
                break
        else:
            logger.debug(f"Not refreshing {bookid} ({book['BookName']}) - no linked source id")
        raise cherrypy.HTTPRedirect(f"book_detail?bookid={bookid}")

    # BOOKS #############################################################

    @cherrypy.expose
    @require_auth()
    def booksearch(self, author=None, title=None, bookid=None, action=''):
        self.label_thread('BOOKSEARCH')
        if '_title' in action:
            searchterm = title
        elif '_author' in action:
            searchterm = author
        else:  # if '_full' in action: or legacy interface
            searchterm = f'{author} {title}'
            searchterm = searchterm.strip()

        if action.startswith('e_'):
            cat = 'book'
        elif action.startswith('a_'):
            cat = 'audio'
        elif action:
            cat = 'general'
        else:  # legacy interface
            cat = 'book'

        results = search_item(searchterm, bookid, cat)
        library = 'eBook'
        if action.startswith('a_'):
            library = 'AudioBook'
        return serve_template(templatename="manualsearch.html", title=i18n.gettext('%(library)s Search Results: "%(query)s"') % {
                                  'library': i18n.status_label(library), 'query': searchterm}, bookid=bookid, results=results, library=library)

    @cherrypy.expose
    @require_auth()
    def count_providers(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        count = CONFIG.total_active_providers()
        return f"Searching {count} providers, please wait..."

    @cherrypy.expose
    @require_auth()
    def snatch_book(self, bookid=None, mode=None, provider=None, url=None, size=None, library=None, title=''):
        logger = logging.getLogger(__name__)
        logger.debug(f"snatch {library} bookid {bookid} mode={mode} from {provider} url=[{url}] {title}")
        db = database.DBConnection()
        bookdata = db.match('SELECT AuthorID, BookName from books WHERE BookID=?', (bookid,))
        if bookdata:
            size_temp = check_int(size, 1000)  # Need to cater for when this is NONE (Issue 35)
            size = round(float(size_temp) / 1048576, 2)
            control_value_dict = {"NZBurl": url}
            new_value_dict = {
                "NZBprov": provider,
                "BookID": bookid,
                "NZBdate": now(),  # when we asked for it
                "NZBsize": size,
                "NZBtitle": bookdata["BookName"],
                "NZBmode": mode,
                "AuxInfo": library,
                "Status": "Snatched"
            }
            db.upsert("wanted", new_value_dict, control_value_dict)
            author_id = bookdata["AuthorID"]
            dl_title = bookdata["BookName"]
            if provider in ['soulseek', 'annas', 'webshare']:
                dl_title = title
            if mode == 'direct':
                snatch, res = direct_dl_method(bookid, dl_title, url, library, provider)
            elif mode in ["torznab", "torrent", "magnet"]:
                snatch, res = tor_dl_method(bookid, bookdata["BookName"], url, library, provider=provider)
            elif mode == 'nzb':
                snatch, res = nzb_dl_method(bookid, bookdata["BookName"], url, library)
            elif mode == 'irc':
                if title:
                    snatch, res = irc_dl_method(bookid, title, url, library, provider)
                else:
                    snatch, res = irc_dl_method(bookid, bookdata["BookName"], url, library, provider)
            else:
                res = f'Unhandled NZBmode [{mode}] for {url}'
                logger.error(res)
                snatch = False
            if snatch:
                logger.info(f'Requested {library} {bookdata["BookName"]} from {provider}')
                custom_notify_snatch(f"{bookid} {library}")
                notify_snatch(
                    f"{unaccented(bookdata['BookName'], only_ascii=False)} from "
                    f"{CONFIG.disp_name(provider)} at {now()}")
                schedule_job(action=SchedulerCommand.START, target='PostProcessor')
            else:
                db.action("UPDATE wanted SET status='Failed',DLResult=? WHERE NZBurl=?", (res, url))
            db.close()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}&library={library}")
        logger.debug(f'snatch_book Invalid bookid [{bookid}]')
        db.close()
        raise cherrypy.HTTPError(404, f"BookID {bookid} not found")

    @cherrypy.expose
    @require_auth()
    def audio(self, booklang=None, book_filter=''):
        user = 0
        email = ''
        db = database.DBConnection()
        try:
            user = owner_id()
            if user:
                res = db.match('SELECT SendTo from users where UserID=?', (user,))
                if res and res['SendTo']:
                    email = res['SendTo']
            if not booklang or booklang == 'None':
                booklang = None
            languages = db.select(
                "SELECT DISTINCT BookLang from books WHERE AUDIOSTATUS !='Skipped' AND AUDIOSTATUS !='Ignored'")
        finally:
            db.close()
        return serve_template(templatename="audio.html", title=i18n.gettext('AudioBooks'), books=[],
                              languages=languages, booklang=booklang, user=user, email=email, book_filter=book_filter)

    @cherrypy.expose
    @require_auth()
    def books(self, booklang=None, book_filter=''):
        user = 0
        email = ''
        db = database.DBConnection()
        try:
            user = owner_id()
            if user:
                res = db.match('SELECT SendTo from users where UserID=?', (user,))
                if res and res['SendTo']:
                    email = res['SendTo']
            if not booklang or booklang == 'None':
                booklang = None
            languages = db.select("SELECT DISTINCT BookLang from books WHERE STATUS !='Skipped' AND STATUS !='Ignored'")
        finally:
            db.close()
        return serve_template(templatename="books.html", title=i18n.gettext('eBooks'), books=[],
                              languages=languages, booklang=booklang, user=user, email=email, book_filter=book_filter)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_books(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        rows = []
        filtered = []
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            to_read = set()
            have_read = set()
            reading = set()
            abandoned = set()
            flag_to = 0
            flag_have = 0
            userprefs = 0
            perm = lazylibrarian.perm_admin
            cookie = cherrypy.request.cookie
            if cookie and 'll_prefs' in list(cookie.keys()):
                userprefs = check_int(cookie['ll_prefs'].value, 0)
            userid = owner_id()
            if userid:
                to_read = get_readinglist("ToRead", userid)
                have_read = get_readinglist("HaveRead", userid)
                reading = get_readinglist("Reading", userid)
                abandoned = get_readinglist("Abandoned", userid)
                serversidelogger.debug(
                    f"get_books userid {userid} read {len(to_read)},{len(have_read)},"
                    f"{len(reading)},{len(abandoned)}")

            cmd = ("SELECT bookimg,authorname,bookname,bookrate,bookdate,books.status,books.bookid,booklang, "
                   "booksub,booklink,workpage,bookauthors.authorid,seriesdisplay,booklibrary,audiostatus,audiolibrary, "
                   "group_concat(series.seriesid || '~' || series.seriesname || ' #' || member.seriesnum, '^') "
                   "as series, bookgenre,bookadded,scanresult,lt_workid, "
                   "group_concat(series.seriesname || ' #' || member.seriesnum, '; ') as altsub "
                   "FROM books,authors,bookauthors "
                   "LEFT OUTER JOIN member ON (bookauthors.BookID = member.BookID and bookauthors.bookid=books.bookid) "
                   "LEFT OUTER JOIN series ON (member.SeriesID = series.SeriesID) "
                   "WHERE bookauthors.authorid=authors.authorid and bookauthors.bookid=books.bookid ")
            serversidelogger.debug(
                f"ToRead {len(to_read)} Read {len(have_read)} Reading {len(reading)} Abandoned {len(abandoned)}")
            types = []
            if CONFIG.get_bool('EBOOK_TAB'):
                types.append('eBook')
            if CONFIG.get_bool('AUDIO_TAB'):
                types.append('AudioBook')
            if types:
                library = types[0]
                if 'library' in kwargs and kwargs['library'] in types:
                    library = kwargs['library']
            else:
                library = None

            status_type = 'books.status'
            if library == 'AudioBook':
                status_type = 'audiostatus'
            args = []

            if kwargs['source'] == "Manage":
                if kwargs['whichStatus'] == 'ToRead':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in to_read) + ")"
                elif kwargs['whichStatus'] == 'Read':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in have_read) + ")"
                elif kwargs['whichStatus'] == 'Reading':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in reading) + ")"
                elif kwargs['whichStatus'] == 'Abandoned':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in abandoned) + ")"
                elif kwargs['whichStatus'] != 'All':
                    cmd += f" and {status_type}=?"
                    args.append(kwargs['whichStatus'])

            elif kwargs['source'] == "Books":
                cmd += " and books.STATUS !='Skipped' AND books.STATUS !='Ignored'"
            elif kwargs['source'] == "Audio":
                cmd += " and AUDIOSTATUS !='Skipped' AND AUDIOSTATUS !='Ignored'"
            elif kwargs['source'] == "Author":
                cmd += " and bookauthors.AuthorID=?"
                args.append(kwargs['AuthorID'])
                if 'ignored' in kwargs and kwargs['ignored'] == "True":
                    cmd += f" and {status_type}='Ignored'"
                else:
                    cmd += f" and {status_type} != 'Ignored'"

            if (kwargs['source'] in ["Books", "Author", "Audio"] and 'booklang' in kwargs and
                    kwargs['booklang'] != '' and kwargs['booklang'] != 'None'):
                # for these we need to check and filter on BookLang if set
                cmd += " and BOOKLANG=?"
                args.append(kwargs['booklang'])

            if kwargs['source'] in ["Books", "Audio"] and userid and (userprefs & lazylibrarian.pref_myfeeds or
                                                                      userprefs & lazylibrarian.pref_myafeeds):
                serversidelogger.debug("Getting user booklist")
                mybooks = []
                res = db.select("SELECT WantID from subscribers WHERE Type='author' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} authors")
                for authorid in res:
                    bookids = db.select('SELECT BookID from bookauthors WHERE AuthorID=?', (authorid['WantID'],))
                    for bookid in bookids:
                        mybooks.append(bookid['BookID'])

                res = db.select("SELECT WantID from subscribers WHERE Type='series' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} series")
                for series in res:
                    sel = 'SELECT BookID from member,series WHERE series.seriesid=?'
                    sel += ' and member.seriesid=series.seriesid'
                    bookids = db.select(sel, (series['WantID'],))
                    for bookid in bookids:
                        mybooks.append(bookid['BookID'])

                res = db.select("SELECT WantID from subscribers WHERE Type='feed' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} feeds")
                for feed in res:
                    sel = "SELECT BookID from books WHERE instr(Requester, '?') > 0"
                    sel += "  or instr(AudioRequester, '?') > 0"
                    bookids = db.select(sel, (feed['WantID'], feed['WantID']))
                    for bookid in bookids:
                        mybooks.append(bookid['BookID'])

                mybooks = set(mybooks)
                serversidelogger.debug(f"User booklist length {len(mybooks)}")
                cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in mybooks) + ")"

            if kwargs['source'] in ["Author", "Books", "Audio"] and lazylibrarian.PRIMARY_AUTHORS:
                # only show book for primary author
                cmd += " and books.bookid in (SELECT bookid FROM bookauthors where bookauthors.authorid=authors.authorid "
                cmd += f"and books.bookid=bookauthors.bookid and role={ROLE['PRIMARY']})"

            cmd += (" GROUP BY bookimg, authorname, bookname, bookrate, bookdate, books.status, books.bookid, "
                    "booklang, booksub, booklink, workpage, bookauthors.authorid, booklibrary, audiostatus, "
                    "audiolibrary, bookgenre, bookadded, scanresult, lt_workid")

            serversidelogger.debug(f"get_books {cmd}: {str(args)}")
            rowlist = db.select(cmd, tuple(args))
            serversidelogger.debug(f"get_books selected {len(rowlist)}")

            if library is None:
                rowlist = []
            # At his point we want to sort and filter _before_ adding the html as it's much quicker
            # turn the sqlite rowlist into a list of lists
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)
                    for pos in [5, 14, 16]:
                        if entry[pos] is None:
                            entry[pos] = ""
                    if CONFIG.get_bool('SORT_SURNAME'):
                        entry[1] = surname_first(entry[1], postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
                    if CONFIG.get_bool('SORT_DEFINITE'):
                        entry[2] = sort_definite(entry[2], articles=get_list(CONFIG.get_csv('NAME_DEFINITE')))
                    rows.append(entry)  # add each rowlist to the masterlist
                serversidelogger.debug("get_books surname/definite completed")

                if sSearch:
                    serversidelogger.debug(f"filter [{sSearch}]")
                    if library is not None:
                        search_fields = ['AuthorName', 'BookName', 'BookDate', 'Status', 'BookID',
                                         'BookLang', 'BookSub', 'AuthorID', 'BookGenre',
                                         'ScanResult']
                        if library == 'AudioBook':
                            search_fields[3] = 'AudioStatus'

                        filtered = []
                        for row in rowlist:
                            _dict = dict(row)
                            for key in search_fields:
                                if _dict[key] and sSearch.lower() in _dict[key].lower():
                                    filtered.append(list(row))
                                    break
                    else:
                        q = fold(sSearch)
                        filtered = [x for x in rows if q in fold(x)]
                        # filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                # table headers and column headers do not match at this point
                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")
                if sortcolumn < 4:  # author, title
                    sortcolumn -= 1
                elif sortcolumn == 4:  # series
                    sortcolumn = -1
                elif sortcolumn == 8:  # status
                    if status_type == 'audiostatus':
                        sortcolumn = 14
                    else:
                        sortcolumn = 5
                elif sortcolumn == 7:  # added or listed
                    if kwargs['source'] == "Manage":
                        sortcolumn = 18
                    else:
                        if status_type == 'audiostatus':
                            sortcolumn = 15
                        else:
                            sortcolumn = 13
                else:  # rating, date
                    sortcolumn -= 2

                serversidelogger.debug(f"final sortcolumn {sortcolumn}")

                if sortcolumn in [12, 13, 15, 18]:  # series, dates
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                elif sortcolumn in [2]:  # title
                    filtered.sort(key=lambda y: y[sortcolumn].lower() if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")
                elif sortcolumn in [3]:  # stars
                    filtered.sort(key=lambda y: float(y[sortcolumn]) if y[sortcolumn] is not None else 0.0,
                                  reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

                # now add html to the ones we want to display
                data = []  # the masterlist to be filled with the html data
                for row in rows:
                    title = row[2]
                    if not title:
                        continue
                    worklink = ''
                    sitelink = ''
                    if CONFIG.get_bool('RATESTARS'):
                        bookrate = int(round(check_float(row[3], 0.0)))
                        if bookrate > 5:
                            bookrate = 5
                    else:
                        bookrate = row[3]

                    if row[20]:  # is there a librarything workid
                        worklink = '<a href="' + CONFIG['LT_URL'] + '/' + 'work/' + \
                                   row[20] + '"><small><i>LibraryThing</i></small></a>'
                    elif row[10]:  # is there a workpage link
                        worklink = '<a href="' + row[10] + '" ><small><i>LibraryThing</i></small></a>'
                    else:
                        row[10] = ''
                        row[20] = ''

                    editpage = '<a href="edit_book?bookid=' + row[6] + '&library=' + library + \
                        '"><small><i>' + i18n.gettext('Manual') + '</i></a>'

                    if not row[9]:
                        row[9] = ''
                    elif row[9].startswith('/works/OL'):
                        ref = CONFIG['OL_URL'] + row[9]
                        sitelink = f'<a href="{ref}"><small><i>OpenLibrary</i></small></a>'

                    elif 'goodreads' in row[9]:
                        sitelink = f'<a href="{row[9]}"><small><i>GoodReads</i></small></a>'
                    elif 'hardcover' in row[9]:
                        sitelink = f'<a href="{row[9]}"><small><i>HardCover</i></small></a>'
                    elif 'books.google.com' in row[9] or 'market.android.com' in row[9]:
                        sitelink = f'<a href="{row[9]}"><small><i>GoogleBooks</i></small></a>'

                    if row[8] and ' #' not in row[8] and row[8] != "None":  # is there a subtitle that's not series info
                        title = f'{title}<br><small><i>{row[8]}</i></small>'
                    # elif row[20]:  # series info
                    #     title = '%s<br><small><i>(%s)</i></small>' % (title, row[20])
                    title = title + '<br>' + sitelink + ' ' + worklink
                    bookgenre = row[17]

                    if perm & lazylibrarian.perm_edit:
                        title = title + ' ' + editpage

                    if CONFIG.get_bool('SHOW_GENRES') and bookgenre and bookgenre != 'Unknown':
                        arr = bookgenre.split(',')
                        genres = ''
                        for a in arr:
                            if kwargs['source'] == "Audio":
                                genres = genres + ' <a href=\'audio?book_filter=' + a.strip() + '\'">' + \
                                         a.strip() + '</a>'
                            elif kwargs['source'] == "Books":
                                genres = genres + ' <a href=\'books?book_filter=' + a.strip() + '\'">' + \
                                         a.strip() + '</a>'
                            elif kwargs['source'] in ["Author", "Manage"]:
                                genres = genres + ' <a href=\'author_page?authorid=' + row[11] + '&book_filter=' + \
                                         a.strip() + '\'">' + a.strip() + '</a>'
                            else:
                                genres + genres + ' ' + a.strip()
                        genres = genres.strip()
                        if genres:
                            title += ' [' + genres + ']'

                    if row[6] in to_read:
                        flag = '&nbsp;<i class="far fa-bookmark"></i>'
                        flag_to += 1
                    elif row[6] in have_read:
                        flag = '&nbsp;<i class="fas fa-bookmark"></i>'
                        flag_have += 1
                    elif row[6] in reading:
                        flag = '&nbsp;<i class="fas fa-play-circle"></i>'
                    elif row[6] in abandoned:
                        flag = '&nbsp;<i class="fas fa-ban"></i>'
                    else:
                        flag = ''

                    if status_type == 'audiostatus' and kwargs['source'] == 'Audio':
                        row[5] = row[14]
                        row[13] = row[15]

                    # Need to pass bookid and status twice for legacy as datatables modifies first one
                    thisrow = [row[6], row[0], row[1], title, row[12], bookrate,
                               date_format(row[4], context=row[6], datelang=CONFIG['DATE_LANG']),
                               row[5], row[11], row[6],
                               date_format(row[13], CONFIG['DATE_FORMAT'], context=row[6],
                                           datelang=CONFIG['DATE_LANG']),
                               row[5], row[16], flag]

                    if kwargs['source'] == "Manage":
                        cmd = "SELECT Time,Interval,Count from failedsearch WHERE Bookid=? AND Library='eBook'"
                        searches = db.match(cmd, (row[6],))
                        if searches:
                            thisrow.append(f"{searches['Count']}/{searches['Interval']}")
                            try:
                                thisrow.append(time.strftime("%d %b %Y", time.localtime(float(searches['Time']))))
                            except (ValueError, TypeError):
                                thisrow.append('')
                        else:
                            thisrow.append('0')
                            thisrow.append('')
                    elif kwargs['source'] == 'Author':
                        thisrow.append(row[14])
                        thisrow.append(date_format(row[15], CONFIG['DATE_FORMAT'], context=row[6],
                                                   datelang=CONFIG['DATE_LANG']))

                    thisrow.append(row[18])
                    thisrow.append(row[19])
                    data.append(thisrow)

                rows = data

            serversidelogger.debug(
                f"get_books {kwargs['source']} returning {displaystart} to {displaystart + displaylength}, "
                f"flagged {flag_to},{flag_have}")
            serversidelogger.debug(f"get_books filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")

        except Exception:
            logger.error(f'Unhandled exception in get_books: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  }
        if kwargs['source'] == 'Author':
            status = db.match("SELECT Status from authors WHERE authorid=?", (kwargs['AuthorID'],))
            mydict['loading'] = status['Status'] == 'Loading'
        elif kwargs['source'] == 'Books':
            mydict['loading'] = lazylibrarian.EBOOK_UPDATE
        elif kwargs['source'] == 'Audio':
            mydict['loading'] = lazylibrarian.AUDIO_UPDATE
        db.close()
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def add_book(self, bookid=None, authorid=None, library=None, source=None):
        logger = logging.getLogger(__name__)
        if library == 'eBook':
            ebook_status = "Wanted"
            audio_status = "Skipped"
        elif library == 'AudioBook':
            audio_status = "Wanted"
            ebook_status = "Skipped"
        elif library == 'Both':
            audio_status = "Wanted"
            ebook_status = "Wanted"
        else:
            if CONFIG.get_bool('AUDIO_TAB'):
                audio_status = "Wanted"
            else:
                audio_status = "Skipped"
            if CONFIG.get_bool('EBOOK_TAB'):
                ebook_status = "Wanted"
            else:
                ebook_status = "Skipped"

        author_id = ''
        db = database.DBConnection()
        match = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        if not match and authorid:
            _ = add_author_to_db(None, False, authorid, False, f'WebServer add_book {bookid}')
            match = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        if match:
            db.upsert("books", {'Status': ebook_status, 'AudioStatus': audio_status},
                      {'BookID': bookid})
            author_id = match['AuthorID']
            update_totals(author_id)
        else:
            if source:
                if source in lazylibrarian.INFOSOURCES:
                    this_source = lazylibrarian.INFOSOURCES[source]
                else:
                    logger.error(f"Invalid source {source} in add_book")
                    this_source = lazylibrarian.INFOSOURCES[CONFIG['BOOK_API']]
            else:
                this_source = lazylibrarian.INFOSOURCES[CONFIG['BOOK_API']]
            api = this_source['api']
            api = api()
            t = threading.Thread(target=api.add_bookid_to_db,
                                 name=f"{this_source['src']}-BOOK",
                                 args=[bookid, ebook_status, audio_status, "Added by user"])
            t.start()
            t.join(timeout=10)  # 10 s to add book before redirect
        db.close()

        if CONFIG.get_bool('IMP_AUTOSEARCH'):
            books = [{"bookid": bookid}]
            self.start_book_search(books)

        if author_id:
            raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}")
        if ebook_status == 'Wanted':
            raise cherrypy.HTTPRedirect("books")
        if audio_status == 'Wanted':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def start_book_search(self, books=None, library=None, force=False):
        logger = logging.getLogger(__name__)
        if books:
            if CONFIG.use_any():
                if force:
                    name = 'FORCE-SEARCHBOOK'
                else:
                    name = 'SEARCHBOOK'
                logger.debug("Starting search_book thread")
                threading.Thread(target=search_book, name=name, args=[books, library]).start()
                booktype = library
                if not booktype:
                    booktype = 'book'  # all types
                logger.debug(f"Searching for {booktype} with id: {books[0]['bookid']}")
            else:
                logger.warning("Not searching for book, no search methods set, check config.")
        else:
            logger.debug("BookSearch called with no books")

    @cherrypy.expose
    @require_auth()
    def search_for_book(self, bookid=None, library=None):
        author_id = ''
        db = database.DBConnection()
        try:
            bookdata = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        finally:
            db.close()
        if bookdata:
            author_id = bookdata["AuthorID"]

            # start searchthreads
            books = [{"bookid": bookid}]
            self.start_book_search(books, library=library, force=True)

        if author_id:
            raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def request_book(self, **kwargs):
        self.label_thread('REQUEST_BOOK')
        logger = logging.getLogger(__name__)
        prefix = ''
        sent = False
        title = i18n.gettext('Request Error')
        if owner_id():
            db = database.DBConnection()
            res = db.match('SELECT Name,UserName,UserID,Email from users where UserID=?', (owner_id(),))
            if res:
                cmd = ("SELECT BookFile,AudioFile,AuthorName,BookName from books,authors WHERE BookID=? and "
                       "books.AuthorID = authors.AuthorID")
                bookdata = db.match(cmd, (kwargs['bookid'],))
                kwargs.update(bookdata)
                kwargs.update(res)
                kwargs.update({'message': 'Request to Download'})

                remote_ip = cherrypy.request.remote.ip
                msg = f'IP: {remote_ip}\n'
                for itm in kwargs:
                    if kwargs[itm]:
                        line = f"{itm}: {unaccented(kwargs[itm], only_ascii=False)}\n"
                    else:
                        line = f"{itm}: \n"
                    msg += line

                types = []
                if CONFIG.get_bool('EBOOK_TAB'):
                    types.append('eBook')
                if CONFIG.get_bool('AUDIO_TAB'):
                    types.append('AudioBook')

                booktype = 'book'
                if types and 'library' in kwargs and kwargs['library'] in types:
                    booktype = kwargs['library']

                title = f"{i18n.status_label(booktype)}: {bookdata['BookName']}"

                if 'Email' in kwargs and kwargs['Email']:
                    result = notifiers.email_notifier.notify_message('Request from LazyLibrarian User',
                                                                     msg, CONFIG['ADMIN_EMAIL'])
                    if result:
                        sent = True
                        prefix = i18n.gettext("Message sent")
                        msg = i18n.gettext("You will receive a reply by email")
                    else:
                        logger.error(f"Unable to send message to: {msg}")
                        prefix = i18n.gettext("Message not sent")
                        msg = i18n.gettext("Please try again later")
                else:
                    prefix = i18n.gettext("Unable to send message")
                    msg = i18n.gettext("No email address supplied")
            else:
                msg = i18n.gettext("Unknown user")
            db.close()
        else:
            msg = i18n.gettext("Nobody logged in?")

        if sent:
            timer = 5
        else:
            timer = 0
        return serve_template(templatename="response.html", prefix=prefix,
                              title=title, message=msg, timer=timer)

    @cherrypy.expose
    @require_auth()
    def serve_comic(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Comic [{feedid}]")
        return self.serve_item(feedid, "comic")

    @cherrypy.expose
    @require_auth()
    def serve_img(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Image [{feedid}]")
        return self.serve_item(feedid, "img")

    @cherrypy.expose
    @require_auth()
    def serve_book(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Book [{feedid}]")
        return self.serve_item(feedid, "book")

    @cherrypy.expose
    @require_auth()
    def serve_audio(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Audio [{feedid}]")
        return self.serve_item(feedid, "audio")

    @cherrypy.expose
    @require_auth()
    def serve_issue(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Issue [{feedid}]")
        return self.serve_item(feedid, "issue")

    @cherrypy.expose
    @require_auth()
    def serve_item(self, feedid, ftype):
        logger = logging.getLogger(__name__)
        userid = feedid[:10]
        itemid = feedid[10:]
        itemid = itemid.split('.')[0]  # discard any extension
        if len(userid) != 10:
            logger.debug(f"Invalid userID [{userid}]")
            return None

        target = ''

        size = re.search(r'_w\d+$', itemid)
        if size:
            size = check_int(size.group()[2:], 0)
            itemid = itemid[:-5]
        else:
            size = 0

        db = database.DBConnection()
        res = db.match('SELECT UserName,Perms,BookType from users where UserID=?', (userid,))
        if res:
            perm = check_int(res['Perms'], 0)
            preftype = res['BookType']
        else:
            logger.debug(f"Invalid userID [{userid}]")
            return None

        if not perm & lazylibrarian.perm_download:
            logger.debug(f"Insufficient permissions for userID [{userid}]")
            return None

        if ftype == 'img':
            if itemid:
                res = db.match('SELECT BookName,BookImg from books WHERE BookID=?', (itemid,))
                if res:
                    logger.debug(f"Itemid {itemid} matches ebook")
                    bookimg = res['BookImg']
                    if bookimg and bookimg.startswith('http'):
                        # external URL (set by e.g. googlebooks import) - cache it,
                        # point the row at the cached file and serve that, instead
                        # of silently falling through to the app logo
                        link, ok, _ = cache_img(ImageType.BOOK, itemid, bookimg)
                        if ok:
                            db.action("UPDATE books SET BookImg=? WHERE BookID=?",
                                      (link, itemid))
                            logger.info(f"Cached external cover for {itemid} from {bookimg}")
                            bookimg = link
                    if size:
                        target = createthumb(os.path.join(DIRS.DATADIR, bookimg), size, False)
                    if not target:
                        target = os.path.join(DIRS.DATADIR, bookimg)
                    if path_isfile(target):
                        return self.send_file(target, name=res['BookName'] + splitext(bookimg)[1])
                else:
                    res = db.match('SELECT Title,Cover from issues WHERE IssueID=?', (itemid,))
                    if res:
                        logger.debug(f"Itemid {itemid} matches issue")
                        if size:
                            target = createthumb(os.path.join(DIRS.DATADIR, res['Cover']), size, False)
                        if not target:
                            target = os.path.join(DIRS.DATADIR, res['Cover'])
                        if path_isfile(target):
                            return self.send_file(target, name=res['Title'] + splitext(res['Cover'])[1])
                    else:
                        try:
                            comicid, issueid = itemid.split('_')
                            cmd = ("SELECT Title,Cover from comics,comicissues WHERE "
                                   "comics.ComicID=comicissues.ComicID and comics.ComicID=? and IssueID=?")
                            res = db.match(cmd, (comicid, issueid))
                        except (IndexError, ValueError):
                            res = None
                        if res:
                            logger.debug(f"Itemid {itemid} matches comicid")
                            if size:
                                target = createthumb(os.path.join(DIRS.DATADIR, res['Cover']), size, False)
                            if not target:
                                target = os.path.join(DIRS.DATADIR, res['Cover'])
                            if path_isfile(target):
                                return self.send_file(target, name=res['Title'] + splitext(res['Cover'])[1])

            logger.debug(f"Itemid {itemid} no match")
            target = os.path.join(DIRS.PROG_DIR, 'data', 'images', 'll192.png')
            if path_isfile(target):
                return self.send_file(target, name='lazylibrarian.png')

        elif ftype == 'comic':
            try:
                comicid, issueid = itemid.split('_')
                cmd = ("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                       "and comics.ComicID=? and IssueID=?")
                res = db.match(cmd, (comicid, issueid))
            except (IndexError, ValueError):
                res = None
                issueid = 0

            if res:
                target = res['IssueFile']
                if target and path_isfile(target):
                    logger.debug(f'Opening {ftype} {target}')
                    return self.send_file(target, name=f"{res['Title']} {issueid}{splitext(target)[1]}")

        elif ftype == 'audio':
            res = db.match('SELECT AudioFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                cnt = 0
                myfile = res['AudioFile']
                # count the audiobook parts
                if myfile and path_isfile(myfile):
                    parentdir = os.path.dirname(myfile)
                    for _, _, filenames in os.walk(parentdir):
                        for filename in filenames:
                            if CONFIG.is_valid_booktype(filename, 'audiobook'):
                                cnt += 1

                if cnt > 1 and not CONFIG.get_bool('RSS_PODCAST'):
                    target = zip_audio(os.path.dirname(myfile), res['BookName'], itemid)
                    if target and path_isfile(target):
                        logger.debug(f'Opening {ftype} {target}')
                        return self.send_file(target, name=res['BookName'] + '.zip')

                if myfile and path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile)

        elif ftype == 'book':
            res = db.match('SELECT BookFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                myfile = res['BookFile']
                fname, extn = splitext(myfile)
                types = []
                for itm in get_list(CONFIG['EBOOK_TYPE']):
                    target = fname + '.' + itm
                    if path_isfile(target):
                        types.append(itm)

                # serve user preferred type if available, or system preferred type
                if preftype and preftype in types:
                    extn = preftype
                else:
                    extn = types[0]
                myfile = fname + '.' + extn
                if path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile)

        elif ftype == 'issue':
            res = db.match('SELECT Title,IssueFile from issues WHERE IssueID=?', (itemid,))
            if res:
                myfile = res['IssueFile']
                if myfile and path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile, name=f"{res['Title']} {itemid}{splitext(myfile)[1]}")
        db.close()
        logger.warning(f"No file found for {ftype} {itemid}")
        return None

    @cherrypy.expose
    @require_auth()
    def send_book(self, bookid=None, library=None, redirect=None, booktype=None):
        return self.open_book(bookid=bookid, library=library, redirect=redirect, booktype=booktype, email=True)

    @cherrypy.expose
    @require_auth()
    def open_book(self, bookid=None, library=None, redirect=None, booktype=None, email=False):
        logger = logging.getLogger(__name__)
        adminlogger = logging.getLogger('special.admin')
        adminlogger.debug(f"{bookid} {library} {redirect} {booktype} {email}")
        self.label_thread('OPEN_BOOK')
        # we need to check the user priveleges and see if they can download the book
        db = database.DBConnection()
        perm = lazylibrarian.perm_admin
        preftype = ''
        res = db.match('SELECT BookType from users where UserID=?', (owner_id(),))
        if res:
            preftype = res['BookType'] or ''

        if booktype is not None:
            preftype = booktype

        apisources = []
        for i in lazylibrarian.INFOSOURCES.keys():
            # source, authorid, bookid
            infosource = lazylibrarian.INFOSOURCES[i]
            apisources.append([infosource, infosource['author_key'], infosource['book_key']])

        bookid_key = 'BookID'
        for itm in apisources:
            if CONFIG['BOOK_API'] == itm[0]:
                bookid_key = itm[2]
                break

        cmd = (f"SELECT BookFile,AudioFile,AuthorName,BookName from books,authors WHERE books.{bookid_key}=? or "
               "BookID=? and books.AuthorID = authors.AuthorID")
        bookdata = db.match(cmd, (bookid, bookid))
        db.close()
        if not bookdata:
            logger.warning(f'Missing bookid: {bookid}')
        else:
            if perm & lazylibrarian.perm_download:
                author_name = bookdata["AuthorName"]
                book_name = bookdata["BookName"]
                if library == 'AudioBook':
                    bookfile = bookdata["AudioFile"]
                    if bookfile and path_isfile(bookfile):
                        parentdir = os.path.dirname(bookfile)
                        namevars = name_vars(bookid)
                        singlename = namevars['AudioSingleFile']
                        singlefile = ''
                        # noinspection PyBroadException
                        try:
                            for fname in listdir(parentdir):
                                if CONFIG.is_valid_booktype(fname, booktype='audio'):
                                    bname, extn = splitext(fname)
                                    if bname == singlename:
                                        # found name matching the AudioSingleFile
                                        singlefile = os.path.join(parentdir, fname)
                                        break
                        except Exception:
                            pass

                        if booktype == 'whole' and singlefile and path_isfile(singlefile):
                            if email:
                                logger.debug(f'Emailing {library} {singlefile}')
                            else:
                                logger.debug(f'Opening {library} {singlefile}')
                            return self.send_file(singlefile, name=os.path.basename(singlefile), email=email)

                        index = os.path.join(parentdir, 'playlist.ll')
                        if path_isfile(index):
                            if booktype == 'zip':
                                zipfile = zip_audio(parentdir, book_name, bookid)
                                if zipfile and path_isfile(zipfile):
                                    if email:
                                        logger.debug(f'Emailing {library} {zipfile}')
                                    else:
                                        logger.debug(f'Opening {library} {zipfile}')
                                    return self.send_file(zipfile, name=f'{book_name}.zip', email=email)
                            idx = check_int(booktype, 0)
                            if idx:
                                with open(syspath(index)) as f:
                                    part = f.read().splitlines()[idx - 1]
                                bookfile = os.path.join(parentdir, part)
                                if bookfile and path_isfile(bookfile):
                                    if email:
                                        logger.debug(f'Emailing {library} {bookfile}')
                                    else:
                                        logger.debug(f'Opening {library} {bookfile}')
                                    return self.send_file(bookfile, name=f"{book_name} "
                                                                         f"part{idx}{splitext(bookfile)[1]}",
                                                          email=email)
                            with open(index) as fp:
                                cnt = sum(1 for _ in fp)
                            if cnt <= 1:
                                if email:
                                    logger.debug(f'Emailing {library} {bookfile}')
                                else:
                                    logger.debug(f'Opening {library} {bookfile}')
                                return self.send_file(bookfile, email=email)
                            if email:
                                msg = i18n.gettext("Please select which part to email")
                            else:
                                msg = i18n.gettext("Please select which part to download")
                            itm = 1
                            partlist = ''
                            while itm <= cnt:
                                if partlist:
                                    partlist += ' '
                                partlist += str(itm)
                                itm += 1
                                partlist += ' zip'
                                if singlefile and path_isfile(singlefile):
                                    partlist += ' whole'
                            safetitle = book_name.replace('&', '&amp;').replace("'", "")

                            return serve_template(templatename="choosetype.html",
                                                  title=safetitle, pop_message=msg,
                                                  pop_types=partlist, bookid=bookid,
                                                  valid=get_list(partlist.replace(' ', ',')),
                                                  email=email)
                        if email:
                            logger.debug(f'Emailing {library} {bookfile}')
                        else:
                            logger.debug(f'Opening {library} {bookfile}')
                        return self.send_file(bookfile, email=email)

                library = 'eBook'
                bookfile = bookdata["BookFile"]
                if bookfile and path_isfile(bookfile):
                    fname, _ = splitext(bookfile)
                    types = []
                    for itm in get_list(CONFIG['EBOOK_TYPE']):
                        target = fname + '.' + itm
                        if path_isfile(target):
                            types.append(itm)
                    logger.debug(f'Preftype:{preftype} Available:{str(types)}')
                    if preftype and len(types):
                        if preftype in types:
                            bookfile = fname + '.' + preftype
                        else:
                            msg = f"{book_name}<br> "
                            typestr = ''
                            for itm in types:
                                if typestr:
                                    typestr += ' '
                                typestr += itm
                            msg += i18n.gettext("Not available as %(type)s, only %(types)s") % {
                                'type': preftype, 'types': typestr}
                            return serve_template(templatename="choosetype.html",
                                                  title=i18n.gettext("Not Available"), pop_message=msg,
                                                  pop_types=typestr, bookid=bookid,
                                                  valid=get_list(CONFIG['EBOOK_TYPE']),
                                                  email=email)
                    elif len(types) > 1:
                        if email:
                            msg = i18n.gettext("Please select format to email")
                        else:
                            msg = i18n.gettext("Please select format to download")
                        typestr = ''
                        for itm in types:
                            if typestr:
                                typestr += ' '
                            typestr += itm
                        return serve_template(templatename="choosetype.html",
                                              title=i18n.gettext("Choose Type"), pop_message=msg,
                                              pop_types=typestr, bookid=bookid,
                                              valid=get_list(CONFIG['EBOOK_TYPE']),
                                              email=email)
                    if len(types) and bookfile and path_isfile(bookfile):
                        if email:
                            logger.debug(f'Emailing {library} {bookfile}')
                            return self.send_file(bookfile, name=book_name, email=email)
                        logger.debug(f'Opening {library} {bookfile}')
                        return self.send_file(bookfile, email=email)
                    logger.debug(f'Unable to send {library} {book_name}, no valid types?')

                logger.info(f'Missing {library} {author_name}, {book_name} [{bookfile}]')
                if library == 'AudioBook':
                    raise cherrypy.HTTPRedirect("audio")
                raise cherrypy.HTTPRedirect("books")
            return self.request_book(library=library, bookid=bookid, redirect=redirect)

        if library == 'AudioBook':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def book_detail(self, bookid=None):
        """ Read-only "master" detail view for a book, replacing the old bookinfo()
        popup (which only ever showed image/title/description via bookdesc) for plain
        book ids - see base.html's bookinfo() for the author/comic cases, unchanged. """
        db = database.DBConnection()
        book = db.match("SELECT books.*, AuthorName from books,authors WHERE "
                        "books.AuthorID=authors.AuthorID AND BookID=?", (bookid,))
        db.close()
        if not book:
            raise cherrypy.HTTPRedirect("books")
        book = dict(book)

        book['BookDate'] = date_format(book['BookDate'], CONFIG['AUTHOR_DATE_FORMAT'],
                                       context=book['BookName'], datelang=CONFIG['DATE_LANG'])
        book['OriginalPubDate'] = date_format(book['OriginalPubDate'], CONFIG['AUTHOR_DATE_FORMAT'],
                                              context=book['BookName'], datelang=CONFIG['DATE_LANG'])

        # Book-level source ids resolve to working pages via simple templates (unlike
        # author ids, which need a live API call) - stored as INFOSOURCES['link_template'],
        # only present for sources verified live against real ids from this library:
        # GoodReads bare id (no title slug) 200s, OpenLibrary work id 301s, Google Books
        # volume id 302s, DNB id 302s. HardCover/RanobeDB have no verified template and
        # ~0 usage in this library's book records, so shown as plain ids (no link_template
        # key) rather than guessed (possibly wrong) links.
        book_links = []
        for src in lazylibrarian.INFOSOURCES.values():
            col = src['book_key']
            if book.get(col):
                template = src.get('link_template')
                link = template.format(book[col]) if template else ''
                book_links.append((col, book[col], link))

        amazon_link = f'https://www.amazon.com/dp/{book["ASIN"]}' if book.get('ASIN') else ''

        return serve_template(templatename="book_detail.html", title=book['BookName'], book=book,
                              book_links=book_links, amazon_link=amazon_link)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def lookup_book_asin(self, bookid=None):
        """ AJAX: on-demand fetch of a book's ASIN from GoodReads' single-book endpoint
        (book/show/{id}.xml - has asin/kindle_asin; the bulk author-book-list endpoint
        used during normal refresh doesn't, so this can't be backfilled for free the way
        author source links were - see gr.py's add_bookid_to_db). Not run automatically
        for every book, only when the detail page is actually viewed and asks for it. """
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        book = db.match("SELECT gr_id from books WHERE BookID=?", (bookid,))
        if not book or not book['gr_id']:
            db.close()
            return {'error': 'No GoodReads id linked to this book'}
        api = lazylibrarian.INFOSOURCES['GoodReads']['api']()
        try:
            url = '/'.join([CONFIG['GR_URL'], f"book/show/{book['gr_id']}.xml?{urlencode(api.params)}"])
            rootxml, _ = gr_xml_request(url)
        except Exception as e:
            logger.error(f"lookup_book_asin error for book {bookid}: {e}")
            db.close()
            return {'error': 'Lookup failed, check the logs'}
        asin = ''
        if rootxml is not None:
            book_el = rootxml.find('book')
            if book_el is not None:
                asin_el = book_el.find('asin')
                asin = asin_el.text if asin_el is not None and asin_el.text else ''
                if not asin:
                    kasin_el = book_el.find('kindle_asin')
                    asin = kasin_el.text if kasin_el is not None and kasin_el.text else ''
        if not asin:
            db.close()
            return {'found': False}
        db.action('UPDATE books SET ASIN=? WHERE BookID=?', (asin, bookid))
        db.close()
        return {'found': True, 'asin': asin, 'link': f'https://www.amazon.com/dp/{asin}'}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def force_language_refresh(self):
        """ AJAX: kick off refresh_book_languages() in the background to re-evaluate
        languages across candidate books in the database. """
        logger = logging.getLogger(__name__)
        if 'LANGREFRESH' in [n.name for n in list(threading.enumerate())]:
            return {'error': 'Language refresh is already running'}
        threading.Thread(target=refresh_book_languages, name='LANGREFRESH', args=[]).start()
        logger.info("Manually triggered book language refresh")
        return {'success': True}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def language_refresh_status(self):
        """ AJAX: is a language refresh currently running, and progress counters. """
        running = 'LANGREFRESH' in [n.name for n in list(threading.enumerate())]
        return {
            'running': running,
            'checked': lazylibrarian.LANG_REFRESH_STATUS.get('checked', 0),
            'updated': lazylibrarian.LANG_REFRESH_STATUS.get('updated', 0),
            'unignored': lazylibrarian.LANG_REFRESH_STATUS.get('unignored', 0),
            'total': lazylibrarian.LANG_REFRESH_STATUS.get('total', 0),
        }

    @cherrypy.expose
    @require_auth()
    def edit_book(self, bookid=None, library='eBook', images=False):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        self.label_thread('EDIT_BOOK')
        db = database.DBConnection()
        authors = db.select(
            "SELECT AuthorName from authors WHERE Status !='Ignored' ORDER by AuthorName COLLATE NOCASE")
        cmd = ("SELECT BookName,BookID,BookSub,BookGenre,BookLang,BookDesc,books.Manual,AuthorName,books.AuthorID,"
               "BookDate,ScanResult,BookAdded,BookIsbn,WorkID,LT_WorkID,Narrator,BookFile,books.gr_id,"
               "books.gb_id,books.ol_id, books.hc_id from books,authors WHERE books.AuthorID = authors.AuthorID"
               " and BookID=?")
        bookdata = db.match(cmd, (bookid,))
        cmd = "SELECT SeriesName, SeriesNum from member,series where series.SeriesID=member.SeriesID and BookID=?"
        seriesdict = db.select(cmd, (bookid,))
        if bookdata:
            cmd = ("SELECT SeriesName from series,seriesauthors WHERE series.seriesid = seriesauthors.seriesid and "
                   "authorid=? ORDER by SeriesName COLLATE NOCASE")
            series = db.select(cmd, (bookdata['AuthorID'],))
        else:
            series = db.select("SELECT SeriesName from series WHERE Status !='Ignored' "
                               "ORDER by SeriesName COLLATE NOCASE")
        db.close()
        if bookdata:
            bookdata = dict(bookdata)
            bookdata['library'] = library
            if library != "AudioBook":
                bookdata.pop('Narrator', None)
            covers = []
            if images:
                sources = ['current', 'cover', 'goodreads', 'librarything', 'openlibrary',
                           'googleisbn', 'bing', 'googleimage']
                if CONFIG['HC_API']:
                    sources.append('hardcover')
                for source in sources:
                    cover, _ = get_book_cover(bookid, source)
                    if cover:
                        covers.append([source, cover])

            bookfile = bookdata['BookFile']
            if bookfile and path_isfile(bookfile):
                opffile = opf_file(os.path.dirname(bookfile))
            else:
                opffile = ''
            if opffile and path_isfile(opffile):
                opf_template, replaces = opf_read(opffile)
                remove_file(opf_template)  # we don't need the template file yet
            else:
                replaces = []
            subs = []

            for itm in replaces:
                # remove ones that are duplicated in bookdata, don't want two fields editing the same item
                # can't modify replaces list while iterating so make a new list
                if itm[0] not in ['title', 'creator', 'ISBN', 'date', 'description']:
                    subs.append(itm)
            return serve_template(templatename="editbook.html", title=i18n.gettext("Edit Book"), config=bookdata,
                                  seriesdict=seriesdict, authors=authors, covers=covers, replaces=subs, series=series)
        logger.info(f'Missing book {bookid}')
        return None

    @cherrypy.expose
    @require_auth()
    def book_update(self, bookname='', bookid='', booksub='', bookgenre='', booklang='', bookdate='',
                    manual='0', authorname='', cover='', newid='', editordata='', bookisbn='', workid='',
                    **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        if bookid:
            db = database.DBConnection()
            try:
                scanresult = ''
                if kwargs.get('importfrom'):
                    source = kwargs['importfrom']
                    folder = ''
                    library = ''
                    if path_isfile(source):
                        folder = os.path.dirname(source)
                    elif path_isdir(source):
                        folder = source
                    if folder:
                        if book_file(folder, booktype='audiobook', config=CONFIG):
                            library = 'Audio'
                        elif book_file(folder, booktype='ebook', config=CONFIG):
                            library = 'eBook'
                    if library:
                        res = process_book_from_dir(folder, library, bookid)
                        if res:
                            scanresult = f'Imported manually from {folder}'
                        else:
                            logger.debug(f"Failed to import {bookid} from {source}")
                            raise cherrypy.HTTPRedirect(f"edit_book?bookid={bookid}")
                    else:
                        logger.debug(f"No {library} found in {source}")

                cmd = ("SELECT BookName,BookSub,BookGenre,BookLang,BookImg,BookDate,BookDesc,books.Manual,"
                       "AuthorName,books.AuthorID, BookIsbn, WorkID, ScanResult, BookFile from books,authors "
                       "WHERE books.AuthorID = authors.AuthorID and BookID=?")
                bookdata = db.match(cmd, (bookid,))
                if bookdata:
                    edited = ''
                    moved = False
                    if bookgenre == 'None':
                        bookgenre = ''
                    manual = bool(check_int(manual, 0))

                    if newid and bookid != newid:
                        cmd = ("SELECT BookName,Authorname from books,authors WHERE "
                               "books.AuthorID = authors.AuthorID and BookID=?")
                        match = db.match(cmd, (newid,))
                        if match:
                            logger.warning(
                                f"Cannot change bookid to {newid}, in use by {match['BookName']}/{match['AuthorName']}")
                        else:
                            logger.warning("Updating bookid is not supported yet")
                            # edited += "BookID "
                    if scanresult and bookdata['ScanResult'] != scanresult:
                        edited += "ScanResult "
                    if bookdata['BookName'] != bookname:
                        edited += "Title "
                    if bookdata['BookSub'] != booksub:
                        edited += "Subtitle "
                    if bookdata['BookDesc'] != editordata:
                        edited += "Description "
                    if bookdata['BookGenre'] != bookgenre:
                        edited += "Genre "
                    if bookdata['BookLang'] != booklang:
                        edited += "Language "
                    if bookdata['BookIsbn'] != bookisbn:
                        edited += "ISBN "
                    if bookdata['WorkID'] != workid:
                        edited += "WorkID "
                    if bookdata['BookDate'] != bookdate:
                        if bookdate == '0000':
                            edited += "Date "
                        else:
                            # sometimes get yyyy, sometimes yyyy-mm, sometimes yyyy-mm-dd
                            if len(bookdate) <= 4:  # eg 412 BC = -412 or 400 AD = 400
                                y = check_int(bookdate, default=0, positive=False)
                            elif len(bookdate) in [7, 10]:
                                y = check_year(bookdate[:4])
                                if y and len(bookdate) == 7:
                                    try:
                                        _ = datetime.date(int(bookdate[:4]), int(bookdate[5:7]), 1)
                                    except ValueError:
                                        y = 0
                                elif y and len(bookdate) == 10:
                                    try:
                                        _ = datetime.date(int(bookdate[:4]), int(bookdate[5:7]), int(bookdate[8:]))
                                    except ValueError:
                                        y = 0
                            else:
                                y = 0
                            if y:
                                edited += "Date "
                            else:
                                bookdate = bookdata["BookDate"]
                    if bool(check_int(bookdata['Manual'], 0)) != manual:
                        edited += "Manual "
                    if bookdata['AuthorName'] != authorname:
                        moved = True

                    covertype = ''
                    if cover == 'librarything':
                        covertype = '_lt'
                    elif cover == 'goodreads':
                        covertype = '_gr'
                    elif cover == 'openlibrary':
                        covertype = '_ol'
                    elif cover == 'googleisbn':
                        covertype = '_gi'
                    elif cover == 'googleimage':
                        covertype = '_go'
                    elif cover == 'bing':
                        covertype = '_bi'
                    elif cover == 'ranobedb':
                        covertype = '_ra'
                    elif cover == 'cover':
                        covertype = '_cover'
                    if covertype:
                        cachedir = DIRS.CACHEDIR
                        coverid = uuid.uuid4().hex
                        coverlink = 'cache/book/' + coverid + '.jpg'
                        coverfile = os.path.join(cachedir, "book", coverid + '.jpg')
                        newcoverfile = os.path.join(cachedir, "book", bookid + covertype + '.jpg')
                        if not path_exists(newcoverfile):
                            logger.error(f"Coverfile {newcoverfile} for {bookid} is missing")
                        else:
                            try:
                                edited += f'Cover ({cover})'
                                dest = copyfile(newcoverfile, coverfile)
                                logger.debug(f"{newcoverfile} {coverlink} {dest}")
                            except Exception as e:
                                logger.error(str(e))
                    else:
                        coverlink = bookdata['BookImg']

                    if edited:
                        control_value_dict = {'BookID': bookid}
                        new_value_dict = {
                            'BookName': bookname,
                            'BookSub': booksub,
                            'BookGenre': bookgenre,
                            'BookLang': booklang,
                            'BookDate': bookdate,
                            'BookDesc': editordata,
                            'BookIsbn': bookisbn,
                            'WorkID': workid,
                            'BookImg': coverlink,
                            'ScanResult': scanresult,
                            'Manual': bool(manual)
                        }
                        db.upsert("books", new_value_dict, control_value_dict)

                    cmd = ("SELECT SeriesName, SeriesNum, series.SeriesID from member,series where "
                           "series.SeriesID=member.SeriesID and BookID=?")
                    old_series = db.select(cmd, (bookid,))
                    old_list = []
                    new_list = []
                    dict_counter = 0
                    while f"series[{dict_counter}][name]" in kwargs:
                        s_name = kwargs[f"series[{dict_counter}][name]"]
                        s_name = clean_name(s_name, '&/')
                        s_num = kwargs[f"series[{dict_counter}][number]"]
                        match = db.match('SELECT SeriesID from series WHERE SeriesName=?', (s_name,))
                        if match:
                            new_list.append([match['SeriesID'], s_num, s_name])
                        else:
                            new_list.append(['', s_num, s_name])
                        dict_counter += 1
                    if ('series[new][name]' in kwargs and 'series[new][number]' in kwargs and
                            kwargs['series[new][name]']):
                        s_name = kwargs["series[new][name]"]
                        s_name = clean_name(s_name, '&/')
                        s_num = kwargs['series[new][number]']
                        new_list.append(['', s_num, s_name])
                    for itm in old_series:
                        old_list.append([itm['SeriesID'], itm['SeriesNum'], itm['SeriesName']])

                    debug_msg = f"Old series list for {bookid}: {old_list}"
                    logger.debug(debug_msg)
                    clean_list = []
                    for itm in new_list:
                        if itm[1]:
                            clean_list.append(itm)
                    new_list = clean_list

                    debug_msg = f"New series list for {bookid}: {new_list}"
                    logger.debug(debug_msg)
                    series_changed = False
                    for itm in old_list:
                        if itm[1:] not in [i[1:] for i in new_list]:
                            series_changed = True
                    for itm in new_list:
                        if itm[1:] not in [i[1:] for i in old_list]:
                            series_changed = True
                    if not series_changed:
                        logger.debug("No series changes")
                    if series_changed:
                        set_series(new_list, bookid, reason=scanresult)
                        delete_empty_series()
                        edited += "Series "

                    bookfile = bookdata['BookFile']
                    if bookfile and path_isfile(bookfile):
                        opffile = opf_file(os.path.dirname(bookfile))
                    else:
                        opffile = ''
                    if opffile and path_isfile(opffile):
                        opf_template, replaces = opf_read(opffile)
                    else:
                        opf_template = ''
                        replaces = []

                    if opf_template:
                        subs = []
                        for itm in replaces:
                            if itm[0] == 'title':
                                subs.append((itm[0], bookname))
                            elif itm[0] == 'creator':
                                subs.append((itm[0], authorname))
                            elif itm[0] == 'ISBN':
                                subs.append((itm[0], bookisbn))
                            elif itm[0] == 'date':
                                subs.append((itm[0], bookdate))
                            elif itm[0] == 'description':
                                subs.append((itm[0], editordata))
                            elif itm[0] in kwargs:
                                if itm[1] != kwargs[itm[0]]:
                                    edited += itm[0] + ' '
                                    subs.append((itm[0], kwargs[itm[0]]))
                                else:
                                    subs.append((itm[0], itm[1]))
                            else:
                                subs.append((itm[0], itm[1]))

                        if edited:
                            new_opf = opf_write(opf_template, subs)
                            remove_file(opf_template)
                            remove_file(opffile)
                            try:
                                safe_move(new_opf, opffile)
                            except Exception as e:
                                logger.warning(f"Failed to move file: {str(e)}")
                                moved = False
                    if edited:
                        logger.info(f'Updated [ {edited}] for {bookname}')
                    else:
                        logger.debug(f'Book [{bookname}] has not been changed')

                    if moved:
                        authordata = db.match('SELECT AuthorID from authors WHERE AuthorName=?', (authorname,))
                        if authordata:
                            control_value_dict = {'BookID': bookid}
                            new_value_dict = {'AuthorID': authordata['AuthorID']}
                            db.upsert("books", new_value_dict, control_value_dict)
                            update_totals(bookdata["AuthorID"])  # we moved from here
                            update_totals(authordata['AuthorID'])  # to here

                        logger.info(f'Book [{bookname}] has been moved')
                    else:
                        logger.debug(f'Book [{bookname}] has not been moved')
                    if edited or moved:
                        data = db.match("SELECT * from books,authors WHERE "
                                        "books.authorid=authors.authorid and BookID=?", (bookid,))
                        if data['BookFile'] and path_isfile(data['BookFile']):
                            dest_path = os.path.dirname(data['BookFile'])
                            global_name = splitext(os.path.basename(data['BookFile']))[0]
                            if opf_template and CONFIG.get_bool('IMP_EBOOKOPF'):  # we already have a valid (new) opffile
                                dest_opf = os.path.join(dest_path, global_name + '.opf')
                                if opffile != dest_opf:
                                    try:
                                        safe_copy(opffile, dest_opf)
                                    except Exception as e:
                                        logger.warning(f"Failed to copy opf file: {str(e)}")
                            elif CONFIG.get_bool('IMP_EBOOKOPF'):
                                create_opf(dest_path, data, global_name, overwrite=True)

                    raise cherrypy.HTTPRedirect(f"edit_book?bookid={bookid}")
            finally:
                db.close()
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_results_ajax(self, **args):
        action = args.get('action', 'unknown action')
        redirect = args.get('redirect', '')
        passed = 0
        failed = 0

        for arg in ['action']:
            args.pop(arg, None)

        this_source = lazylibrarian.INFOSOURCES[CONFIG['BOOK_API']]
        api = this_source['api']
        api = api()
        ids = set(args.keys())
        if action in ['AddBook', 'AddAudio', 'AddBoth']:
            wantbook = "Wanted" if action in ['AddBook', 'AddBoth'] else 'Skipped'
            wantaudio = "Wanted" if action in ['AddAudio', 'AddBoth'] else 'Skipped'
            for itm in ids:
                if api.add_bookid_to_db(itm, wantbook, wantaudio,
                                        f"Added by User from resultlist {wantbook}:{wantaudio}"):
                    passed += 1
                else:
                    failed += 1
        elif action in ['AddAuthor']:
            books = bool(CONFIG['NEWAUTHOR_STATUS'] != 'Ignored') or bool(CONFIG['NEWAUTHOR_AUDIO'] != 'Ignored')
            for itm in ids:
                if add_author_to_db(refresh=False, authorid=itm, addbooks=books,
                                    reason=f"User add_author_id {itm}"):
                    passed += 1
                else:
                    failed += 1

        total = passed + failed
        summary = mark_summary(i18n.gettext("Mark Results '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)

        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary,
            'redirect': redirect
        }

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_books_ajax(self, authorid=None, seriesid=None, action=None, redirect=None, **args):
        book_filter = None
        if 'bookfilter' in args:
            book_filter = args['bookfilter']
        logger = logging.getLogger(__name__)
        if 'library' in args:
            library = args['library']
        else:
            library = 'eBook'
            if redirect == 'audio':
                library = 'AudioBook'

        if 'marktype' in args:
            library = args['marktype']

        if 'AuthorID' in args and authorid is None:
            authorid = args['AuthorID']

        for arg in ['book_table_length', 'ignored', 'library', 'booklang', 'marktype', 'AuthorID', 'bookfilter']:
            args.pop(arg, None)

        passed = 0
        failed = 0
        to_read = []
        have_read = []
        reading = []
        abandoned = []
        userid = ''
        wantedbooks = []
        wantedaudio = []

        db = database.DBConnection()
        if not self.valid_source(redirect):
            redirect = "books"
        check_totals = []
        if redirect == 'author':
            check_totals = [authorid]
        reading_lists = ["Unread", "Read", "ToRead", "Reading", "Abandoned"]
        if action:
            if action in reading_lists:
                userid = owner_id()
                if userid:
                    to_read = set(get_readinglist("ToRead", userid))
                    have_read = set(get_readinglist("HaveRead", userid))
                    reading = set(get_readinglist("Reading", userid))
                    abandoned = set(get_readinglist("Abandoned", userid))

            for bookid in args:
                if action in reading_lists:
                    to_read.discard(bookid)
                    have_read.discard(bookid)
                    reading.discard(bookid)
                    abandoned.discard(bookid)

                    if action == "Read":
                        have_read.add(bookid)
                    elif action == "ToRead":
                        to_read.add(bookid)
                    elif action == "Reading":
                        reading.add(bookid)
                    elif action == "Abandoned":
                        abandoned.add(bookid)
                    logger.debug(f'Status set to {action} for {bookid}')
                    passed += 1

                elif action in ["Wanted", "WantEbook", "WantAudio", "WantBoth"] or \
                        status_mark_targets(action, library):
                    bookdata = db.match('SELECT AuthorID,BookName,Status,AudioStatus from books WHERE BookID=?',
                                        (bookid,))
                    if bookdata:
                        authorid = bookdata['AuthorID']
                        bookname = bookdata['BookName']
                        if authorid not in check_totals:
                            check_totals.append(authorid)
                        if (action == "Wanted" and "eBook" in library) or action in ["WantEbook", "WantBoth"]:
                            if bookdata['Status'] in ["Open", "Have"]:
                                logger.debug(f'eBook "{bookname}" is already marked Open')
                                failed += 1
                            else:
                                # ScanResult set here too, matching the Ignored/Skipped/Have
                                # actions below - otherwise re-wanting a previously-deleted
                                # book leaves its stale "User deleted" ScanResult in place
                                # with no indication the book is active again.
                                db.upsert("books", {'Status': 'Wanted', 'ScanResult': 'User Wanted'},
                                          {'BookID': bookid})
                                logger.debug(f'Status set to "Wanted" for "{bookname}"')
                                wantedbooks.append({"bookid": bookid})
                                passed += 1
                        if (action == "Wanted" and "AudioBook" in library) or action in ["WantAudio", "WantBoth"]:
                            if bookdata['AudioStatus'] in ["Open", "Have"]:
                                logger.debug(f'AudioBook "{bookname}" is already marked Open')
                                failed += 1
                            else:
                                db.upsert("books", {'AudioStatus': 'Wanted', 'ScanResult': 'User Wanted'},
                                          {'BookID': bookid})
                                logger.debug(f'AudioStatus set to "Wanted" for "{bookname}"')
                                wantedaudio.append({"bookid": bookid})
                                passed += 1
                        targets = status_mark_targets(action, library)
                        if targets:
                            status, mark_library = targets
                            if 'eBook' in mark_library:
                                db.upsert("books", {'Status': status, 'ScanResult': f'User {status}'},
                                          {'BookID': bookid})
                                logger.debug(f'Status set to "{status}" for "{bookname}"')
                                passed += 1
                            if 'AudioBook' in mark_library:
                                db.upsert("books", {'AudioStatus': status, 'ScanResult': f'User {status}'},
                                          {'BookID': bookid})
                                logger.debug(f'AudioStatus set to "{status}" for "{bookname}"')
                                passed += 1
                    else:
                        logger.warning(f"Unable to set status {action} for {bookid}")
                        failed += 1
                elif action == "NoDelay":
                    if 'eBook' in library:
                        db.action("delete from failedsearch WHERE BookID=? AND Library='eBook'", (bookid,))
                    if 'AudioBook' in library:
                        db.action("delete from failedsearch WHERE BookID=? AND Library='AudioBook'", (bookid,))
                    logger.debug(f'{library} delay set to zero for {bookid}')
                    passed += 1
                elif action in ["Remove", "Delete"]:
                    cmd = ("SELECT AuthorName,Bookname,BookFile,AudioFile,books.AuthorID from books,authors "
                           "WHERE BookID=? and books.AuthorID = authors.AuthorID")
                    bookdata = db.match(cmd, (bookid,))
                    if bookdata:
                        authorid = bookdata['AuthorID']
                        bookname = bookdata['BookName']
                        if authorid not in check_totals:
                            check_totals.append(authorid)
                        if action == "Delete":
                            if 'AudioBook' in library:
                                bookfile = bookdata['AudioFile']
                                if bookfile and path_isfile(bookfile):
                                    try:
                                        rmtree(os.path.dirname(bookfile))
                                        logger.info(f'AudioBook {os.path.dirname(bookfile)} deleted from disc')
                                        db.action("UPDATE books SET AudioFile='' WHERE BookID=?", (bookid,))
                                    except Exception as e:
                                        logger.warning(f'rmtree failed on {bookfile}, {type(e).__name__} {str(e)}')
                                        failed += 1
                            if 'eBook' in library:
                                bookfile = bookdata['BookFile']
                                if bookfile and path_isfile(bookfile):
                                    try:
                                        rmtree(os.path.dirname(bookfile))
                                        logger.info(f'eBook {os.path.dirname(bookfile)} deleted from disc')
                                        db.action("UPDATE books SET BookFile='' WHERE BookID=?", (bookid,))
                                        if CONFIG['IMP_CALIBREDB'] and \
                                            CONFIG.get_bool('IMP_CALIBRE_EBOOK'):
                                            self.delete_from_calibre(bookdata)
                                    except Exception as e:
                                        logger.warning(f'rmtree failed on {bookfile}, {type(e).__name__} {str(e)}')
                                        failed += 1

                        if 'eBook' in library:
                            db.upsert("books", {"Status": "Ignored", "ScanResult": f"User {action}d ebook"}, {"BookID": bookid})
                            logger.debug(f'Status set to Ignored for "{bookname}"')
                            passed += 1
                        if 'AudioBook' in library:
                            db.upsert("books", {"AudioStatus": "Ignored", "ScanResult": f"User {action}d audiobook"}, {"BookID": bookid})
                            logger.debug(f'AudioStatus set to Ignored for "{bookname}"')
                            passed += 1

                        if action == 'Delete':
                            bookcheck = db.match('SELECT Status,AudioStatus from books WHERE BookID=?', (bookid,))
                            if bookcheck['Status'] == bookcheck['AudioStatus'] == 'Ignored':
                                for table in ['books', 'wanted', 'readinglists']:
                                    db.action(f"DELETE from {table} WHERE BookID=?", (bookid,))

                        update_totals(authorid)

            if action in reading_lists and userid:
                set_readinglist("ToRead", userid, to_read)
                set_readinglist("HaveRead", userid, have_read)
                set_readinglist("Reading", userid, reading)
                set_readinglist("Abandoned", userid, abandoned)
        db.close()

        if check_totals:
            for author in check_totals:
                update_totals(author)

        # start searchthreads
        if CONFIG.use_any() and check_int(CONFIG['SEARCH_BOOKINTERVAL'], 0):
            if wantedbooks:
                logger.debug(f"Starting ebook search thread, library={library}, action={action}")
                threading.Thread(target=search_book, name='SEARCHBOOK',
                                 args=[wantedbooks, 'eBook']).start()
            if wantedaudio:
                logger.debug(f"Starting audio search thread, library={library}, action={action}")
                threading.Thread(target=search_book, name='SEARCHBOOK',
                                 args=[wantedaudio, 'AudioBook']).start()

        if redirect == "author":
            if 'eBook' in library:
                redirect = f"author_page?authorid={authorid}&library=eBook"
            if 'AudioBook' in library:
                redirect = f"author_page?authorid={authorid}&library=AudioBook"
        elif redirect in ["books", "audio"]:
            redirect = redirect
        elif redirect == "members":
            redirect = f"series_members?seriesid={seriesid}&ignored=False"
        elif 'AudioBook' in library:
            redirect = "manage?library=AudioBook"
        else:
            redirect = "manage?library=eBook"
        if book_filter:
            redirect = f"{redirect}&book_filter={book_filter}"
        # Return JSON response instead of redirect
        total = passed + failed
        summary = mark_summary(i18n.gettext("Mark Books '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary,
            'redirect': redirect
        }

    # WALL #########################################################

    @cherrypy.expose
    @require_auth()
    def mag_wall(self, title=''):
        self.label_thread('MAGWALL')
        cmd = "SELECT IssueFile,IssueID,IssueDate,Title,Cover from issues"
        args = None
        if title:
            title = title.replace('&amp;', '&')
            cmd += " WHERE Title=?"
            args = (title,)
        cmd += " order by IssueAcquired DESC"
        db = database.DBConnection()
        try:
            issues = db.select(cmd, args)
        finally:
            db.close()
        if not len(issues):
            raise cherrypy.HTTPRedirect("magazines")
        mod_issues = []
        maxcount = CONFIG.get_int('MAX_WALL')
        for count, issue in enumerate(issues, start=1):
            this_issue = dict(issue)
            if not this_issue.get('Cover') or not this_issue['Cover'].startswith('cache/'):
                this_issue['Cover'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(this_issue['Cover'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    this_issue['Cover'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, this_issue['Cover'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        this_issue['Cover'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            this_issue['Title'] = issue['Title'].replace('&amp;', '&')
            mod_issues.append(this_issue)
            if maxcount and count >= maxcount:
                title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': count}
                break

        return serve_template(
            templatename="coverwall.html", title=title, results=mod_issues, redirect="magazines",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def comic_wall(self, comicid=None):
        self.label_thread('COMICWALL')
        cmd = ("SELECT IssueFile,IssueID,comics.ComicID,Title,Cover from comicissues,comics WHERE "
               "comics.ComicID = comicissues.ComicID")
        args = None
        if comicid:
            cmd += " AND comics.ComicID=?"
            args = (comicid,)
        cmd += " order by IssueAcquired DESC"
        db = database.DBConnection()
        try:
            issues = db.select(cmd, args)
        finally:
            db.close()
        title = ''
        if not len(issues):
            raise cherrypy.HTTPRedirect("comics")
        mod_issues = []
        maxcount = CONFIG.get_int('MAX_WALL')
        for count, issue in enumerate(issues, start=1):
            this_issue = dict(issue)
            if not this_issue.get('Cover') or not this_issue['Cover'].startswith('cache/'):
                this_issue['Cover'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(this_issue['Cover'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    this_issue['Cover'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, this_issue['Cover'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        this_issue['Cover'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            mod_issues.append(this_issue)
            if maxcount and count >= maxcount:
                title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': count}
                break

        return serve_template(
            templatename="coverwall.html", title=title, results=mod_issues, redirect="comic",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def book_wall(self, have='0'):
        self.label_thread('BOOKWALL')
        if have == '1':
            cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status='Open' order by BookLibrary DESC"
            title = i18n.gettext('Recently Downloaded Books')
        else:
            cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status != 'Ignored' order by BookAdded DESC"
            title = i18n.gettext('Recently Added Books')
        db = database.DBConnection()
        try:
            results = db.select(cmd)
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("books")
        maxcount = CONFIG.get_int('MAX_WALL')
        if maxcount and len(results) > maxcount:
            results = results[:maxcount]
            title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': len(results)}
        ret = []
        for result in results:
            itm = dict(result)
            if not itm['BookLink']:
                itm['BookLink'] = ''
            elif itm['BookLink'].startswith('/works/OL'):
                itm['BookLink'] = CONFIG['OL_URL'] + itm['BookLink']

            if not itm.get('BookImg') or not itm['BookImg'].startswith('cache/'):
                itm['BookImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['BookImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['BookImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['BookImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['BookImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="books", have=have,
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def author_wall(self, have='1'):
        self.label_thread('AUTHORWALL')
        cmd = "SELECT Status,AuthorImg,AuthorID,AuthorName,HaveBooks,TotalBooks from authors "
        if have == '1':
            cmd += "where Status='Active' or Status='Wanted' order by AuthorName ASC"
            title = i18n.gettext('Active/Wanted Authors')
        else:
            cmd += "where Status !='Active' and Status != 'Wanted' order by AuthorName ASC"
            title = i18n.gettext('Inactive Authors')
        db = database.DBConnection()
        try:
            results = db.select(cmd)
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("authors")

        ret = []
        for result in results:
            itm = dict(result)
            if not itm.get('AuthorImg') or not itm['AuthorImg'].startswith('cache/'):
                itm['AuthorImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['AuthorImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['AuthorImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['AuthorImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['AuthorImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="authors", have=have,
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def audio_wall(self):
        self.label_thread('AUDIOWALL')
        db = database.DBConnection()
        try:
            results = db.select(
                'SELECT AudioFile,BookImg,BookID,BookName from books '
                'where AudioStatus="Open" order by AudioLibrary DESC')
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("audio")
        title = i18n.gettext('Recent AudioBooks')
        maxcount = CONFIG.get_int('MAX_WALL')
        if maxcount and len(results) > maxcount:
            results = results[:maxcount]
            title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': len(results)}
        ret = []
        for result in results:
            itm = dict(result)
            if not itm.get('BookImg') or not itm['BookImg'].startswith('cache/'):
                itm['BookImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['BookImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['BookImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['BookImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['BookImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="audio",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def wall_columns(self, redirect=None, count=None, have='', title=''):
        title = title.split(' (')[0].replace(' ', '+')
        if not have:
            have = '1' if 'Wanted' in title else '0'
        columns = check_int(CONFIG.get_int('WALL_COLUMNS'), 6)
        if count == 'up' and columns <= 12:
            columns += 1
        elif count == 'down' and columns > 1:
            columns -= 1
        CONFIG.set_int('WALL_COLUMNS', columns)
        if redirect == 'audio':
            raise cherrypy.HTTPRedirect('audio_wall')
        if redirect == 'books':
            raise cherrypy.HTTPRedirect(f'book_wall?have={have}')
        if redirect == 'magazines':
            if title:
                raise cherrypy.HTTPRedirect(f'mag_wall?title={title}')
            raise cherrypy.HTTPRedirect('mag_wall')
        if redirect == 'comic':
            if title:
                raise cherrypy.HTTPRedirect(f'comic_wall?comicid={title}')
            raise cherrypy.HTTPRedirect('comic_wall')
        if redirect == 'authors':
            raise cherrypy.HTTPRedirect(f'author_wall?have={have}')
        raise cherrypy.HTTPRedirect('home')

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
    def open_comic(self, comicid=None, issueid=None):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            if comicid and '_' in comicid:
                comicid = comicid.split('_')[0]

            # we may want to open an issue with an issueid
            if comicid and issueid:
                cmd = ("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID and "
                       "comics.ComicID=? and IssueID=?")
                iss_data = db.match(cmd, (comicid, issueid))
                if iss_data:
                    issue_file = iss_data["IssueFile"]
                    if issue_file and path_isfile(issue_file):
                        logger.debug(f'Opening file {issue_file}')
                        return self.send_file(issue_file, name=f"{iss_data['Title']} {issueid}"
                                                               f"{splitext(issue_file)[1]}")

            # or we may just have a comicid to find comic in comicissues table
            cmd = ("SELECT Title,IssueFile,IssueID from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                   "and comics.ComicID=?")
            iss_data = db.select(cmd, (comicid,))
        finally:
            db.close()
        if len(iss_data) == 0:
            logger.warning(f"No issues for comic {comicid}")
            raise cherrypy.HTTPRedirect("comics")

        if len(iss_data) == 1 and CONFIG.get_bool('COMIC_SINGLE'):  # we only have one issue, get it
            title = iss_data[0]["Title"]
            issue_id = iss_data[0]["IssueID"]
            issue_file = iss_data[0]["IssueFile"]
            if issue_file and path_isfile(issue_file):
                logger.debug(f'Opening {comicid} - {issue_id}')
                return self.send_file(issue_file, name=f"{title} {issue_id}{splitext(issue_file)[1]}")
            logger.warning(f"No issue {issue_id} for comic {title}")
            raise cherrypy.HTTPError(404, f"Comic Issue {issue_id} not found for {title}")

        # multiple issues, show a list
        logger.debug(f"{comicid} has {len(iss_data)} {plural(len(iss_data), 'issue')}")
        raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")

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
    def send_mag(self, bookid=None):
        return self.open_mag(bookid=bookid, email=True)

    @cherrypy.expose
    @require_auth()
    def open_mag(self, bookid=None, email=False):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            # we may want to open an issue with a hashed bookid
            mag_data = db.match('SELECT * from issues WHERE IssueID=?', (bookid,))
            if mag_data:
                issue_file = mag_data["IssueFile"]
                if issue_file and path_isfile(issue_file):
                    if email:
                        logger.debug(f'Emailing file {issue_file}')
                    else:
                        logger.debug(f'Opening file {issue_file}')
                    return self.send_file(issue_file, name=f"{mag_data['Title']} {mag_data['IssueDate']}"
                                                           f"{splitext(issue_file)[1]}", email=email)

            # or we may just have a title to find magazine in issues table
            mag_data = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (unquote(bookid),))
            if not mag_data:
                logger.warning(f"Unknown magazine title: {bookid}")
                raise cherrypy.HTTPError(404, f"Magazine {bookid} not found")
            bookid = mag_data['Title']
            mag_data = db.select('SELECT * from issues WHERE Title=? COLLATE NOCASE', (bookid,))
        finally:
            db.close()

        if len(mag_data) == 1 and CONFIG.get_bool('MAG_SINGLE'):  # we only have one issue, get it
            issue_date = mag_data[0]["IssueDate"]
            issue_file = mag_data[0]["IssueFile"]
            if issue_file and path_isfile(issue_file):
                if email:
                    logger.debug(f'Emailing {bookid} - {issue_date}')
                else:
                    logger.debug(f'Opening {bookid} - {issue_date}')
                return self.send_file(issue_file, name=f"{bookid} {issue_date}{splitext(issue_file)[1]}",
                                      email=email)
            logger.warning(f"No issue {issue_date} for magazine {bookid}")
            raise cherrypy.HTTPRedirect("magazines")
        if len(mag_data) == 0:
            logger.warning(f"No issues found for magazine {bookid}")
            raise cherrypy.HTTPRedirect("magazines")
        # multiple issues, show a list
        logger.debug(f"{bookid} has {len(mag_data)} {plural(len(mag_data), 'issue')}")
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(bookid)}")

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
    def bookdesc(self, bookid=None):
        img = None
        title = None
        text = None
        if bookid:
            db = database.DBConnection()
            if bookid.startswith('A_'):
                cmd = "SELECT AuthorName,About,AuthorImg from authors WHERE authorid=?"
                res = db.match(cmd, (bookid[2:],))
            elif bookid.startswith(('CV', 'CX')):
                try:
                    comicid, issueid = bookid.split('_')
                    cmd = ("SELECT Title as BookName,comicissues.Description as BookDesc,Cover as BookImg,"
                           "Contributors from comics,comicissues where comics.comicid = comicissues.comicid "
                           "and comics.comicid=? and issueid=?")
                    res = db.match(cmd, (comicid, issueid))
                except ValueError:
                    cmd = ("SELECT Title as BookName,Description as BookDesc,LatestCover as BookImg from comics "
                           "where comicid=?")
                    res = db.match(cmd, (bookid,))
            else:
                cmd = "SELECT BookName,BookDesc,BookImg,AuthorID from books WHERE bookid=?"
                res = db.match(cmd, (bookid,))
            if res:
                res = dict(res)
                text = res.get('BookDesc')
                if not text:
                    text = res.get('About')
                contributors = res.get('Contributors')
                if contributors:
                    text += '<br><br>' + contributors
                img = res.get('BookImg')
                if not img:
                    img = res.get('AuthorImg')
                title = res.get('BookName')
                if not title:
                    title = res.get('AuthorName')
                if 'AuthorID' in res:
                    common.lastauthor = res['AuthorID']
            db.close()
        if not img:
            img = 'images/nocover.jpg'
        if not title:
            title = i18n.gettext('BookID not found')
        if not text:
            text = i18n.gettext('No Description')
        return img + '^' + title + '^' + text

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
    @require_auth()
    def manage(self, **kwargs):
        types = []
        if CONFIG.get_bool('EBOOK_TAB'):
            types.append('eBook')
        if CONFIG.get_bool('AUDIO_TAB'):
            types.append('AudioBook')
        if not types:
            raise cherrypy.HTTPRedirect('authors')
        library = types[0]
        which_status = 'Wanted'
        if 'library' in kwargs and kwargs['library'] in types:
            library = kwargs['library']
        if 'whichStatus' in kwargs and kwargs['whichStatus']:
            which_status = kwargs['whichStatus']
        if which_status == 'None':
            which_status = "Wanted"
        return serve_template(templatename="managebooks.html", title=i18n.gettext('Manage AudioBooks') if library == 'AudioBook' else i18n.gettext('Manage eBooks'),
                              books=[], types=types, library=library, whichStatus=which_status)

    @cherrypy.expose
    def opds(self, **kwargs):
        self.label_thread('OPDS Server')
        op = OPDS()
        op.check_params(**kwargs)
        data = op.fetch_data()
        return data

    def send_file(self, myfile, name=None, email=False):
        logger = logging.getLogger(__name__)
        userid = owner_id()
        if userid:
            msg = ''
            if email and userid:
                db = database.DBConnection()
                res = db.match('SELECT UserName,SendTo from users where UserID=?', (userid,))
                db.close()
                if res and res['SendTo']:
                    db = database.DBConnection()
                    sent = []
                    not_sent = []
                    # sending files to kindles only seems to work if separate emails
                    if ',' in res['SendTo']:
                        addrs = get_list(res['SendTo'])
                    else:
                        addrs = [res['SendTo']]
                    for addr in addrs:
                        logger.debug(f"Emailing {myfile} to {addr}")
                        if name:
                            msg = lazylibrarian.NEWFILE_MSG.replace('{name}', name).replace(
                                '{method}', ' is attached').replace('{link}', '')
                        result = notifiers.email_notifier.email_file(subject="Message from LazyLibrarian",
                                                                     message=msg, to_addr=addr, files=[myfile])
                        if result:
                            db.action('INSERT into sent_file (WhenSent, UserID, Addr, FileName) VALUES (?, ?, ?, ?)',
                                      (str(int(time.time())), userid, addr, os.path.basename(myfile)))
                            sent.append(addr)
                        else:
                            not_sent.append(addr)
                    db.close()
                    msg = ''
                    if sent:
                        logger.debug(f"Emailed file {os.path.basename(myfile)} to {','.join(sent)}")
                        msg = i18n.gettext("Emailed file %(file)s to %(addresses)s") % {
                            'file': os.path.basename(myfile), 'addresses': ','.join(sent)} + ' '
                    if not_sent:
                        logger.error(f"Failed to email file {os.path.basename(myfile)} to {','.join(not_sent)}")
                        msg += i18n.gettext("Failed to email file %(file)s to %(addresses)s") % {
                            'file': os.path.basename(myfile), 'addresses': ','.join(not_sent)}
                return serve_template(templatename="choosetype.html", title=i18n.gettext('Send file'),
                                      pop_message=msg, pop_types='', bookid='', valid='', email=email)
        if not name:
            name = os.path.basename(myfile)
        if path_isfile(myfile):
            if userid:
                db = database.DBConnection()
                db.action('INSERT into sent_file (WhenSent, UserID, Addr, FileName) VALUES (?, ?, ?, ?)',
                          (str(int(time.time())), userid, 'Open', name))
                db.close()
            return serve_file(myfile, mime_type(myfile), "attachment", name=name)
        logger.error(f"No file [{myfile}]")
        return None
