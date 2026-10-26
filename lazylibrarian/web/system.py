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

""" Updates, library scans, imports and exports, jobs, logs, syncing, OPDS and the legacy API """

import logging
import os
import traceback
from urllib.parse import quote, urlsplit, urlunsplit

import cherrypy

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.common import log_header
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import plural
from lazylibrarian.opds import OPDS
from lazylibrarian.rssfeed import gen_feed
from lazylibrarian.services import InvalidRequestError, system
from lazylibrarian.web.common import BasePages, serve_template


class SystemPages(BasePages):
    """ Updates, library scans, imports and exports, jobs, logs, syncing, OPDS and the legacy API """

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
    def check_for_updates(self):
        self.label_thread('UPDATES')
        status = system.update_status()
        behind = status['behind']
        commits = status['commits'].replace('\n', '<br>')
        if behind == 0:
            if status['commits']:
                message = i18n.gettext("LazyLibrarian status is unknown") + '<br><small>' + commits
            else:
                message = i18n.gettext("LazyLibrarian is up to date")
        elif behind > 0:
            message = i18n.ngettext("LazyLibrarian is behind by %(count)s commit",
                                    "LazyLibrarian is behind by %(count)s commits", behind) % {'count': behind}
            message = message + '<br><small>' + commits
            if status['manual']:
                message += i18n.gettext("Update needs manual installation")
        else:
            message = i18n.gettext("LazyLibrarian version is unknown")
            messages = i18n.gettext("Your version (%(version)s) is not recognized at %(repo)s") % {
                'version': status['version'], 'repo': status['repo']}
            messages += '  ' + i18n.gettext('Branch: %(branch)s') % {'branch': status['branch']}
            message = message + '<br><small>' + messages
        return message

    @cherrypy.expose
    @require_auth()
    def force_update(self):
        system.start_author_update()
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def force_openlibrary_dump(self):
        """ AJAX: manually trigger an OpenLibrary bulk-dump sync right now instead of
        waiting for its next scheduled run """
        try:
            system.start_openlibrary_dump()
        except InvalidRequestError as e:
            return {'error': str(e)}
        return {'success': True}

    @cherrypy.expose
    @require_auth()
    def update(self):
        self.label_thread('UPDATING')
        logging.getLogger(__name__).debug('(webServe-Update) - Performing update')
        system.request_stop('update')
        message = i18n.gettext('LazyLibrarian is updating...')
        return serve_template(templatename="shutdown.html", prefix='', title=i18n.gettext("Updating"),
                              message=message, timer=90)

    @cherrypy.expose
    @require_auth()
    def library_scan(self, **kwargs):
        types = system.book_libraries()
        if not types:
            raise cherrypy.HTTPRedirect('authors')
        library = kwargs['library'] if kwargs.get('library') in types else types[0]
        system.start_library_scan(library)
        if library == 'AudioBook':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def clean_magazine_library(self):
        system.clean_magazine_library()
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def magazine_scan(self, **kwargs):
        title = kwargs.get('title', '').replace('&amp;', '&')
        system.start_magazine_scan(title)
        if title:
            raise cherrypy.HTTPRedirect(f"issue_page?title={quote(title)}")
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def include_alternate(self, library='eBook'):
        system.start_alternate_scan(library)
        raise cherrypy.HTTPRedirect(f"manage?library={library}")

    @cherrypy.expose
    @require_auth()
    def import_issues(self, title=None):
        try:
            system.start_issue_import(title)
        except InvalidRequestError as e:
            logging.getLogger(__name__).error(str(e))
            raise cherrypy.HTTPRedirect("magazines") from None
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(title)}")

    @cherrypy.expose
    @require_auth()
    def import_alternate(self, library='eBook'):
        self.validate_param("library name", library, ['<', '>', '='], 404)
        system.start_alternate_import(library)
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
        self.label_thread('IMPORTCSV')
        try:
            if system.start_csv_import(library):
                return i18n.gettext("Importing csv (background task) from %(file)s") % {
                    'file': system.csv_import_file(library)}
            return i18n.gettext('CSV import is already running')
        except InvalidRequestError:
            return i18n.gettext("No %(library)s CSV file in [%(folder)s]") % {
                'library': i18n.status_label(library), 'folder': CONFIG['ALTERNATE_DIR']}
        except Exception as e:
            logging.getLogger(__name__).error(f'Unable to complete the import: {type(e).__name__} {str(e)}')
            return i18n.gettext('Unable to complete the import: %(error)s') % {
                'error': f'{type(e).__name__} {str(e)}'}

    @cherrypy.expose
    @require_auth()
    def export_csv(self, library=''):
        self.validate_param("library name", library, ['<', '>', '='], 404)
        self.label_thread('EXPORTCSV')
        return system.export_library_csv(library).replace('\n', '<br>')

    @cherrypy.expose
    @require_auth()
    def shutdown(self):
        self.label_thread('SHUTDOWN')
        system.request_stop('shutdown')
        message = i18n.gettext('LazyLibrarian is closed')
        return serve_template(templatename="shutdown.html", prefix='', title=i18n.gettext("Close library"),
                              message=message, timer=0)

    @cherrypy.expose
    @require_auth()
    def restart(self):
        self.label_thread('RESTART')
        system.request_stop('restart')
        message = i18n.gettext('LazyLibrarian is reopening...')
        return serve_template(templatename="shutdown.html", prefix='', title=i18n.gettext("Reopen library"),
                              message=message, timer=50)

    @cherrypy.expose
    @require_auth()
    def show_jobs(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        return ''.join(f'{line}\n' for line in system.jobs())

    @cherrypy.expose
    @require_auth()
    def show_apprise(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        try:
            return "\n".join(system.apprise_types())
        except Exception as e:
            logging.getLogger(__name__).debug(str(e))
            return ''

    @cherrypy.expose
    @require_auth()
    def show_stats(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        return ''.join(f'{line}\n' for line in system.stats())

    @cherrypy.expose
    @require_auth()
    def restart_jobs(self):
        system.restart_scheduled_jobs()

    @cherrypy.expose
    @require_auth()
    def stop_jobs(self):
        system.stop_scheduled_jobs()

    @cherrypy.expose
    @require_auth()
    def clear_log(self):
        system.clear_log()
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def toggle_detailed_logs(self):
        system.toggle_detailed_log()
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def delete_logs(self):
        system.delete_log_files()
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def get_support_zip(self):
        self.label_thread('SAVELOG')
        zipfile = system.support_zip()
        return cherrypy.lib.static.serve_file(zipfile, 'application/x-download', 'attachment',
                                              os.path.basename(zipfile))

    @cherrypy.expose
    @require_auth()
    def log_header(self):
        return log_header()

    @cherrypy.expose
    @require_auth()
    def logs(self):
        return serve_template(templatename="logs.html", title=i18n.gettext("Log"), lineList=[])

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_log(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        # kwargs is used by datatables to pass params
        page = None
        # noinspection PyBroadException
        try:
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            page = system.list_log(search=sSearch, sort=system.LOG_FIELDS[int(iSortCol_0)],
                                   descending=sSortDir_0 == "desc", offset=int(iDisplayStart), limit=displaylength)
        except Exception:
            logging.getLogger(__name__).error(f'Unhandled exception in get_log: {traceback.format_exc()}')
        return {'iTotalDisplayRecords': page.matched if page else 0,
                'iTotalRecords': page.total if page else 0,
                'aaData': [[item[field] for field in system.LOG_FIELDS] for item in page.items] if page else [],
                }

    @cherrypy.expose
    @require_auth()
    def show_running(self):
        """ return a list of currently running tasks """
        return system.running_tasks()

    @cherrypy.expose
    @require_auth()
    def sync_to_calibre(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        userid = owner_id()
        if not userid:
            return i18n.gettext("No userid found")
        msg = system.sync_calibre(userid)
        if msg is None:
            return i18n.gettext('Calibre Sync is already running')
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
        msg = system.sync_hardcover(confirmed=confirmed, readonly=readonly or ignore)
        self.label_thread('WEBSERVER')
        return msg

    @cherrypy.expose
    @require_auth()
    def sync_to_goodreads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('WEB-GRSYNC')
        msg = system.sync_goodreads()
        self.label_thread('WEBSERVER')
        return msg

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def ping(self):
        """ Health check for Docker and monitoring tools, like Sonarr's /ping. It needs no
        login, so it only says whether LazyLibrarian is up and can read its database """
        if system.database_ok():
            return {'status': 'OK'}
        cherrypy.response.status = 503
        return {'status': 'Error'}

    @cherrypy.expose
    def api(self, **kwargs):
        from lazylibrarian.api import Api
        a = Api()
        # noinspection PyArgumentList
        a.check_params(**kwargs)
        return a.fetch_data

    @cherrypy.expose
    @require_auth()
    def force_process(self, source=None):
        system.start_postprocessor()
        if self.valid_source(source):
            raise cherrypy.HTTPRedirect(source)
        raise cherrypy.HTTPRedirect('index')

    @cherrypy.expose
    @require_auth()
    def force_wish(self, source=None):
        system.search_wishlists()
        if self.valid_source(source):
            raise cherrypy.HTTPRedirect(source)
        raise cherrypy.HTTPRedirect('index')

    @cherrypy.expose
    @require_auth()
    def force_search(self, source=None, title=None):
        self.validate_param("search title", title, ['<', '>', '='], 404)
        if title and source in ("magazines", 'comics'):
            if CONFIG.use_any():
                title = title.replace('&amp;', '&')
                if source == 'magazines':
                    self.search_for_mag(bookid=title)
                else:
                    self.search_for_comic(comicid=title)
            else:
                logging.getLogger(__name__).warning('Search called but no download providers set')
        elif source in ("magazines", 'comics', "books", "audio"):
            system.start_search(source)

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
