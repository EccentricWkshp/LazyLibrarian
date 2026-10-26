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

""" The series list, series members and series edits """

import contextlib
import logging
import traceback

import cherrypy

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int
from lazylibrarian.services import NotFoundError, authors, series, users
from lazylibrarian.web.books import READING_FLAGS
from lazylibrarian.web.common import BasePages, mark_summary, serve_template

# series.html's columns, by the field each one sorts on (the source column has always sorted by percent)
SERIES_COLUMNS = ('SeriesID', 'AuthorSort', 'SeriesName', 'Percent', 'Status', 'SeriesID', 'Have', 'Total', 'Reason',
                  'Percent', 'Percent')


class SeriesPages(BasePages):
    """ The series list, series members and series edits """

    @cherrypy.expose
    @require_auth()
    def remove_series(self, seriesid):
        try:
            series.remove_series(seriesid)
        except NotFoundError as e:
            logging.getLogger(__name__).warning(str(e))
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def edit_series(self, seriesid):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_SERIES')
        try:
            edit = series.series_for_edit(seriesid)
        except NotFoundError as e:
            logging.getLogger(__name__).info(f'Missing series {seriesid}')
            raise cherrypy.HTTPError(404, str(e)) from None
        return serve_template(templatename="editseries.html", title=i18n.gettext("Edit Series"), config=edit['series'],
                              members=edit['members'])

    @cherrypy.expose
    @require_auth()
    def series_update(self, seriesid='', **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if seriesid:
            new_name = kwargs.get('new_name')
            if new_name:
                self.validate_param("new series name", new_name, ['<', '>', '='], 404)
            try:
                series.update_series(seriesid, kwargs.get('new_id'), new_name)
            except NotFoundError as e:
                raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def refresh_series(self, seriesid):
        series.refresh_series(seriesid)
        raise cherrypy.HTTPRedirect(f"series_members?seriesid={seriesid}&ignored=False")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_series(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        page = None
        rows = []
        userprefs = 0
        cookie = cherrypy.request.cookie
        userid = owner_id()
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        # noinspection PyBroadException
        try:
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            author_id = kwargs.get('AuthorID') or ''
            if author_id == 'None':
                author_id = ''
            page = series.list_series(
                search=sSearch, sort=SERIES_COLUMNS[int(iSortCol_0)], descending=sSortDir_0 == "desc",
                offset=int(iDisplayStart), limit=displaylength, status=kwargs.get('whichStatus') or 'All',
                authorid=author_id, active_only=bool(kwargs.get('active')),
                subscriber=userid if userid and userprefs & lazylibrarian.pref_myseries else None)
            # We pass SeriesID twice for datatables as the render function modifies it,
            # and we need it in two columns. There is probably a better way...
            rows = [[s['SeriesID'], s['AuthorSort'], s['SeriesName'], s['Status'], s['AuthorID'], s['SeriesID'],
                     s['Have'], s['Total'], s['Reason'], s['Source'], s['Percent']] for s in page.items]
            serversidelogger.debug(f"get_series filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_series: {traceback.format_exc()}')
            rows = []
            page = None
        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def series(self, authorid=None, which_status=None, active=False):
        title = i18n.gettext('Series')
        if authorid:
            with contextlib.suppress(NotFoundError):
                title = i18n.gettext('%(author)s Series') % {'author': authors.get_author(authorid)['AuthorName']}
            if '&' in title and '&amp;' not in title:
                title = title.replace('&', '&amp;')
        return serve_template(templatename="series.html", title=title, authorid=authorid, series=[],
                              whichStatus=which_status, active=active)

    @cherrypy.expose
    @require_auth()
    def series_members(self, seriesid, ignored=False):
        userid = owner_id()
        try:
            found = series.series_page(seriesid, ignored=bool(ignored) and ignored != 'False', userid=userid)
        except NotFoundError:
            raise cherrypy.HTTPRedirect("series") from None
        rows = []
        for member in found['members']:
            name = member['BookName']
            if member['BookSub']:  # is there a subtitle
                name = f"{name}<br><small><i>{member['BookSub']}</i></small>"
            rows.append({'BookID': member['BookID'], 'BookName': name, 'SeriesNum': member['SeriesNum'],
                         'BookImg': member['BookImg'], 'Status': member['Status'], 'AuthorName': member['AuthorName'],
                         'AuthorID': member['AuthorID'], 'BookLink': member['BookLink'] or '',
                         'WorkPage': member['WorkPage'] or '', 'AudioStatus': member['AudioStatus'],
                         'Flag': READING_FLAGS.get(member['ReadingList'], '')})
        return serve_template(templatename="members.html", title=found['series']['SeriesName'], members=rows,
                              series=found['series'], multi="True" if found['multi'] else "False", ignored=ignored,
                              email=users.send_to(userid))

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_series_ajax(self, action=None, redirect=None, **args):
        # redirect is an explicit param (not left in **args) for the same reason
        # mark_books_ajax already declares it: series.html's #mark_series form has a
        # hidden `redirect` field (the authorid to bounce back to) that FormData sends
        # alongside the checked series - left in args it's iterated as if it were a
        # SeriesID, fails to match any series, and is counted as a failed item
        # (Issue #2850).
        for arg in ['book_table_length', 'series_table_length', 'author_table_length', 'ignored', '_', 'action',
                    'which_status']:
            args.pop(arg, None)
        passed, failed = series.mark_series(action, list(args), userid=owner_id())
        if action:
            redirect = f"series?authorid={redirect}" if redirect else "series"
        elif redirect is None:
            redirect = ''
        summary = mark_summary(i18n.gettext("Mark Series '%(action)s' completed.") % {
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
