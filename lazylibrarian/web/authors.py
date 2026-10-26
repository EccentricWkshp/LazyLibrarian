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

import contextlib
import datetime
import logging
import traceback

import cherrypy

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, date_format
from lazylibrarian.services import InvalidRequestError, NotFoundError, ServiceError, authors, users
from lazylibrarian.services.system import book_libraries
from lazylibrarian.web import common
from lazylibrarian.web.common import BasePages, mark_summary, serve_template

# index.html's columns, the checkbox column sorts by the source badge
INDEX_COLUMNS = ('BadgeSource', 'AuthorImg', 'NameSort', 'DateAdded', 'LastBookSort', 'LastDate', 'Percent',
                 'Status', 'AuthorLink', 'LastLink', 'HaveBooks', 'UnignoredBooks', 'AuthorID', 'LastBookID')


class AuthorPages(BasePages):
    """ The author list, author pages, author edits and source links, and the search box """

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
        page = None
        # noinspection PyBroadException
        try:
            userprefs = 0
            cookie = cherrypy.request.cookie
            if cookie and 'll_prefs' in list(cookie.keys()):
                userprefs = check_int(cookie['ll_prefs'].value, 0)
            userid = owner_id()
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            page = authors.list_authors(
                search=sSearch, sort=INDEX_COLUMNS[int(iSortCol_0)], descending=sSortDir_0 == "desc",
                offset=int(iDisplayStart), limit=displaylength, ignored=bool(lazylibrarian.IGNORED_AUTHORS),
                primary_only=bool(lazylibrarian.PRIMARY_AUTHORS),
                subscriber=userid if userid and userprefs & lazylibrarian.pref_myauthors else None)
            rows = [self.index_row(author) for author in page.items]
            serversidelogger.debug(f"get_index filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_index: {traceback.format_exc()}')
            rows = []
            page = None
        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  'loading': lazylibrarian.AUTHORS_UPDATE,
                  'searching': lazylibrarian.SEARCHING,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @staticmethod
    def index_row(author) -> list:
        """ An author as the row index.html shows """
        row = [author[field] for field in ('AuthorImg', 'NameSort', 'LastBookSort', 'LastDate', 'Percent', 'Status',
                                           'AuthorLink', 'LastLink', 'HaveBooks', 'UnignoredBooks', 'AuthorID',
                                           'LastBookID')]
        row.append('')  # the progress bar is drawn by the page
        # format DateAdded only now, as the display format may not sort as text
        row.append(date_format(author['DateAdded'], CONFIG['DATE_FORMAT'], context=author['NameSort'],
                               datelang=CONFIG['DATE_LANG']))
        row.append(author['AddedReason'])
        # Same source-badge convention as author.html/editauthor.html: the explicitly-confirmed
        # PrimarySource is linked, as AuthorLink is guaranteed to match it; one inferred from the
        # priority order is plain text, as there's no verified matching URL for a guess.
        badge = author['BadgeSource']
        if author['PrimarySource']:
            row.append(f'<a href="{author["AuthorLink"]}" target="_blank" rel="noreferrer">'
                       f'<small><i>{badge}</i></small></a>')
        elif badge:
            row.append(f'<small><i>{badge}</i></small>')
        else:
            row.append('')
        return row

    @cherrypy.expose
    @require_auth()
    def search(self, searchfor, btnsearch=None):
        logger = logging.getLogger('special.searching')
        logger.debug(f"Search {btnsearch}: {searchfor}")
        self.label_thread('SEARCH')
        if not searchfor:
            raise cherrypy.HTTPRedirect("home")
        if not self.validate_param("searchfor", searchfor, ['<', '>', '='], None):
            raise cherrypy.HTTPRedirect("home")
        if searchfor.lower().startswith('authorid:'):
            self.add_author_id(searchfor[9:])
            return None
        if searchfor.lower().startswith('bookid:'):
            self.add_book(searchfor[7:])
            return None
        found = authors.search_sources(searchfor)
        return serve_template(templatename="searchresults.html",
                              title=i18n.gettext('Search Results: "%(query)s"') % {'query': searchfor},
                              searchresults=found['results'], authorlist=found['authorlist'],
                              loadlist=found['loadlist'], booklist=found['booklist'], booksearch=found['booksearch'])

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_authors_ajax(self, action=None, **args):
        for arg in ['author_table_length', 'series_table_length', 'book_table_length', 'ignored', '_', 'action',
                    'which_status']:
            args.pop(arg, None)
        passed, failed = authors.mark_authors(action, list(args), userid=owner_id())
        summary = mark_summary(i18n.gettext("Mark Authors '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': passed + failed,
            'summary': summary
        }

    @cherrypy.expose
    @require_auth()
    def author_page(self, authorid, book_lang=None, library='eBook', ignored=False, **args):
        user = owner_id()
        email = users.send_to(user)
        try:
            author = authors.get_author(authorid, any_source_id=True)
        except NotFoundError:
            raise cherrypy.HTTPRedirect("authors") from None
        languages = authors.author_languages(authorid, ignored=bool(ignored))

        types = book_libraries()
        if types and library not in types:
            library = types[0]
        if not types:
            library = None

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
            book_filter=args.get('book_filter', ''), gb_search_link=authors.gb_search_link(authorname),
            amazon_search_link=authors.amazon_search_link(authorname))

    @cherrypy.expose
    @require_auth()
    def author_detail(self, authorid):
        """ Read-only "master" detail view for an author, linked from the author
        name on author_page. Surfaces fields that exist in the authors table but
        have never had anywhere to display on the read-only side (AKA, About,
        DateAdded, Updated, ...) - see author_page for the book-listing view. """
        user = owner_id()
        email = users.send_to(user)
        try:
            details = authors.author_details(authorid)
        except NotFoundError:
            raise cherrypy.HTTPRedirect("authors") from None
        author = details['author']
        authorname = author['AuthorName']
        if not authorname:  # still loading?
            raise cherrypy.HTTPRedirect("authors")

        author['AuthorBorn'] = date_format(author['AuthorBorn'], CONFIG['AUTHOR_DATE_FORMAT'],
                                           context=authorname, datelang=CONFIG['DATE_LANG'])
        author['AuthorDeath'] = date_format(author['AuthorDeath'], CONFIG['AUTHOR_DATE_FORMAT'],
                                            context=authorname, datelang=CONFIG['DATE_LANG'])
        if author.get('Updated'):
            author['Updated'] = datetime.datetime.fromtimestamp(int(author['Updated'])).strftime('%Y-%m-%d %H:%M')

        return serve_template(templatename="author_detail.html", title=authorname, author=author,
                              showseries=CONFIG.get_int('SERIES_TAB'), user=user, email=email,
                              librarian_note=details['librarian_note'],
                              gb_search_link=authors.gb_search_link(authorname),
                              author_age=details['age'], ebook_status_counts=details['ebook_status_counts'],
                              audio_status_counts=details['audio_status_counts'],
                              about_by_source=details['about_by_source'],
                              source_book_counts=details['source_book_counts'],
                              amazon_search_link=authors.amazon_search_link(authorname))

    @cherrypy.expose
    @require_auth()
    def set_author(self, authorid, status):
        try:
            authors.set_status(authorid, status)
        except NotFoundError as e:
            logging.getLogger(__name__).debug(f'set_author Invalid authorid [{authorid}]')
            raise cherrypy.HTTPError(404, str(e)) from None
        except InvalidRequestError as e:
            raise cherrypy.HTTPError(400, str(e)) from None
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

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
        # an author still loading may not be there yet
        with contextlib.suppress(NotFoundError):
            authors.remove_author(authorid)
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def refresh_author(self, authorid):
        try:
            authors.refresh_author(authorid)
        except NotFoundError as e:
            logging.getLogger(__name__).debug(f'refresh_author Invalid authorid [{authorid}]')
            raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def follow_author(self, authorid):
        self.follow(authorid, True)

    @cherrypy.expose
    @require_auth()
    def unfollow_author(self, authorid):
        self.follow(authorid, False)

    @staticmethod
    def follow(authorid, follow):
        try:
            authors.follow_author(authorid, follow)
        except NotFoundError as e:
            logging.getLogger(__name__).error(str(e))
            raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def library_scan_author(self, authorid, **kwargs):
        types = book_libraries()
        try:
            if not types:
                authors.get_author(authorid)
                raise cherrypy.HTTPRedirect('authors')
            library = kwargs['library'] if kwargs.get('library') in types else types[0]
            authorid = authors.start_author_scan(authorid, library)
        except NotFoundError as e:
            logging.getLogger(__name__).debug(f'ScanAuthor Invalid authorid [{authorid}]')
            raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}&library={library}")

    @cherrypy.expose
    @require_auth()
    def add_author(self, authorname):
        authors.add_author_by_name(authorname)
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def add_author_id(self, authorid, authorname=''):
        authors.add_author_by_id(authorid, authorname)
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def toggle_auth(self):
        # show ignored/paused ones, or active/wanted ones
        lazylibrarian.IGNORED_AUTHORS = not lazylibrarian.IGNORED_AUTHORS
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def toggle_primary(self, page=None, authorid=None):
        # show primary ones, or all
        lazylibrarian.PRIMARY_AUTHORS = not lazylibrarian.PRIMARY_AUTHORS
        if not page:
            page = 'home'
        if authorid:
            raise cherrypy.HTTPRedirect(f"{page}?authorid={authorid}")
        raise cherrypy.HTTPRedirect(page)

    @cherrypy.expose
    @require_auth()
    def edit_author(self, authorid=None, images=False):
        self.label_thread('EDIT_AUTHOR')
        user = owner_id()
        email = users.send_to(user)
        try:
            data = authors.get_author(authorid)
        except NotFoundError:
            logging.getLogger(__name__).info(f'Missing author {authorid}')
            return None
        photos = authors.author_images(authorid) if images else []
        return serve_template(templatename="editauthor.html", title=i18n.gettext("Edit Author"), config=data,
                              showseries=CONFIG.get_int('SERIES_TAB'), user=user, email=email, images=photos)

    # noinspection PyUnusedLocal
    # kwargs needed for passing utf8 hidden input
    @cherrypy.expose
    @require_auth()
    def author_update(self, authorid='', authorname='', authorborn='', authordeath='', authorimg='',
                      editordata='', manual='0', aka='', amazonauthorurl='', **kwargs):
        with contextlib.suppress(NotFoundError):
            authors.update_author(authorid, authorname,
                                  born=None if not authorborn or authorborn == 'None' else authorborn,
                                  died=None if not authordeath or authordeath == 'None' else authordeath,
                                  image='' if authorimg == 'None' else authorimg, about=editordata,
                                  manual=bool(check_int(manual, 0)), aka=aka, amazon_url=amazonauthorurl,
                                  cover=kwargs.get('cover'))
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def search_author_source(self, authorid, source):
        """ AJAX: search a single source for this author by name, return the best
        candidate (if any) for the edit-author screen to show for confirmation.
        Does not write anything - see link_author_source for that. """
        try:
            result = authors.search_source(authorid, source)
        except ServiceError as e:
            return {'error': str(e)}
        if not result:
            return {'found': False}
        return {'found': True, **result}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def link_author_source(self, authorid, source, sourceid):
        """ AJAX: persist a user-confirmed source ID against this author """
        try:
            column, value = authors.link_source(authorid, source, sourceid)
        except ServiceError as e:
            return {'error': str(e)}
        return {'success': True, 'column': column, 'value': value}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def set_primary_source(self, authorid, source):
        """ AJAX: mark one of an author's already-linked sources as their primary """
        try:
            authorlink = authors.set_primary_source(authorid, source)
        except ServiceError as e:
            return {'error': str(e)}
        return {'success': True, 'authorlink': authorlink}

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def unlink_author_source(self, authorid, source):
        """ AJAX: clear a linked source id so it can be searched (and linked to a
        different match) again """
        try:
            authors.unlink_source(authorid, source)
        except ServiceError as e:
            return {'error': str(e)}
        return {'success': True}
