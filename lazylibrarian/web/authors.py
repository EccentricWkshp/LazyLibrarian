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

""" The author list, author pages, author edits and source links, and the search box """

import datetime
import logging
import os
import re
import threading
import time
import traceback
from shutil import copyfile, rmtree
from urllib.parse import quote

import cherrypy
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import ROLE, database, dbk, grsync, i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.cache import ImageType, cache_img
from lazylibrarian.common import delete_empty_folders
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import (
    DIRS,
    get_directory,
    listdir,
    path_exists,
    path_isdir,
    path_isfile,
    setperm,
    splitext,
)
from lazylibrarian.formatter import (
    check_int,
    date_format,
    fold,
    format_author_name,
    get_list,
    safe_unicode,
    sort_definite,
    strip_quotes,
    surname_first,
    unaccented,
)
from lazylibrarian.images import get_author_image, img_id
from lazylibrarian.importer import (
    add_author_name_to_db,
    add_author_to_db,
    get_preferred_author,
    search_for,
    update_totals,
)
from lazylibrarian.librarysync import library_scan
from lazylibrarian.startup import prioritized_infosources
from lazylibrarian.web import common
from lazylibrarian.web.common import BasePages, mark_summary, serve_template


class AuthorPages(BasePages):
    """ The author list, author pages, author edits and source links, and the search box """

    # GoodReads prefixes its 'about' field with an editorial note like:
    # "<i>Librarian Note: There is more than one author in the Goodreads
    # database with this name.</i><br /><br />actual bio..." when applicable
    # (duplicate-author disambiguation, merged records, etc.) - GR's own
    # convention, not a separate structured API field. get_all_author_details()
    # stores 'about' verbatim, so this is detectable straight from what's
    # already in the authors table, no extra fetch or schema change needed.
    LIBRARIAN_NOTE_RE = re.compile(
        r'^\s*<i>\s*Librarian Note:\s*(?P<note>.*?)\s*</i>\s*(?:<br\s*/?>\s*)*', re.IGNORECASE | re.DOTALL)

    @cherrypy.expose
    @require_auth()
    def authors(self):
        title = i18n.gettext('Authors')
        if lazylibrarian.IGNORED_AUTHORS:
            if CONFIG.get_bool('IGNORE_PAUSED'):
                title = i18n.gettext('Inactive Authors')
            else:
                title = i18n.gettext('Ignored Authors')
        return serve_template(templatename="index.html", title=title, redirect=title.lower())

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_index(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        serversidelogger.debug(f"Start {iDisplayStart} Length {iDisplayLength} Col {iSortCol_0} "
                               f"Dir {sSortDir_0} Search [{sSearch}]")
        rows = []
        filtered = []
        rowlist = []
        userid = None
        userprefs = 0
        mydict = {}
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            cookie = cherrypy.request.cookie
            if cookie and 'll_prefs' in list(cookie.keys()):
                userprefs = check_int(cookie['ll_prefs'].value, 0)
            userid = owner_id()
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            # Sources that expose a per-author ID (unlike GoogleBooks/DNB/BN, which are
            # book-search-only - their author_key is the plain 'authorid' placeholder,
            # not a real per-source column). Derived from INFOSOURCES so a new such
            # source needs no change here or in the badge fallback below.
            author_link_sources = [(name, src['author_key']) for name, src in lazylibrarian.INFOSOURCES.items()
                                    if src['author_key'] != 'authorid']
            cmd = ("SELECT AuthorImg,AuthorName,LastBook,LastDate,Status,AuthorLink,LastLink,HaveBooks,"
                   "UnignoredBooks,AuthorID,LastBookID,DateAdded,Reason,PrimarySource," +
                   ",".join(col for _, col in author_link_sources) +
                   " from authors ")
            if lazylibrarian.IGNORED_AUTHORS:
                if CONFIG.get_bool('IGNORE_PAUSED'):
                    cmd += "where Status IN ('Ignored', 'Paused') "
                else:
                    cmd += "where Status == 'Ignored' "
            else:
                if CONFIG.get_bool('IGNORE_PAUSED'):
                    cmd += "where Status NOT IN ('Ignored', 'Paused') "
                else:
                    cmd += "where Status != 'Ignored' "
            cmd += "and AuthorName is not null "

            if lazylibrarian.PRIMARY_AUTHORS:
                # is the author a primary author for any book...
                bookauthors = set()
                res = db.select(f"SELECT AuthorID from bookauthors WHERE role={ROLE['PRIMARY']}")
                for author in res:
                    bookauthors.add(author['AuthorID'])
                cmd += " and AuthorID in (" + ", ".join(f"'{w}'" for w in bookauthors) + ")"
            myauthors = set()
            if userid and userprefs & lazylibrarian.pref_myauthors:
                res = db.select("SELECT WantID from subscribers WHERE Type='author' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} authors")
                for author in res:
                    myauthors.add(author['WantID'])
                cmd += " and AuthorID in (" + ", ".join(f"'{w}'" for w in myauthors) + ")"

            cmd += " order by AuthorName COLLATE NOCASE"
            serversidelogger.debug(f"get_index {cmd}")

            rowlist = db.select(cmd)
            # At his point we want to sort and filter _before_ adding the html as it's much quicker
            # turn the sqlite rowlist into a list of lists
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    arow = list(row)
                    reasonlist = arow[12]
                    if not reasonlist:
                        reasonlist = "Unknown"
                    reasonlist = reasonlist.split()
                    reasonstring = ''
                    match reasonlist[0].lower().strip(":"):
                        case 'webserver':  # manual search and add of author
                            reasonstring = "Manual search"
                        case 'wishlist':  # added via wishlist rss search
                            reasonstring = "Wishlist search " + ' '.join(reasonlist[1:])
                        case 'process_alternate':  # added via import of alt folder
                            reasonstring = f"Import {' '.join(reasonlist[1:])} from alternate folder"
                        case 'ol.find_book':
                            reasonstring = "OpenLibrary search"
                        case 'ol_get_author_books':
                            reasonstring = "OpenLibrary search"
                        case 'gr.find_book':
                            reasonstring = "GoodReads search"
                        case 'gr_get_author_books':
                            reasonstring = "GoodReads search"
                        case 'hc.find_book':
                            reasonstring = "HardCover search"
                        case 'hc_get_author_books':
                            reasonstring = "HardCover search"
                        case 'gb.find_book':
                            reasonstring = "GoogleBooks search"
                        case 'gb_get_author_books':
                            reasonstring = "GoogleBooks search"
                        case 'import_csv':
                            reasonstring = "CSV import"
                        case 'sync_calibre_list':
                            reasonstring = "Calibre Sync"
                        case 'api':  # by name, id, and refresh
                            reasonstring = "API"
                        case 'add':
                            reasonstring = f"Import author of {' '.join(reasonlist[3:])}"
                        case 'contributor':
                            reasonstring = ' '.join(reasonlist)
                        case 'series':
                            reasonstring = "Search for series " + ' '.join(reasonlist[1:])
                        case _:
                            reasonstring = ''

                    if CONFIG.get_bool('SORT_SURNAME'):
                        arow[1] = surname_first(arow[1], postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
                    if CONFIG.get_bool('SORT_DEFINITE'):
                        arow[2] = sort_definite(arow[2], articles=get_list(CONFIG.get_csv('NAME_DEFINITE')))
                    arow[3] = date_format(arow[3], '', f'{arow[1]}/{arow[2]}', datelang=CONFIG['DATE_LANG'])
                    nrow = arow[:4]
                    havebooks = check_int(arow[7], 0)
                    totalbooks = check_int(arow[8], 0)
                    if totalbooks:
                        percent = int((havebooks * 100.0) / totalbooks)
                    else:
                        percent = 0
                    if percent > 100:
                        percent = 100

                    # if percent <= 25:
                    #     css = 'danger'
                    # elif percent <= 50:
                    #     css = 'warning'
                    # elif percent <= 75:
                    #     css = 'info'
                    # else:
                    #     css = 'success'

                    arow[12] = strip_quotes(reasonstring)
                    nrow.append(percent)
                    nrow.extend(arow[4:11])
                    bar = ''
                    nrow.append(bar)
                    nrow.extend(arow[11:13])

                    # Same source-badge convention as author.html/editauthor.html: prefer
                    # the explicitly-confirmed PrimarySource (linked, so AuthorLink is
                    # guaranteed to match); otherwise fall back to priority order among
                    # whatever's linked (the user's configured CONFIG['BOOK_API'] first,
                    # via prioritized_infosources()), shown as plain text since there's no
                    # verified matching URL for an inferred guess.
                    primarysource = arow[13]
                    link_values = arow[14:14 + len(author_link_sources)]
                    fallback_map = dict(zip((name for name, _ in author_link_sources), link_values, strict=False))
                    badge_source = primarysource
                    if not badge_source:
                        for fb_name, _ in prioritized_infosources():
                            if fallback_map.get(fb_name):
                                badge_source = fb_name
                                break
                    if primarysource:
                        badge_html = (f'<a href="{arow[5]}" target="_blank" rel="noreferrer">'
                                      f'<small><i>{badge_source}</i></small></a>')
                    elif badge_source:
                        badge_html = f'<small><i>{badge_source}</i></small>'
                    else:
                        badge_html = ''
                    nrow.append(badge_html)
                    rows.append(nrow)  # add each rowlist to the masterlist
                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    q = fold(sSearch)
                    filtered = [x for x in rows if q in fold(x)]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0) - 1
                if sortcolumn == 2:
                    sortcolumn = 13
                elif sortcolumn > 2:
                    sortcolumn -= 1
                serversidelogger.debug(f"sortcolumn {sortcolumn}")
                filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                              reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]
                # format DateAdded only after sorting, as the display format may not sort as text
                for row in rows:
                    row[13] = date_format(row[13], CONFIG['DATE_FORMAT'], context=row[1],
                                          datelang=CONFIG['DATE_LANG'])
            serversidelogger.debug(f"get_index returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_index filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_index: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []
        finally:
            db.close()
            mydict = {'iTotalDisplayRecords': len(filtered),
                      'iTotalRecords': len(rowlist),
                      'aaData': rows,
                      'loading': lazylibrarian.AUTHORS_UPDATE,
                      'searching': lazylibrarian.SEARCHING,
                      }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def search(self, searchfor, btnsearch=None):
        logger = logging.getLogger('special.searching')
        logger.debug(f"Search {btnsearch}: {searchfor}")
        searchresults = None
        self.label_thread('SEARCH')
        if not searchfor:
            raise cherrypy.HTTPRedirect("home")

        if not self.validate_param("searchfor", searchfor, ['<', '>', '='], None):
            raise cherrypy.HTTPRedirect("home")

        lazylibrarian.SEARCHING = 1
        if searchfor.lower().startswith('authorid:'):
            self.add_author_id(searchfor[9:])
            return None
        if searchfor.lower().startswith('bookid:'):
            self.add_book(searchfor[7:])
            return None
        authid_key = 'AuthorID'
        bookid_key = 'BookID'

        apisources = []
        for i in lazylibrarian.INFOSOURCES.keys():
            # source, authorid, bookid
            infosource = lazylibrarian.INFOSOURCES[i]
            apisources.append([infosource, infosource['author_key'], infosource['book_key']])

        for itm in apisources:
            if CONFIG['BOOK_API'] == itm[0]:
                authid_key = itm[1]
                bookid_key = itm[2]
                break

        db = database.DBConnection()
        try:
            authorids = db.select(f"SELECT {authid_key} as AuthorID from authors where status != 'Loading'")
            loadingauthorids = db.select(f"SELECT {authid_key} as AuthorID from authors where status = 'Loading'")
            booksearch = db.select(f"SELECT Status,AudioStatus,{bookid_key} as BookID from books")
        finally:
            db.close()

        authorlist = []
        for itm in authorids:
            if itm['AuthorID']:
                authorlist.append(itm['AuthorID'])
        authorlist = list(set(authorlist))
        loadlist = []
        for itm in loadingauthorids:
            if itm['AuthorID']:
                loadlist.append(itm['AuthorID'])
        loadlist = list(set(loadlist))
        booklist = []
        for itm in booksearch:
            if itm['BookID']:
                booklist.append(itm['BookID'])
        booklist = list(set(booklist))
        # we don't know if searchfor is an author, book or isbn
        try:
            searchresults = search_for(searchfor, CONFIG['BOOK_API'])
            logger.debug(f"Found {len(searchresults)} from {CONFIG['BOOK_API']}")
            if CONFIG.get_bool('MULTI_SOURCE'):
                for info_src in lazylibrarian.INFOSOURCES.keys():
                    itm = lazylibrarian.INFOSOURCES[info_src]
                    if CONFIG['BOOK_API'] != info_src and CONFIG[itm['enabled']]:
                        moreresults = search_for(searchfor, info_src)
                        logger.debug(f"Found {len(moreresults)} from {info_src}")
                        # Prefer our configured book api if equal matches by downgrading all the others slightly.
                        for res in moreresults:
                            res['highest_fuzz'] -= 1
                            searchresults.append(res)
        except Exception as e:
            logger.debug(str(e))
        sortedlist = sorted(searchresults, key=lambda x: (x['highest_fuzz'], x['bookrate_count']),
                            reverse=True)
        lazylibrarian.SEARCHING = 0
        return serve_template(templatename="searchresults.html", title=i18n.gettext('Search Results: "%(query)s"') % {'query': searchfor},
                              searchresults=sortedlist, authorlist=authorlist, loadlist=loadlist,
                              booklist=booklist, booksearch=booksearch)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_authors_ajax(self, action=None, **args):
        logger = logging.getLogger(__name__)
        for arg in ['author_table_length', 'series_table_length', 'book_table_length', 'ignored', '_', 'action', 'which_status']:
            args.pop(arg, None)
        passed = 0
        failed = 0
        if action:
            db = database.DBConnection()
            try:
                for authorid in args:
                    check = db.match("SELECT AuthorName from authors WHERE AuthorID=?", (authorid,))
                    if not check:
                        logger.warning(f'Unable to set Status to "{action}" for "{authorid}"')
                        failed += 1
                    elif action in ["Active", "Wanted", "Paused", "Ignored"]:
                        db.upsert("authors", {'Status': action}, {'AuthorID': authorid})
                        logger.info(f'Status set to "{action}" for "{check["AuthorName"]}"')
                        passed += 1
                    elif action in ("Delete", "Delete+Ignore"):
                        failure_list = []
                        logger.info(f"{action} author and media files for {check['AuthorName']}")
                        cmd = "SELECT BookFile,AudioFile,BookID from books WHERE AuthorID=? and "
                        cmd += "((BookFile IS NOT NULL AND BookFile != '') or (AudioFile IS NOT NULL AND AudioFile != ''))"
                        books = db.select(cmd, (authorid,))
                        logger.debug(f"Located {len(books)} books for author {authorid}")
                        if books:
                            for book in books:
                                for location in [book['BookFile'], book['AudioFile']]:
                                    if location and path_exists(location):
                                        try:
                                            foldername = os.path.dirname(location)
                                            logger.debug(f"Deleting folder: {foldername}")
                                            rmtree(foldername)
                                        except Exception as e:
                                            failure_list.append(f'rmtree failed on {location}, {type(e).__name__} {str(e)}')
                                for table in ['wanted', 'readinglists']:
                                    db.action(f"DELETE from {table} WHERE BookID=?", (book['BookID'],))
                            try:
                                logger.debug("Deleting empty folders")
                                delete_empty_folders(CONFIG['EBOOK_DIR'])
                                delete_empty_folders(CONFIG['AUDIO_DIR'])
                            except Exception as e:
                                failure_list.append(f"Error deleting: {e}")
                        if action == "Delete+Ignore":
                            db.action("UPDATE books SET BookFile='', AudioFile='', Status='Ignored', \
                                      AudioStatus='Ignored', Scanresult='User Delete+Ignore' WHERE AuthorID=?",
                                      (authorid,))
                            update_totals(authorid)
                            db.upsert("authors", {'Status': 'Ignored'}, {'AuthorID': authorid})
                            logger.info(f"Author {check['AuthorName']} set to Ignored")
                        else:
                            db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
                            logger.info(f"Author {check['AuthorName']} deleted")
                        if failure_list:
                            logger.warning(f"Failures while {action} {check['AuthorName']}: {failure_list}")
                            failed += 1
                        else:
                            passed += 1
                    elif action == "Remove":
                        logger.info(f"Removing author: {check['AuthorName']}")
                        db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
                        passed += 1
                    elif action == 'Subscribe':
                        userid = owner_id()
                        if userid:
                            res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                           (userid, 'author', authorid))
                            if res:
                                logger.debug(f"User {userid} is already subscribed to {authorid}")
                                failed += 1
                            else:
                                db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                          (userid, 'author', authorid))
                                logger.debug(f"Subscribe {userid} to author {authorid}")
                                passed += 1
                    elif action == 'Unsubscribe':
                        userid = owner_id()
                        if userid:
                            db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                      (userid, 'author', authorid))
                            res = db.select('SELECT bookid from books where authorid=?', (authorid, ))
                            for iss in res:
                                db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                          (userid, 'ebook', iss['bookid']))
                            logger.debug(f"Unsubscribe {userid} author {authorid}")
                            passed += 1
            finally:
                logger.debug(f"Completed {action} for {len(args)}")
                db.close()

        # Return JSON response instead of redirect
        total = passed + failed
        summary = mark_summary(i18n.gettext("Mark Authors '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary
        }

    @cherrypy.expose
    @require_auth()
    def author_page(self, authorid, book_lang=None, library='eBook', ignored=False, **args):
        db = database.DBConnection()
        user = 0
        email = ''
        user = owner_id()
        if user:
            res = db.match('SELECT SendTo from users where UserID=?', (user,))
            if res and res['SendTo']:
                email = res['SendTo']

        author = dict(db.match("SELECT * from authors WHERE AuthorID=?", (authorid,)))
        if not author:
            author = dict(db.match("SELECT * from authors WHERE ol_id=? or gr_id=? or hc_id=?",
                                   (authorid, authorid, authorid,)))
        if ignored:
            languages = db.select(
                "SELECT DISTINCT BookLang from books WHERE AuthorID=? AND Status ='Ignored'",
                (authorid,))
        else:
            languages = db.select(
                "SELECT DISTINCT BookLang from books WHERE AuthorID=? AND Status !='Ignored'",
                (authorid,))
        db.close()

        types = []
        if CONFIG.get_bool('EBOOK_TAB'):
            types.append('eBook')
        if CONFIG.get_bool('AUDIO_TAB'):
            types.append('AudioBook')
        if types and library not in types:
            library = types[0]
        if not types:
            library = None
        if not author:
            raise cherrypy.HTTPRedirect("authors")

        # if we've changed author, reset to first page of new authors books
        if authorid == common.lastauthor:
            firstpage = 'false'
        else:
            common.lastauthor = authorid
            firstpage = 'true'

        authorname = author['AuthorName']
        if not authorname:  # still loading?
            raise cherrypy.HTTPRedirect("authors")

        author['AuthorBorn'] = date_format(author['AuthorBorn'], CONFIG['AUTHOR_DATE_FORMAT'],
                                           context=authorname, datelang=CONFIG['DATE_LANG'])
        author['AuthorDeath'] = date_format(author['AuthorDeath'], CONFIG['AUTHOR_DATE_FORMAT'],
                                            context=authorname, datelang=CONFIG['DATE_LANG'])

        return serve_template(
            templatename="author.html", title=authorname, author=author,
            languages=languages, booklang=book_lang, types=types, library=library, ignored=ignored,
            showseries=CONFIG.get_int('SERIES_TAB'), firstpage=firstpage, user=user, email=email,
            book_filter=args.get('book_filter', ''), gb_search_link=self.gb_search_link(authorname),
            amazon_search_link=self.amazon_search_link(authorname))

    @staticmethod
    def gb_search_link(authorname):
        """ GoogleBooks has no author-entity/ID of its own (see INFOSOURCES's author_link) -
        volumes only, not authors - so unlike gr_link/ol_link/hc_link/ran_link this can't
        be a verified per-author page link, just a name-based search results link using
        Google Books' inauthor: search operator. Not stored - built fresh each render so
        it always reflects the current AuthorName. """
        if not CONFIG['GB_API'] or not authorname:
            return ''
        return f'https://books.google.com/books?q=inauthor:%22{quote(authorname)}%22'

    @staticmethod
    def amazon_search_link(authorname):
        """ Amazon has no free author-lookup API (PA-API needs an Associates account with
        real sales volume) and scraping product pages for the byline's own p_27 author-facet
        value would carry the same ban risk already ruled out elsewhere. This is the
        unauthenticated version of that same p_27 facet search Amazon's own byline links
        use - built from the plain author name, no fetch/scrape involved, same
        unverified-search-link status as gb_search_link. Useful for self-published authors
        (see ASIN work) who often have nothing else to search by. """
        if not authorname:
            return ''
        # The whole "p_27:Name" refinement value needs encoding as one unit (colon -> %3A)
        # to match what Amazon's own byline search links actually send - a bare colon
        # after p_27 with only the name percent-encoded silently fails to filter by author.
        return f'https://www.amazon.com/s?i=stripbooks&rh={quote(f"p_27:{authorname}")}'

    @cherrypy.expose
    @require_auth()
    def author_detail(self, authorid):
        """ Read-only "master" detail view for an author, linked from the author
        name on author_page. Surfaces fields that exist in the authors table but
        have never had anywhere to display on the read-only side (AKA, About,
        DateAdded, Updated, ...) - see author_page for the book-listing view. """
        db = database.DBConnection()
        user = 0
        email = ''
        user = owner_id()
        if user:
            res = db.match('SELECT SendTo from users where UserID=?', (user,))
            if res and res['SendTo']:
                email = res['SendTo']
        author = dict(db.match("SELECT * from authors WHERE AuthorID=?", (authorid,)))
        if not author:
            db.close()
            raise cherrypy.HTTPRedirect("authors")
        authorname = author['AuthorName']
        if not authorname:  # still loading?
            db.close()
            raise cherrypy.HTTPRedirect("authors")

        # Per-source book counts + cross-source overlap for the Sources table below.
        # Uses every source's book_key column for overlap (a book can carry a gb_id/
        # dnb_id even though those aren't author-linkable sources), counted in Python
        # rather than one SQL query per source since per-author book counts are small.
        # Column list is derived from INFOSOURCES (single source of truth, see !1850
        # review) instead of a hand-duplicated tuple. DNB/BN are excluded from the *count*
        # loop below (but stay in book_source_cols for overlap) because they have no
        # dedicated row in author_detail.html - unlike GoogleBooks, which also has no
        # author entity of its own but does get a row, so it stays in both.
        book_source_cols = tuple(src['book_key'] for src in lazylibrarian.INFOSOURCES.values()
                                 if src.get('book_key')) + ('ASIN',)
        book_rows = db.select(
            f"SELECT {','.join(book_source_cols)} from books WHERE AuthorID=?", (authorid,))
        source_book_counts = {}
        for col in (c for c in book_source_cols if c not in ('dnb_id', 'bn_id')):
            count = 0
            overlap = 0
            for row in book_rows:
                if row[col]:
                    count += 1
                    if any(row[other] for other in book_source_cols if other != col):
                        overlap += 1
            source_book_counts[col] = (count, overlap)

        ebook_status_counts = {row['Status'] or 'None': row['cnt'] for row in db.select(
            "SELECT Status, COUNT(*) as cnt FROM books WHERE AuthorID=? GROUP BY Status", (authorid,))}
        audio_status_counts = {row['AudioStatus'] or 'None': row['cnt'] for row in db.select(
            "SELECT AudioStatus, COUNT(*) as cnt FROM books WHERE AuthorID=? GROUP BY AudioStatus", (authorid,))}
        db.close()

        def parse_author_date(datestr):
            if not datestr:
                return None
            parts = datestr.split('-')
            try:
                year = int(parts[0])
                month = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                day = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
                return datetime.date(year, month, day)
            except (ValueError, IndexError):
                return None

        born_date = parse_author_date(author.get('AuthorBorn'))
        death_date = parse_author_date(author.get('AuthorDeath'))
        author_age = None
        if born_date:
            end_date = death_date or datetime.date.today()
            author_age = end_date.year - born_date.year - ((end_date.month, end_date.day)
                                                            < (born_date.month, born_date.day))

        author['AuthorBorn'] = date_format(author['AuthorBorn'], CONFIG['AUTHOR_DATE_FORMAT'],
                                           context=authorname, datelang=CONFIG['DATE_LANG'])
        author['AuthorDeath'] = date_format(author['AuthorDeath'], CONFIG['AUTHOR_DATE_FORMAT'],
                                            context=authorname, datelang=CONFIG['DATE_LANG'])
        if author.get('Updated'):
            author['Updated'] = datetime.datetime.fromtimestamp(int(author['Updated'])).strftime('%Y-%m-%d %H:%M')

        librarian_note = ''
        if author.get('About'):
            match = self.LIBRARIAN_NOTE_RE.match(author['About'])
            if match:
                librarian_note = match.group('note')
                author['About'] = author['About'][match.end():]

        # Per-source About text - a linear list of what each linked source itself
        # says, not just the single merged/preferred version above.
        about_by_source = []
        for name, col in (('GoodReads', 'gr_about'), ('OpenLibrary', 'ol_about'),
                          ('HardCover', 'hc_about'), ('RanobeDB', 'ran_about'), ('DBK', 'dbk_about')):
            text = author.get(col)
            if text:
                note_match = self.LIBRARIAN_NOTE_RE.match(text)
                if note_match:
                    text = text[note_match.end():]
                about_by_source.append((name, text))

        return serve_template(templatename="author_detail.html", title=authorname, author=author,
                              showseries=CONFIG.get_int('SERIES_TAB'), user=user, email=email,
                              librarian_note=librarian_note, gb_search_link=self.gb_search_link(authorname),
                              author_age=author_age, ebook_status_counts=ebook_status_counts,
                              audio_status_counts=audio_status_counts, about_by_source=about_by_source,
                              source_book_counts=source_book_counts,
                              amazon_search_link=self.amazon_search_link(authorname))

    @cherrypy.expose
    @require_auth()
    def set_author(self, authorid, status):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:
            author_name = authorsearch['AuthorName']
            logger.info(f"{status} author: {author_name}")
            control_value_dict = {'AuthorID': authorid}
            new_value_dict = {'Status': status}
            db.upsert("authors", new_value_dict, control_value_dict)
            logger.debug(
                f'AuthorID [{authorid}]-[{author_name}] {status} - redirecting to Author home page')
            db.close()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")
        logger.debug(f'pause_author Invalid authorid [{authorid}]')
        db.close()
        raise cherrypy.HTTPError(404, f"AuthorID {authorid} not found")

    @cherrypy.expose
    @require_auth()
    def pause_author(self, authorid):
        self.set_author(authorid, 'Paused')

    @cherrypy.expose
    @require_auth()
    def want_author(self, authorid):
        self.set_author(authorid, 'Wanted')

    @cherrypy.expose
    @require_auth()
    def resume_author(self, authorid):
        self.set_author(authorid, 'Active')

    @cherrypy.expose
    @require_auth()
    def ignore_author(self, authorid):
        self.set_author(authorid, 'Ignored')

    @cherrypy.expose
    @require_auth()
    def remove_author(self, authorid):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:  # to stop error if try to remove an author while they are still loading
            author_name = authorsearch['AuthorName']
            logger.info(f"Removing all references to author: {author_name}")
            db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
            # if the author was the only remaining contributor to a series, remove the series
            orphans = db.select('select seriesid from series except select seriesid from seriesauthors')
            for orphan in orphans:
                db.action('DELETE from series where seriesid=?', (orphan[0],))
        db.close()
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def refresh_author(self, authorid):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        db.close()
        if authorsearch:  # to stop error if try to refresh an author while they are still loading
            authorname = authorsearch['AuthorName']
            if not authorname or 'unknown' in authorname.lower() or 'anonymous' in authorname.lower():
                authorname = None
            threading.Thread(target=add_author_to_db, name=f"REFRESHAUTHOR_{authorid}",
                             args=[authorname, True, authorid, True,
                                   f"WebServer refresh_author {authorid}"]).start()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")
        logger.debug(f'refresh_author Invalid authorid [{authorid}]')
        raise cherrypy.HTTPError(404, f"AuthorID {authorid} not found")

    @cherrypy.expose
    @require_auth()
    def follow_author(self, authorid):
        # empty GRfollow is not-yet-used, zero means manually unfollowed so sync leaves it alone
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName, GRfollow from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:
            if authorsearch['GRfollow'] and authorsearch['GRfollow'] != '0':
                logger.warning(f"Already Following {authorsearch['AuthorName']}")
            else:
                msg = grsync.grfollow(authorid, True)
                if msg.startswith('Unable'):
                    logger.warning(msg)
                else:
                    logger.info(msg)
                    followid = msg.split("followid=")[1]
                    db.action("UPDATE authors SET GRfollow=? WHERE AuthorID=?", (followid, authorid))
        else:
            msg = f"Invalid authorid to follow ({authorid})"
            logger.error(msg)
            raise cherrypy.HTTPError(404, msg)

        db.close()
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def unfollow_author(self, authorid):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName, GRfollow from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:
            if not authorsearch['GRfollow'] or authorsearch['GRfollow'] == '0':
                logger.warning(f"Not Following {authorsearch['AuthorName']}")
            else:
                msg = grsync.grfollow(authorid, False)
                if msg.startswith('Unable'):
                    logger.warning(msg)
                else:
                    db.action("UPDATE authors SET GRfollow='0' WHERE AuthorID=?", (authorid,))
                    logger.info(msg)
        else:
            msg = f"Invalid authorid to unfollow ({authorid})"
            logger.error(msg)
            raise cherrypy.HTTPError(404, msg)
        db.close()
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def library_scan_author(self, authorid, **kwargs):
        logger = logging.getLogger(__name__)
        fuzzlogger = logging.getLogger('special.fuzz')
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:  # to stop error if try to refresh an author while they are still loading
            author_name = authorsearch['AuthorName']
            types = []
            if CONFIG.get_bool('EBOOK_TAB'):
                types.append('eBook')
            if CONFIG.get_bool('AUDIO_TAB'):
                types.append('AudioBook')
            if not types:
                db.close()
                raise cherrypy.HTTPRedirect('authors')
            library = types[0]
            if 'library' in kwargs and kwargs['library'] in types:
                library = kwargs['library']

            if library == 'AudioBook':
                authordir = safe_unicode(os.path.join(get_directory('AudioBook'), author_name))
            else:  # if library == 'eBook':
                authordir = safe_unicode(os.path.join(get_directory('eBook'), author_name))
            if not path_isdir(authordir):
                logger.debug(f"Assumed authordir [{authordir}] not found")
                # books might not be in exact same authorname folder due to capitalisation
                # or accent stripping etc.
                # eg Calibre puts books into folder "Eric Van Lustbader", but
                # goodreads told lazylibrarian he's "Eric van Lustbader", note the lowercase 'v'
                # or calibre calls "Neil deGrasse Tyson" "Neil DeGrasse Tyson" with a capital 'D'
                # so try a fuzzy match...
                libdir = os.path.dirname(authordir)
                matchname, exists = get_preferred_author(author_name)
                if exists:
                    author_name = matchname
                    if exists != authorid:
                        logger.warning(f"{authorid}:{author_name} matches preferred id {exists}:{matchname}")
                    authorid = exists
                logger.debug(f"Scanning {libdir} for preferred name {matchname}")
                matchname = unaccented(matchname).lower()
                for itm in listdir(libdir):
                    match = fuzz.ratio(format_author_name(unaccented(itm),
                                                            get_list(CONFIG.get_csv('NAME_POSTFIX'))),
                                                            matchname,
                                                            processor=default_process)
                    if match >= CONFIG.get_int('NAME_RATIO'):
                        authordir = os.path.join(libdir, itm)
                        fuzzlogger.debug(f"Fuzzy match folder {round(match, 2)}% {itm} for {author_name}")
                        # TODO Add this name variant as an aka if not already there?
                        break

            if not path_isdir(authordir):
                logger.debug(f"[{authordir}] still not found")
                # if still not found, see if we have a book by them, and what directory it's in
                if library == 'AudioBook':
                    sourcefile = 'AudioFile'
                else:
                    sourcefile = 'BookFile'
                cmd = f"SELECT {sourcefile} from books where AuthorID=? and {sourcefile} <> ''"
                anybook = db.match(cmd, (authorid,))
                if anybook:
                    logger.debug(f"Found {sourcefile} {anybook[sourcefile]} for {authorid}:{author_name}")
                    authordir = safe_unicode(os.path.dirname(os.path.dirname(anybook[sourcefile])))
                else:
                    logger.debug(f"No {sourcefile} in library for {authorid}:{author_name}")

            if path_isdir(authordir):
                remv = CONFIG.get_bool('FULL_SCAN')
                logger.debug(f"Using [{authordir}] for {authorid}:{author_name}")
                try:
                    threading.Thread(target=library_scan, name=f'AUTHOR_SCAN_{authorid}',
                                     args=[authordir, library, authorid, remv]).start()
                except Exception as e:
                    logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
            else:
                # maybe we don't have any of their books
                logger.warning(f'Unable to find author directory: {authordir}')
            db.close()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}&library={library}")
        logger.debug(f'ScanAuthor Invalid authorid [{authorid}]')
        db.close()
        raise cherrypy.HTTPError(404, f"AuthorID {authorid} not found")

    @cherrypy.expose
    @require_auth()
    def add_author(self, authorname):
        threading.Thread(target=add_author_name_to_db, name='ADDAUTHOR',
                         args=[authorname, False, True, f'WebServer add_author {authorname}']).start()
        time.sleep(2)  # so we get some data before going to authorpage
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def add_author_id(self, authorid, authorname=''):
        threading.Thread(target=add_author_to_db, name='ADDAUTHORID',
                         args=[authorname, False, authorid, True, f'WebServer add_author_id {authorid}']).start()
        time.sleep(2)  # so we get some data before going to authorpage
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def toggle_auth(self):
        if lazylibrarian.IGNORED_AUTHORS:  # show ignored/paused ones, or active/wanted ones
            lazylibrarian.IGNORED_AUTHORS = False
        else:
            lazylibrarian.IGNORED_AUTHORS = True
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def toggle_primary(self, page=None, authorid=None):
        if lazylibrarian.PRIMARY_AUTHORS:  # show primary ones, or all
            lazylibrarian.PRIMARY_AUTHORS = False
        else:
            lazylibrarian.PRIMARY_AUTHORS = True
        if not page:
            page = 'home'
        if authorid:
            redirect = f"{page}?authorid={authorid}"
        else:
            redirect = page
        raise cherrypy.HTTPRedirect(redirect)

    @cherrypy.expose
    @require_auth()
    def edit_author(self, authorid=None, images=False):
        self.label_thread('EDIT_AUTHOR')
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        user = 0
        email = ''
        user = owner_id()
        if user:
            res = db.match('SELECT SendTo from users where UserID=?', (user,))
            if res and res['SendTo']:
                email = res['SendTo']
        try:
            data = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        finally:
            db.close()
        if data:
            photos = []
            if images:
                res = get_author_image(authorid=authorid, refresh=False, max_num=5)
                if res and path_isdir(res):
                    basedir = res.replace(DIRS.DATADIR, '').lstrip('/')
                    for itm in listdir(res):
                        photos.append([itm, os.path.join(basedir, itm)])
            return serve_template(templatename="editauthor.html", title=i18n.gettext("Edit Author"), config=data,
                                  showseries=CONFIG.get_int('SERIES_TAB'), user=user, email=email,
                                  images=photos)
        logger.info(f'Missing author {authorid}')
        return None

    # noinspection PyUnusedLocal
    # kwargs needed for passing utf8 hidden input
    @cherrypy.expose
    @require_auth()
    def author_update(self, authorid='', authorname='', authorborn='', authordeath='', authorimg='',
                      editordata='', manual='0', aka='', amazonauthorurl='', **kwargs):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authdata = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        if authdata:
            edited = ""
            if not authorborn or authorborn == 'None':
                authorborn = None
            if not authordeath or authordeath == 'None':
                authordeath = None
            if authorimg == 'None':
                authorimg = ''
            manual = bool(check_int(manual, 0))

            if authdata["AuthorBorn"] != authorborn:
                edited += "Born "
            if authdata["AKA"] != aka:
                edited += "AKA "
            if (authdata["AmazonAuthorURL"] or '') != amazonauthorurl:
                edited += "AmazonURL "
            if authdata["AuthorDeath"] != authordeath:
                edited += "Died "
            if 'cover' in kwargs:
                if kwargs['cover'] == "manual":
                    if authorimg and (authdata["AuthorImg"] != authorimg):
                        edited += "Image manual"
                elif kwargs['cover'] != "current":
                    authorimg = os.path.join(DIRS.DATADIR, kwargs['cover'])
                    edited += f"Image {kwargs['cover']} "

            if authdata["About"] != editordata:
                edited += "Description "
            if bool(check_int(authdata['Manual'], 0)) != manual:
                edited += "Manual "

            if authdata["AuthorName"] != authorname:
                match = db.match('SELECT AuthorName from authors where AuthorName=?', (authorname,))
                if match:
                    logger.debug(f"Unable to rename, new author name {authorname} already exists")
                    authorname = authdata["AuthorName"]
                else:
                    edited += "Name "

            if edited:
                # Check dates, format to yyyy/mm/dd
                # use None to clear date
                # Leave unchanged if fails datecheck
                if authorborn is not None:
                    ab = date_format(authorborn, context=authorname, datelang=CONFIG['DATE_LANG'])
                    if len(ab) == 10:
                        authorborn = ab
                    else:
                        logger.warning(f"Author Born date [{authorborn}] rejected")
                        authorborn = authdata["AuthorBorn"]  # leave unchanged
                        edited = edited.replace('Born ', '')

                if authordeath is not None:
                    ab = date_format(authordeath, context=authorname, datelang=CONFIG['DATE_LANG'])
                    if len(ab) == 10:
                        authordeath = ab
                    else:
                        logger.warning(f"Author Died date [{authordeath}] rejected")
                        authordeath = authdata["AuthorDeath"]  # leave unchanged
                        edited = edited.replace('Died ', '')

                if not authorimg:
                    authorimg = authdata["AuthorImg"]
                else:
                    if authorimg == 'none':
                        authorimg = os.path.join(DIRS.PROG_DIR, 'data', 'images', 'nophoto.png')

                    rejected = True

                    if authorimg.startswith('http'):
                        # cache image from url
                        authorimg, success, _ = cache_img(ImageType.AUTHOR, img_id(), authorimg, refresh=True)
                        if success:
                            rejected = False
                    else:
                        # Cache file image
                        if not path_isfile(authorimg):
                            logger.warning(f"Failed to find file {authorimg}")
                        else:
                            extn = splitext(authorimg)[1].lower()
                            if extn and extn in ['.jpg', '.jpeg', '.png', '.webp']:
                                image_id = img_id()
                                destfile = os.path.join(DIRS.CACHEDIR, 'author', image_id + '.jpg')
                                try:
                                    copyfile(authorimg, destfile)
                                    logger.debug(f"{authorimg}->{destfile}")
                                    setperm(destfile)
                                    authorimg = 'cache/author/' + image_id + '.jpg'
                                    rejected = False
                                except Exception as why:
                                    logger.warning(
                                        f"Failed to copy file {authorimg}, {type(why).__name__} {str(why)}")
                            else:
                                logger.warning(f"Invalid extension on [{authorimg}]")

                    if rejected:
                        logger.warning(f"Author Image [{authorimg}] rejected")
                        authorimg = authdata["AuthorImg"]
                        edited = edited.replace('Image ', '')

                control_value_dict = {'AuthorID': authorid}
                new_value_dict = {
                    'AuthorName': authorname,
                    'AuthorBorn': authorborn,
                    'AuthorDeath': authordeath,
                    'AuthorImg': authorimg,
                    'About': editordata,
                    'AKA': aka,
                    'AmazonAuthorURL': amazonauthorurl,
                    'Manual': bool(manual)
                }
                db.upsert("authors", new_value_dict, control_value_dict)
                logger.info(f'Updated [ {edited}] for {authorname}')

            else:
                logger.debug(f'Author [{authorname}] has not been changed')
        db.close()

        icrawlerdir = os.path.join(DIRS.CACHEDIR, 'icrawler', authorid)
        rmtree(icrawlerdir, ignore_errors=True)
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @staticmethod
    def author_linkable_sources():
        """ Sources that expose a per-author ID and a uniform find_author_id()/
        get_author_info() pair (unlike GoogleBooks/DNB, which are book-search-only -
        see gb.py/dnb.py, neither has find_author_id). These are the only sources that
        can be linked to an author record or chosen as an author's PrimarySource.
        Derived from lazylibrarian.INFOSOURCES at call time, not class-definition time -
        webServe is imported before startup.init_build_lists() populates INFOSOURCES. """
        return {name: src['author_key'] for name, src in lazylibrarian.INFOSOURCES.items()
                if src['author_key'] != 'authorid'}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def search_author_source(self, authorid, source):
        """ AJAX: search a single source for this author by name, return the best
        candidate (if any) for the edit-author screen to show for confirmation.
        Does not write anything - see link_author_source for that. """
        logger = logging.getLogger(__name__)
        if source not in self.author_linkable_sources():
            return {'error': f'{source} does not support author search'}
        db = database.DBConnection()
        author = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
        db.close()
        if not author:
            return {'error': f'Author {authorid} not found'}
        if source not in lazylibrarian.INFOSOURCES:
            return {'error': f'{source} is not a configured source'}
        inf_source = lazylibrarian.INFOSOURCES[source]
        if not CONFIG[inf_source['enabled']]:
            return {'error': f'{source} is not enabled in Config -> Importing'}
        api = inf_source['api']()
        try:
            result = api.find_author_id(authorname=author['AuthorName'])
        except Exception as e:
            logger.error(f"search_author_source {source} error for author {authorid}: {e}")
            return {'error': f'{source} search failed, check the logs'}
        if not result or not result.get('authorid'):
            return {'found': False}
        return {'found': True, 'authorid': result.get('authorid'), 'authorname': result.get('authorname'),
                'authorlink': result.get('authorlink')}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def link_author_source(self, authorid, source, sourceid):
        """ AJAX: persist a user-confirmed source ID against this author. Does not
        change PrimarySource - see set_primary_source for that. Also fetches and
        stores that source's own author-page link immediately (into its INFOSOURCES
        author_link column) rather than waiting for the next scheduled refresh to
        backfill it via get_all_author_details(). """
        logger = logging.getLogger(__name__)
        if source not in self.author_linkable_sources():
            return {'error': f'{source} cannot be linked to an author'}
        if not sourceid:
            return {'error': 'No source id supplied'}
        column = self.author_linkable_sources()[source]
        if source == 'DBK':
            # accept the bare number or the author page link, stored as DBK<number>
            sourceid = dbk.DBK.author_id_from_text(sourceid)
            if not sourceid:
                return {'error': 'Not a Databazeknih author id or link'}
        db = database.DBConnection()
        author = db.match('SELECT AuthorID,AuthorName from authors WHERE AuthorID=?', (authorid,))
        if not author:
            db.close()
            return {'error': f'Author {authorid} not found'}
        updates = {column: sourceid}
        link_column = lazylibrarian.INFOSOURCES[source].get('author_link')
        if link_column:
            inf_source = lazylibrarian.INFOSOURCES[source]
            api = inf_source['api']()
            try:
                info = api.get_author_info(authorid=sourceid, authorname=author['AuthorName'])
            except Exception as e:
                logger.error(f"link_author_source {source} lookup error for author {authorid}: {e}")
                info = None
            if info and info.get('authorlink'):
                updates[link_column] = info['authorlink']
        db.upsert('authors', updates, {'AuthorID': authorid})
        db.close()
        logger.info(f"Linked author {authorid} to {source} id {sourceid}")
        return {'success': True, 'column': column, 'value': sourceid}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def set_primary_source(self, authorid, source):
        """ Mark one of an author's already-linked sources as their primary - drives the
        author-page name link and source badge. Re-fetches the canonical link for the
        stored id rather than guessing a URL template, so AuthorLink always matches
        whatever that source's own get_author_info() would build. """
        logger = logging.getLogger(__name__)
        if source not in self.author_linkable_sources():
            return {'error': f'{source} cannot be a primary source'}
        column = self.author_linkable_sources()[source]
        db = database.DBConnection()
        author = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        if not author:
            db.close()
            return {'error': f'Author {authorid} not found'}
        sourceid = author[column]
        if not sourceid:
            db.close()
            return {'error': f'Author is not linked to {source} yet'}
        inf_source = lazylibrarian.INFOSOURCES[source]
        api = inf_source['api']()
        try:
            info = api.get_author_info(authorid=sourceid, authorname=author['AuthorName'])
        except Exception as e:
            logger.error(f"set_primary_source {source} lookup error for author {authorid}: {e}")
            info = None
        authorlink = info.get('authorlink') if info else ''
        updates = {'PrimarySource': source}
        if authorlink:
            updates['AuthorLink'] = authorlink
            link_column = lazylibrarian.INFOSOURCES[source].get('author_link')
            if link_column:
                updates[link_column] = authorlink
        db.upsert('authors', updates, {'AuthorID': authorid})
        db.close()
        logger.info(f"Set primary source for author {authorid} to {source}")
        return {'success': True, 'authorlink': authorlink}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def unlink_author_source(self, authorid, source):
        """ AJAX: clear a linked source id so it can be searched (and linked to a
        different match) again. Also clears that source's own INFOSOURCES author_link
        entry - a stale link to a source that's no longer linked would show as a
        dead/misleading clickable entry in the author page's source list. If this
        was the author's PrimarySource, clears that too AND clears AuthorLink -
        leaving AuthorLink pointing at a source that's no longer linked would be
        stale/misleading (it's what the author-page name link itself uses), not
        just cosmetically wrong on the badge. Falls back to the priority order
        (same as an author nobody's set a primary for) until the user picks a new
        one. """
        logger = logging.getLogger(__name__)
        if source not in self.author_linkable_sources():
            return {'error': f'{source} cannot be unlinked'}
        column = self.author_linkable_sources()[source]
        db = database.DBConnection()
        author = db.match('SELECT AuthorID, PrimarySource from authors WHERE AuthorID=?', (authorid,))
        if not author:
            db.close()
            return {'error': f'Author {authorid} not found'}
        updates = {column: ''}
        link_column = lazylibrarian.INFOSOURCES[source].get('author_link')
        if link_column:
            updates[link_column] = ''
        if author['PrimarySource'] == source:
            updates['PrimarySource'] = ''
            updates['AuthorLink'] = ''
        db.upsert('authors', updates, {'AuthorID': authorid})
        db.close()
        logger.info(f"Unlinked {source} from author {authorid}")
        return {'success': True}
