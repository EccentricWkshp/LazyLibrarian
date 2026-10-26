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

import logging
import time
import traceback

import cherrypy

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_float, check_int, date_format
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    ServiceError,
    authors,
    books,
    users,
)
from lazylibrarian.services.system import book_libraries
from lazylibrarian.web import common
from lazylibrarian.web.common import BasePages, mark_summary, serve_template

# books.html's columns, by the field each one sorts on
BOOK_COLUMNS = ('altsub', 'BookImg', 'AuthorSort', 'TitleSort', 'altsub', 'BookRate', 'BookDate', 'BookLibrary',
                'Status', 'BookLang', 'BookSub', 'BookLink', 'WorkPage', 'AuthorID', 'SeriesDisplay', 'BookLibrary',
                'AudioStatus', 'AudioLibrary', 'series', 'BookGenre', 'BookAdded', 'ScanResult', 'LT_WorkID',
                'altsub')
READING_FLAGS = {'ToRead': '&nbsp;<i class="far fa-bookmark"></i>', 'HaveRead': '&nbsp;<i class="fas fa-bookmark"></i>',
                 'Reading': '&nbsp;<i class="fas fa-play-circle"></i>', 'Abandoned': '&nbsp;<i class="fas fa-ban"></i>'}


def book_sort(column: int, source: str, library: str) -> str:
    """ The field a books.html column sorts on, the added and status columns depend on the list """
    if column == 7:  # added or listed
        if source == "Manage":
            return 'BookAdded'
        return 'AudioLibrary' if library == 'AudioBook' else 'BookLibrary'
    if column == 8:  # status
        return 'AudioStatus' if library == 'AudioBook' else 'Status'
    return BOOK_COLUMNS[column]


class BookPages(BasePages):
    """ The ebook and audiobook lists, book pages and edits, searching and marking books """

    @cherrypy.expose
    @require_auth()
    def refresh_book(self, bookid):
        try:
            books.refresh_book(bookid)
        except NotFoundError as e:
            raise cherrypy.HTTPError(404, str(e)) from None
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
            searchterm = f'{author} {title}'.strip()

        if action.startswith('e_'):
            cat = 'book'
        elif action.startswith('a_'):
            cat = 'audio'
        elif action:
            cat = 'general'
        else:  # legacy interface
            cat = 'book'

        results = books.search_providers(searchterm, bookid, cat)
        library = 'AudioBook' if action.startswith('a_') else 'eBook'
        return serve_template(templatename="manualsearch.html",
                              title=i18n.gettext('%(library)s Search Results: "%(query)s"') % {
                                  'library': i18n.status_label(library), 'query': searchterm},
                              bookid=bookid, results=results, library=library)

    @cherrypy.expose
    @require_auth()
    def count_providers(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        count = CONFIG.total_active_providers()
        return f"Searching {count} providers, please wait..."

    @cherrypy.expose
    @require_auth()
    def snatch_book(self, bookid=None, mode=None, provider=None, url=None, size=None, library=None, title=''):
        try:
            author_id, _, _ = books.snatch(bookid, mode, provider, url, size, library, title)
        except NotFoundError as e:
            logging.getLogger(__name__).debug(f'snatch_book Invalid bookid [{bookid}]')
            raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}&library={library}")

    @cherrypy.expose
    @require_auth()
    def audio(self, booklang=None, book_filter=''):
        return self.book_list('AudioBook', "audio.html", i18n.gettext('AudioBooks'), booklang, book_filter)

    @cherrypy.expose
    @require_auth()
    def books(self, booklang=None, book_filter=''):
        return self.book_list('eBook', "books.html", i18n.gettext('eBooks'), booklang, book_filter)

    @staticmethod
    def book_list(library, templatename, title, booklang, book_filter):
        user = owner_id()
        if not booklang or booklang == 'None':
            booklang = None
        return serve_template(templatename=templatename, title=title, books=[],
                              languages=books.book_languages(library), booklang=booklang, user=user,
                              email=users.send_to(user), book_filter=book_filter)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_books(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        source = kwargs['source']
        rows = []
        page = None
        # noinspection PyBroadException
        try:
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            userprefs = 0
            cookie = cherrypy.request.cookie
            if cookie and 'll_prefs' in list(cookie.keys()):
                userprefs = check_int(cookie['ll_prefs'].value, 0)
            userid = owner_id()
            types = book_libraries()
            library = None
            if types:
                library = kwargs['library'] if kwargs.get('library') in types else types[0]
            page = books.list_books(
                source, library=library, status=kwargs.get('whichStatus', 'All'), authorid=kwargs.get('AuthorID'),
                ignored=kwargs.get('ignored') == "True", booklang=kwargs.get('booklang', ''), userid=userid,
                subscribed_only=bool(userprefs & lazylibrarian.pref_myfeeds or userprefs & lazylibrarian.pref_myafeeds),
                primary_only=bool(lazylibrarian.PRIMARY_AUTHORS), search=sSearch,
                sort=book_sort(int(iSortCol_0), source, library), descending=sSortDir_0 == "desc",
                offset=int(iDisplayStart), limit=displaylength)
            rows = [self.book_row(book, source, library) for book in page.items if book['TitleSort']]
            serversidelogger.debug(f"get_books filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_books: {traceback.format_exc()}')
            rows = []
            page = None

        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  }
        if source == 'Author':
            try:
                mydict['loading'] = authors.get_author(kwargs['AuthorID'])['Status'] == 'Loading'
            except NotFoundError:
                mydict['loading'] = False
        elif source == 'Books':
            mydict['loading'] = lazylibrarian.EBOOK_UPDATE
        elif source == 'Audio':
            mydict['loading'] = lazylibrarian.AUDIO_UPDATE
        serversidelogger.debug(str(mydict))
        return mydict

    @staticmethod
    def book_row(book, source, library) -> list:
        """ A book as the row books.html, audio.html, author.html and managebooks.html show """
        if CONFIG.get_bool('RATESTARS'):
            bookrate = min(int(round(check_float(book['BookRate'], 0.0))), 5)
        else:
            bookrate = book['BookRate']

        worklink = ''
        if book['LT_WorkID']:  # is there a librarything workid
            worklink = f'<a href="{CONFIG["LT_URL"]}/work/{book["LT_WorkID"]}"><small><i>LibraryThing</i></small></a>'
        elif book['WorkPage']:  # is there a workpage link
            worklink = f'<a href="{book["WorkPage"]}" ><small><i>LibraryThing</i></small></a>'

        sitelink = ''
        booklink = book['BookLink'] or ''
        if booklink.startswith('/works/OL'):
            sitelink = f'<a href="{CONFIG["OL_URL"] + booklink}"><small><i>OpenLibrary</i></small></a>'
        elif 'goodreads' in booklink:
            sitelink = f'<a href="{booklink}"><small><i>GoodReads</i></small></a>'
        elif 'hardcover' in booklink:
            sitelink = f'<a href="{booklink}"><small><i>HardCover</i></small></a>'
        elif 'books.google.com' in booklink or 'market.android.com' in booklink:
            sitelink = f'<a href="{booklink}"><small><i>GoogleBooks</i></small></a>'

        title = book['TitleSort']
        subtitle = book['BookSub']
        if subtitle and ' #' not in subtitle and subtitle != "None":  # is there a subtitle that's not series info
            title = f'{title}<br><small><i>{subtitle}</i></small>'
        title = title + '<br>' + sitelink + ' ' + worklink
        if lazylibrarian.perm_admin & lazylibrarian.perm_edit:
            title += (f' <a href="edit_book?bookid={book["BookID"]}&library={library}"><small><i>'
                      f'{i18n.gettext("Manual")}</i></a>')

        genre = book['BookGenre']
        if CONFIG.get_bool('SHOW_GENRES') and genre and genre != 'Unknown':
            genres = ''
            for a in genre.split(','):
                if source == "Audio":
                    genres += f' <a href=\'audio?book_filter={a.strip()}\'">{a.strip()}</a>'
                elif source == "Books":
                    genres += f' <a href=\'books?book_filter={a.strip()}\'">{a.strip()}</a>'
                elif source in ["Author", "Manage"]:
                    genres += (f' <a href=\'author_page?authorid={book["AuthorID"]}&book_filter={a.strip()}\'">'
                               f'{a.strip()}</a>')
            genres = genres.strip()
            if genres:
                title += ' [' + genres + ']'

        status = book['Status']
        added = book['BookLibrary']
        if library == 'AudioBook' and source == 'Audio':
            status = book['AudioStatus']
            added = book['AudioLibrary']

        # Need to pass bookid and status twice for legacy as datatables modifies first one
        row = [book['BookID'], book['BookImg'], book['AuthorSort'], title, book['SeriesDisplay'], bookrate,
               date_format(book['BookDate'], context=book['BookID'], datelang=CONFIG['DATE_LANG']),
               status, book['AuthorID'], book['BookID'],
               date_format(added, CONFIG['DATE_FORMAT'], context=book['BookID'], datelang=CONFIG['DATE_LANG']),
               status, book['series'], READING_FLAGS.get(book['ReadingList'], '')]
        if source == "Manage":
            searches = book['FailedSearch']
            if searches:
                row.append(f"{searches['Count']}/{searches['Interval']}")
                try:
                    row.append(time.strftime("%d %b %Y", time.localtime(float(searches['Time']))))
                except (ValueError, TypeError):
                    row.append('')
            else:
                row.append('0')
                row.append('')
        elif source == 'Author':
            row.append(book['AudioStatus'])
            row.append(date_format(book['AudioLibrary'], CONFIG['DATE_FORMAT'], context=book['BookID'],
                                   datelang=CONFIG['DATE_LANG']))
        row.append(book['BookAdded'])
        row.append(book['ScanResult'])
        return row

    @cherrypy.expose
    @require_auth()
    def add_book(self, bookid=None, authorid=None, library=None, source=None):
        author_id, ebook_status, audio_status = books.add_book(bookid, authorid, library, source)
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
        lazylibrarian.services.books.start_search(books, library=library, force=force)

    @cherrypy.expose
    @require_auth()
    def search_for_book(self, bookid=None, library=None):
        try:
            author_id = books.search_for_book(bookid, library)
        except NotFoundError:
            author_id = ''
        if author_id:
            raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def request_book(self, **kwargs):
        self.label_thread('REQUEST_BOOK')
        prefix = ''
        sent = False
        title = i18n.gettext('Request Error')
        userid = owner_id()
        if not userid:
            msg = i18n.gettext("Nobody logged in?")
        else:
            booktype = 'book'
            types = book_libraries()
            if types and kwargs.get('library') in types:
                booktype = kwargs['library']
            try:
                bookname, sent = books.request_book(userid, kwargs['bookid'], kwargs, cherrypy.request.remote.ip)
                title = f"{i18n.status_label(booktype)}: {bookname}"
                if sent:
                    prefix = i18n.gettext("Message sent")
                    msg = i18n.gettext("You will receive a reply by email")
                else:
                    prefix = i18n.gettext("Message not sent")
                    msg = i18n.gettext("Please try again later")
            except InvalidRequestError:
                prefix = i18n.gettext("Unable to send message")
                msg = i18n.gettext("No email address supplied")
            except NotFoundError:
                msg = i18n.gettext("Unknown user")
        return serve_template(templatename="response.html", prefix=prefix, title=title, message=msg,
                              timer=5 if sent else 0)

    @cherrypy.expose
    @require_auth()
    def book_detail(self, bookid=None):
        """ Read-only "master" detail view for a book, replacing the old bookinfo()
        popup (which only ever showed image/title/description via bookdesc) for plain
        book ids - see base.html's bookinfo() for the author/comic cases, unchanged. """
        try:
            details = books.book_details(bookid)
        except NotFoundError:
            raise cherrypy.HTTPRedirect("books") from None
        book = details['book']
        book['BookDate'] = date_format(book['BookDate'], CONFIG['AUTHOR_DATE_FORMAT'],
                                       context=book['BookName'], datelang=CONFIG['DATE_LANG'])
        book['OriginalPubDate'] = date_format(book['OriginalPubDate'], CONFIG['AUTHOR_DATE_FORMAT'],
                                              context=book['BookName'], datelang=CONFIG['DATE_LANG'])
        return serve_template(templatename="book_detail.html", title=book['BookName'], book=book,
                              book_links=details['links'], amazon_link=details['amazon_link'])

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def lookup_book_asin(self, bookid=None):
        """ AJAX: on-demand fetch of a book's ASIN from GoodReads, only when the detail page asks for it """
        try:
            asin = books.lookup_asin(bookid)
        except ServiceError as e:
            return {'error': str(e)}
        if not asin:
            return {'found': False}
        return {'found': True, 'asin': asin, 'link': f'https://www.amazon.com/dp/{asin}'}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def force_language_refresh(self):
        """ AJAX: re-evaluate languages across candidate books in the database, in the background """
        try:
            books.start_language_refresh()
        except InvalidRequestError as e:
            return {'error': str(e)}
        return {'success': True}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def language_refresh_status(self):
        """ AJAX: is a language refresh currently running, and progress counters. """
        return books.language_refresh_status()

    @cherrypy.expose
    @require_auth()
    def edit_book(self, bookid=None, library='eBook', images=False):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_BOOK')
        try:
            edit = books.book_for_edit(bookid, library, bool(images))
        except NotFoundError:
            logging.getLogger(__name__).info(f'Missing book {bookid}')
            return None
        return serve_template(templatename="editbook.html", title=i18n.gettext("Edit Book"), config=edit['book'],
                              seriesdict=edit['seriesdict'], authors=edit['authors'], covers=edit['covers'],
                              replaces=edit['replaces'], series=edit['series'])

    @cherrypy.expose
    @require_auth()
    def book_update(self, bookname='', bookid='', booksub='', bookgenre='', booklang='', bookdate='',
                    manual='0', authorname='', cover='', newid='', editordata='', bookisbn='', workid='',
                    **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if not bookid:
            raise cherrypy.HTTPRedirect("books")
        series = []
        counter = 0
        while f"series[{counter}][name]" in kwargs:
            series.append((kwargs[f"series[{counter}][name]"], kwargs[f"series[{counter}][number]"]))
            counter += 1
        if 'series[new][name]' in kwargs and 'series[new][number]' in kwargs and kwargs['series[new][name]']:
            series.append((kwargs["series[new][name]"], kwargs['series[new][number]']))
        try:
            books.update_book(bookid, bookname, booksub, bookgenre, booklang, bookdate, bool(check_int(manual, 0)),
                              authorname, editordata, bookisbn, workid, cover=cover, newid=newid, series=series,
                              opf_values=kwargs, import_from=kwargs.get('importfrom', ''))
        except NotFoundError:
            raise cherrypy.HTTPRedirect("books") from None
        except ServiceError:
            pass  # the import failed, back to the edit page
        raise cherrypy.HTTPRedirect(f"edit_book?bookid={bookid}")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_results_ajax(self, **args):
        action = args.pop('action', 'unknown action')
        redirect = args.pop('redirect', '')
        passed, failed = books.add_search_results(action, set(args.keys()))
        summary = mark_summary(i18n.gettext("Mark Results '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': passed + failed,
            'summary': summary,
            'redirect': redirect
        }

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_books_ajax(self, authorid=None, seriesid=None, action=None, redirect=None, **args):
        book_filter = args.get('bookfilter')
        library = args.get('library', 'AudioBook' if redirect == 'audio' else 'eBook')
        if 'marktype' in args:
            library = args['marktype']
        if 'AuthorID' in args and authorid is None:
            authorid = args['AuthorID']
        for arg in ['book_table_length', 'ignored', 'library', 'booklang', 'marktype', 'AuthorID', 'bookfilter']:
            args.pop(arg, None)
        if not self.valid_source(redirect):
            redirect = "books"

        result = books.mark_books(action, list(args), library=library,
                                  userid=owner_id() if action in books.READING_ACTIONS else None,
                                  authorid=authorid if redirect == 'author' else None)
        authorid = result['authorid'] or authorid

        if redirect == "author":
            if 'eBook' in library:
                redirect = f"author_page?authorid={authorid}&library=eBook"
            if 'AudioBook' in library:
                redirect = f"author_page?authorid={authorid}&library=AudioBook"
        elif redirect in ["books", "audio"]:
            pass
        elif redirect == "members":
            redirect = f"series_members?seriesid={seriesid}&ignored=False"
        elif 'AudioBook' in library:
            redirect = "manage?library=AudioBook"
        else:
            redirect = "manage?library=eBook"
        if book_filter:
            redirect = f"{redirect}&book_filter={book_filter}"
        passed, failed = result['passed'], result['failed']
        summary = mark_summary(i18n.gettext("Mark Books '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': passed + failed,
            'summary': summary,
            'redirect': redirect
        }

    @cherrypy.expose
    @require_auth()
    def bookdesc(self, bookid=None):
        found = books.description(bookid) if bookid else None
        if found and found['AuthorID']:
            common.lastauthor = found['AuthorID']
        img = (found and found['img']) or 'images/nocover.jpg'
        title = (found and found['title']) or i18n.gettext('BookID not found')
        text = (found and found['text']) or i18n.gettext('No Description')
        return img + '^' + title + '^' + text

    @cherrypy.expose
    @require_auth()
    def manage(self, **kwargs):
        types = book_libraries()
        if not types:
            raise cherrypy.HTTPRedirect('authors')
        library = kwargs['library'] if kwargs.get('library') in types else types[0]
        which_status = kwargs.get('whichStatus') or 'Wanted'
        if which_status == 'None':
            which_status = "Wanted"
        return serve_template(templatename="managebooks.html",
                              title=i18n.gettext('Manage AudioBooks') if library == 'AudioBook'
                              else i18n.gettext('Manage eBooks'),
                              books=[], types=types, library=library, whichStatus=which_status)
