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

import logging
import traceback

import cherrypy

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, date_format
from lazylibrarian.services import InvalidRequestError, NotFoundError, comics
from lazylibrarian.services.files import cover_thumbnail
from lazylibrarian.web.common import BasePages, serve_template
from lazylibrarian.web.magazines import issue_number_text

lastcomic = ''

# comics.html's columns, by the field each one sorts on
COMIC_COLUMNS = comics.SEARCH_FIELDS
# comicissues.html's columns
ISSUE_COLUMNS = ('Title', 'Cover', 'IssueID', 'IssueAcquired', 'IssueID')


class ComicPages(BasePages):
    """ The comic list, comic issues, finding and adding comics and marking them """

    @cherrypy.expose
    @require_auth()
    def edit_comic(self, comicid=None):
        self.label_thread('EDIT_COMIC')
        try:
            data = comics.get_comic(comicid)
        except NotFoundError as e:
            logging.getLogger(__name__).info(f'Missing comic {comicid}:')
            raise cherrypy.HTTPError(404, str(e)) from None
        return serve_template(templatename="editcomic.html", title=i18n.gettext("Edit Comic"), config=data)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    def comic_update(self, comicid='', new_name='', new_id='', aka='', editordata='', **kwargs):
        try:
            comicid = comics.update_comic(comicid, new_name, new_id, aka, editordata)
        except NotFoundError as e:
            raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")

    @cherrypy.expose
    @require_auth()
    def search_for_comic(self, comicid=None):
        try:
            comics.search_for_comic(comicid)
        except NotFoundError:
            raise cherrypy.HTTPRedirect("comics") from None
        raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")

    @cherrypy.expose
    @require_auth()
    def start_comic_search(self, comicid=None):
        comics.start_search(comicid)

    @cherrypy.expose
    @require_auth()
    def comics(self, comic_filter=''):
        return serve_template(templatename="comics.html", title=i18n.gettext("Comics"), comics=[],
                              covercount=1 if CONFIG['TOGGLES'] else 0, user=owner_id(), comic_filter=comic_filter)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_comics(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        page = None
        userprefs = 0
        cookie = cherrypy.request.cookie
        userid = owner_id()
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        # noinspection PyBroadException
        try:
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            page = comics.list_comics(
                search=sSearch, sort=COMIC_COLUMNS[int(iSortCol_0)], descending=sSortDir_0 == "desc",
                offset=int(iDisplayStart), limit=displaylength,
                subscriber=userid if userid and userprefs & lazylibrarian.pref_mycomics else None)
            for comic in page.items:
                row = [comic[field] for field in comics.SEARCH_FIELDS]
                covers = cover_thumbnail(comic['LatestCover'])
                row[1] = covers[0] if covers else 'images/nocover.jpg'
                row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                row[5] = issue_number_text(row[5], year_first=False) or date_format(
                    row[5], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                rows.append(row)
            serversidelogger.debug(f"get_comics filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_comics: {traceback.format_exc()}')
            rows = []
            page = None
        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  'loading': lazylibrarian.COMIC_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def comic_scan(self, **kwargs):
        comicid = kwargs.get('comicid')
        comics.start_scan(comicid)
        if comicid:
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def comicissue_page(self, comicid):
        global lastcomic
        try:
            title = comics.get_comic(comicid)['Title']
        except NotFoundError as e:
            logging.getLogger(__name__).warning(f"Invalid comic ID: {comicid}")
            raise cherrypy.HTTPError(404, str(e)) from None
        safetitle = title.replace('&', '&amp;') if title and '&' in title and '&amp;' not in title else title
        # if we've changed comic, reset to first page of new comics issues
        if comicid == lastcomic:
            firstpage = 'false'
        else:
            lastcomic = comicid
            firstpage = 'true'
        return serve_template(templatename="comicissues.html", comicid=comicid, title=safetitle, issues=[],
                              covercount=1 if CONFIG['TOGGLES'] else 0, user=owner_id(), firstpage=firstpage)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_comic_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0,
                         sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        page = None
        # noinspection PyBroadException
        try:
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            comicid = kwargs['comicid']
            page = comics.list_issues(comicid, search=sSearch, sort=ISSUE_COLUMNS[int(iSortCol_0)],
                                      descending=sSortDir_0 == "desc", offset=int(iDisplayStart), limit=displaylength)
            for issue in page.items:
                covers = cover_thumbnail(issue['Cover'])
                title = issue['Title']
                rows.append([title, covers[0] if covers else 'images/nocover.jpg',
                             date_format(issue['IssueID'], CONFIG['ISS_FORMAT'], context=title,
                                         datelang=CONFIG['DATE_LANG']),
                             date_format(issue['IssueAcquired'], CONFIG['DATE_FORMAT'], context=title,
                                         datelang=CONFIG['DATE_LANG']),
                             f"{comicid}_{issue['IssueID']}"])
            serversidelogger.debug(f"get_comic_issues filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_comic_issues: {traceback.format_exc()}')
            rows = []
            page = None
        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  'loading': lazylibrarian.COMIC_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def find_comic(self, title=None, **kwargs):
        # search for a comic title and produce a list of likely matches
        if not title or title == 'None':
            raise cherrypy.HTTPRedirect("comics")
        results = comics.find_comics(title)
        if results is not None:
            return serve_template(templatename="comicresults.html", title=i18n.gettext("Comics"), results=results,
                                  comicids=comics.comic_ids())
        if kwargs.get('comicfilter'):
            raise cherrypy.HTTPRedirect("comics?comic_filter=" + kwargs.get('comicfilter'))
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def add_comic(self, comicid=None, **kwargs):
        # add a comic from a list in comicresults.html
        if not comicid or comicid == 'None':
            raise cherrypy.HTTPRedirect("comics")
        if not (comicid.startswith('CV') and not CONFIG['CV_APIKEY']):
            self.validate_param("comicid", comicid, ['<', '&', '>', '=', '"', "'", '+', '(', ')'], 404)
        try:
            comics.add_comic(comicid)
        except InvalidRequestError as e:
            raise cherrypy.HTTPError(403, str(e)) from None
        except NotFoundError as e:
            raise cherrypy.HTTPError(404, str(e)) from None
        if kwargs.get('comicfilter'):
            raise cherrypy.HTTPRedirect("comics?comic_filter=" + kwargs.get('comicfilter'))
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def mark_comics(self, action=None, **args):
        args.pop('book_table_length', None)
        comics.mark_comics(action, list(args), userid=owner_id())
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def mark_comic_issues(self, action=None, **args):
        args.pop('book_table_length', None)
        comicid = comics.mark_issues(action, list(args))
        if comicid:
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        raise cherrypy.HTTPRedirect("comics")
