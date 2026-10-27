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
import logging
import traceback
from urllib.parse import quote

import cherrypy

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, check_year, date_format
from lazylibrarian.processcontrol import get_info_on_caller
from lazylibrarian.services import InvalidRequestError, NotFoundError, magazines, users
from lazylibrarian.services.files import cover_thumbnail
from lazylibrarian.web.common import BasePages, mark_summary, serve_template

lastmagazine = ''

# magazines.html's columns, by the field each one sorts on
MAGAZINE_COLUMNS = ('Title', 'LatestCover', 'Title', 'Iss_Cnt', 'LastAcquired', 'IssueDate', 'Status',
                    'IssueStatus', 'Genre')
# issues.html's columns
ISSUE_COLUMNS = ('Title', 'Cover', 'IssueDate', 'IssueAcquired', 'IssueID')


def issue_number_text(issuedate: str, year_first: bool) -> str | None:
    """ An issue number date (yyyynnnn, vvvvnnnn or yyyyvvvvnnnn) as text, None if it isn't one """
    if not issuedate or not issuedate.isdigit():
        return None
    if len(issuedate) == 8:
        # Year/Issue or Volume/Issue with no year
        if check_year(issuedate[:4]):
            if year_first:
                return f'{issuedate[:4]} Issue {int(issuedate[4:])}'
            return f'Issue {int(issuedate[4:])} {issuedate[:4]}'
        return f'Vol {int(issuedate[:4])} #{int(issuedate[4:])}'
    if len(issuedate) == 12:
        if year_first:
            return f'{issuedate[:4]} Vol {int(issuedate[4:8])} #{int(issuedate[8:])}'
        return f'Vol {int(issuedate[4:8])} #{int(issuedate[8:])} {issuedate[:4]}'
    return issuedate


def progress_bar(current, total, percent, width='70%', heading='') -> str:
    return (f'{heading}<div class="progress center-block" style="width: {width};"><div class="progress-bar-info'
            f' progress-bar progress-bar-striped" role="progressbar aria-valuenow="{percent}"'
            f' aria-valuemin="0" aria-valuemax="100" style="width:{percent}%;">'
            f'<span class="progressbar-front-text">{current}/{total}</span></div></div>')


class MagazinePages(BasePages):
    """ The magazine list, issues, past issues, adding magazines and marking them """

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_mags(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
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
            page = magazines.list_magazines(
                search=sSearch, sort=MAGAZINE_COLUMNS[int(iSortCol_0)], descending=sSortDir_0 == "desc",
                offset=int(iDisplayStart), limit=displaylength,
                subscriber=userid if userid and userprefs & lazylibrarian.pref_mymags else None)
            for mag in page.items:
                row = [mag['Title'], mag['LatestCover'], quote(mag['Title']), mag['Iss_Cnt'],
                       date_format(mag['LastAcquired'], CONFIG['DATE_FORMAT'], context=mag['Title'],
                                   datelang=CONFIG['DATE_LANG']),
                       issue_number_text(mag['IssueDate'], year_first=False) or
                       date_format(mag['IssueDate'], CONFIG['ISS_FORMAT'], context=mag['Title'],
                                   datelang=CONFIG['DATE_LANG']),
                       mag['Status'], mag['IssueStatus'], mag['Genre']]
                covers = cover_thumbnail(mag['LatestCover'])
                row[1] = covers[0] if covers else 'images/nocover.jpg'
                row.append(covers[1] if covers else 'images/nocover.jpg')
                rows.append(row)
            serversidelogger.debug(f"get_mags filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_mags: {traceback.format_exc()}')
            rows = []
            page = None
        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  'loading': lazylibrarian.MAG_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def magazines(self, mag_filter=''):
        user = owner_id() or 0
        return serve_template(templatename="magazines.html", title=i18n.gettext("Magazines"), magazines=[],
                              covercount=1 if CONFIG['TOGGLES'] else 0, user=user, email=users.send_to(user),
                              mag_filter=mag_filter)

    @cherrypy.expose
    @require_auth()
    def edit_mag(self, mag=None):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_MAG')
        try:
            magdata = magazines.get_magazine(mag)
        except NotFoundError:
            logging.getLogger(__name__).error(f'Missing magazine {mag}')
            raise cherrypy.HTTPRedirect("magazines") from None
        return serve_template(templatename="editmag.html",
                              title=i18n.gettext('Rename Magazine %(title)s') % {'title': magdata['Title']},
                              config={'Title': magdata['Title']})

    # noinspection PyBroadException
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def magazine_update_ajax(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        passed = failed = 0
        new_title = kwargs.get('new_title')
        old_title = kwargs.get('old_title')
        if not old_title and not new_title:
            summary = i18n.gettext('Insufficient information, need Old and New Title')
        elif old_title == new_title:
            summary = i18n.gettext('Title for %(title)s unchanged') % {'title': old_title}
        elif not self.validate_param("magazine title", new_title, ['<', '>', '='], None):
            summary = i18n.gettext('Invalid new title, unable to rename')
        else:
            try:
                passed, failed = magazines.rename_magazine(old_title, new_title)
                summary = i18n.gettext('Renamed %(old)s to %(new)s') % {'old': old_title, 'new': new_title}
            except InvalidRequestError:
                summary = i18n.gettext('Title %(title)s already exists, unable to rename') % {'title': new_title}
        return {
            'success': True,
            'passed': passed,
            'failed': failed,
            'total': passed + failed,
            'title': new_title,
            'summary': summary or i18n.gettext("Rename completed.")
        }

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        page = None
        # noinspection PyBroadException
        try:
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            page = magazines.list_issues(kwargs['title'].replace('&amp;', '&'), search=sSearch,
                                         sort=ISSUE_COLUMNS[int(iSortCol_0)], descending=sSortDir_0 == "desc",
                                         offset=int(iDisplayStart), limit=displaylength)
            for issue in page.items:
                row = [issue['Title'], 'images/nocover.jpg', issue['IssueDate'], issue['IssueAcquired'],
                       issue['IssueID']]
                covers = cover_thumbnail(issue['Cover'])
                if covers:
                    row[1] = covers[0]
                    row.append(covers[1])
                row[3] = date_format(row[3], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                row[2] = issue_number_text(row[2], year_first=True) or date_format(
                    row[2], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                if lazylibrarian.perm_admin & lazylibrarian.perm_edit:
                    row[2] = row[2] + '<br><a href="edit_issue?issueid=' + row[4] + '"><small><i>Edit</i></a>'
                rows.append(row)
            serversidelogger.debug(f"get_issues filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_issues: {traceback.format_exc()}')
            rows = []
            page = None
        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  'loading': lazylibrarian.MAG_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def edit_issue(self, issueid=None):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_ISSUE')
        try:
            issuedata, tagdict = magazines.issue_for_edit(issueid)
        except NotFoundError as e:
            logging.getLogger(__name__).error(str(e))
            return None
        return serve_template(templatename="editissue.html", title=i18n.gettext("Edit Issue"), config=issuedata,
                              tags=tagdict)

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
        if magtitle:
            self.validate_param("magazine title", magtitle, ['<', '>', '='], 404)
        new_tags = {itm[5:]: value for itm, value in kwargs.items() if itm.startswith('tags_/')}
        try:
            old_tags = ast.literal_eval(kwargs['tagdata'])
        except SyntaxError:
            old_tags = None
        if not isinstance(old_tags, dict):
            logger.warning("Invalid old_tags dictionary")
            old_tags = {}
        try:
            redirect, response = magazines.update_issue(issueid, magtitle, kwargs.get('issuenum'), new_tags, old_tags)
        except NotFoundError:
            raise cherrypy.HTTPRedirect("magazines") from None
        except InvalidRequestError as e:
            raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(redirect)}&response={response}")

    @cherrypy.expose
    @require_auth()
    def issue_page(self, title, response=''):
        global lastmagazine
        try:
            title = magazines.get_magazine(title)['Title']
        except NotFoundError:
            logging.getLogger(__name__).warning(f"Unknown magazine title: {title}")
            raise cherrypy.HTTPError(404, f"Magazine title {title} not found") from None
        # could use htmlparser but seems overkill for just '&'
        safetitle = title.replace('&', '&amp;') if title and '&' in title and '&amp;' not in title else title
        # if we've changed magazine, reset to first page of new magazines issues
        if title == lastmagazine:
            firstpage = 'false'
        else:
            lastmagazine = title
            firstpage = 'true'
        user = owner_id()
        magazines.set_issue_progress(0, 0)
        return serve_template(templatename="issues.html", title=safetitle, issues=[],
                              covercount=1 if CONFIG['TOGGLES'] else 0, user=user, email=users.send_to(user),
                              firstpage=firstpage, response=response)

    @cherrypy.expose
    @require_auth()
    def abort_progress(self):
        magazines.abort_marking()
        return False

    @cherrypy.expose
    @require_auth()
    def test_progress(self):
        return lazylibrarian.test_data

    @cherrypy.expose
    @require_auth()
    def issues_progress(self):
        current = total = percent = '0'
        try:
            current, total, percent = magazines.issue_progress.split('/')
        except ValueError:
            with contextlib.suppress(ValueError):
                current, total, percent = lazylibrarian.magazinescan_data.split('/')
        return progress_bar(current, total, percent)

    @cherrypy.expose
    @require_auth()
    def magazinescan_progress(self):
        try:
            current, total, percent = lazylibrarian.magazinescan_data.split('/')
        except ValueError:
            return lazylibrarian.magazinescan_data
        return progress_bar(current, total, percent, width='90%',
                            heading='<div class="text-center">Scanning Library ...<br></div>')

    @cherrypy.expose
    @require_auth()
    def past_issues(self, mag=None, **kwargs):
        title = i18n.gettext('Past Issues') if not mag or mag == 'None' else mag
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
        rows = []
        page = None
        # noinspection PyBroadException
        try:
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            mag = kwargs.get('mag')
            page = magazines.list_past_issues(
                kwargs['whichStatus'], mag.replace('&amp;', '&') if mag and mag != 'None' else None, search=sSearch,
                sort=magazines.PAST_ISSUE_FIELDS[int(iSortCol_0)], descending=sSortDir_0 == "desc",
                offset=int(iDisplayStart), limit=displaylength)
            for issue in page.items:
                row = [issue[field] for field in magazines.PAST_ISSUE_FIELDS]
                if row[1]:
                    row[1] = row[1].replace('.', ' ')
                provider = row[4] or ''
                if len(provider) > 20:
                    while len(provider) > 20 and '/' in provider:
                        provider = provider.split('/', 1)[1]
                    row[4] = provider.replace('/', ' ')
                rows.append(row)
            serversidelogger.debug(f"get_past_issues filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_past_issues: {traceback.format_exc()}')
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
    def mark_past_issues(self, action=None, **args):
        args.pop('book_table_length', None)
        magazines.mark_past_issues(action, list(args))
        raise cherrypy.HTTPRedirect("past_issues")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_issues_ajax(self, action=None, **args):
        args.pop('book_table_length', None)
        passed, failed, title = magazines.mark_issues(action, list(args))
        summary = mark_summary(i18n.gettext("Operation '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': passed + failed,
            'title': title,
            'summary': summary
        }

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_magazines_ajax(self, action=None, **args):
        logger = logging.getLogger(__name__)
        args.pop('book_table_length', None)
        passed, failed = magazines.mark_magazines(action, list(args), userid=owner_id())
        summary = mark_summary(i18n.gettext("Operation '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        res = {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': passed + failed,
            'summary': summary
        }
        logger.debug(f"{res}")
        logger.debug(f"Returning to {get_info_on_caller(depth=1)}")
        return res

    @cherrypy.expose
    @require_auth()
    def search_for_mag(self, bookid=None):
        try:
            magazines.search_for_magazine(bookid)
        except NotFoundError as e:
            raise cherrypy.HTTPError(404, str(e)) from None
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def start_magazine_search(self, mags=None):
        magazines.start_search(mags)

    @cherrypy.expose
    @require_auth()
    def add_magazine(self, title=None, **kwargs):
        if not title or title == 'None':
            raise cherrypy.HTTPRedirect("magazines")
        self.validate_param("magazine title", title, ['<', '>', '='], 404)
        stored, new = magazines.add_magazine(title)
        if not new:
            # it was there already, show it
            raise cherrypy.HTTPRedirect(f"magazines?mag_filter={quote(stored)}")
        if kwargs.get('magfilter'):
            raise cherrypy.HTTPRedirect("magazines?mag_filter=" + kwargs.get('magfilter'))
        raise cherrypy.HTTPRedirect("magazines")
