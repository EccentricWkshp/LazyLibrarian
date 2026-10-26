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

""" The ebook and audiobook lists, book pages and edits, searching and marking books """

import contextlib
import datetime
import logging
import os
import threading
import time
import traceback
import uuid
from shutil import copyfile, rmtree
from urllib.parse import urlencode

import cherrypy

import lazylibrarian
from lazylibrarian import ROLE, database, i18n, notifiers
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.bookwork import delete_empty_series, language_from_words, set_series
from lazylibrarian.cache import gr_xml_request
from lazylibrarian.common import get_readinglist, is_valid_language, set_readinglist
from lazylibrarian.config2 import CONFIG
from lazylibrarian.downloadmethods import (
    direct_dl_method,
    irc_dl_method,
    nzb_dl_method,
    tor_dl_method,
)
from lazylibrarian.filesystem import (
    DIRS,
    book_file,
    opf_file,
    path_exists,
    path_isdir,
    path_isfile,
    remove_file,
    safe_copy,
    safe_move,
    splitext,
)
from lazylibrarian.formatter import (
    check_float,
    check_int,
    check_year,
    clean_name,
    date_format,
    get_list,
    now,
    plural,
    sort_definite,
    surname_first,
    thread_name,
    unaccented,
)
from lazylibrarian.images import get_book_cover
from lazylibrarian.importer import add_author_to_db, update_totals
from lazylibrarian.manual_import import process_book_from_dir
from lazylibrarian.manualbook import search_item
from lazylibrarian.metadata_opf import create_opf
from lazylibrarian.notifiers import custom_notify_snatch, notify_snatch
from lazylibrarian.opfedit import opf_read, opf_write
from lazylibrarian.scheduling import SchedulerCommand, schedule_job
from lazylibrarian.searchbook import search_book
from lazylibrarian.web import common
from lazylibrarian.web.common import (
    BasePages,
    fold,
    mark_summary,
    serve_template,
    status_mark_targets,
)


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


class BookPages(BasePages):
    """ The ebook and audiobook lists, book pages and edits, searching and marking books """

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
