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
import threading
import traceback
from urllib.parse import quote, urlsplit, urlunsplit

import cherrypy

import lazylibrarian
from lazylibrarian import database, grsync, hc, i18n, magazinescan, versioncheck
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.calibre import sync_calibre_list
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.common import create_support_zip, log_header
from lazylibrarian.config2 import CONFIG
from lazylibrarian.csvfile import export_csv, import_csv
from lazylibrarian.filesystem import DIRS, csv_file, path_exists, remove_file
from lazylibrarian.formatter import plural
from lazylibrarian.librarysync import library_scan
from lazylibrarian.logconfig import LOGCONFIG
from lazylibrarian.manual_import import process_alternate, process_issues
from lazylibrarian.oldump import update_openlibrary_dump
from lazylibrarian.opds import OPDS
from lazylibrarian.postprocess import process_dir
from lazylibrarian.rssfeed import gen_feed
from lazylibrarian.scheduling import (
    SchedulerCommand,
    all_author_update,
    restart_jobs,
    schedule_job,
    show_jobs,
    show_stats,
)
from lazylibrarian.searchmag import search_magazines
from lazylibrarian.searchrss import search_wishlist
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

    @cherrypy.expose
    @require_auth()
    def show_running(self):
        """ return a list of currently running tasks """
        return lazylibrarian.scheduling.show_running()

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
