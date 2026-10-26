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


import logging
import os
import re
import threading
import traceback
from urllib.parse import quote, urlsplit, urlunsplit

import cherrypy

import lazylibrarian
from lazylibrarian import database, grsync, hc, i18n, magazinescan, versioncheck
from lazylibrarian.auth import AuthController, owner_id, require_auth
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.calibre import sync_calibre_list
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.common import create_support_zip, log_header
from lazylibrarian.config2 import CONFIG
from lazylibrarian.csvfile import export_csv, import_csv
from lazylibrarian.download_client import get_download_progress
from lazylibrarian.filesystem import DIRS, csv_file, path_exists, remove_file
from lazylibrarian.formatter import date_format, make_unicode, plural
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
from lazylibrarian.web.authors import AuthorPages
from lazylibrarian.web.books import BookPages
from lazylibrarian.web.comics import ComicPages
from lazylibrarian.web.common import BasePages, fold, serve_template
from lazylibrarian.web.connection_tests import ConnectionTestPages
from lazylibrarian.web.files import FilePages
from lazylibrarian.web.magazines import MagazinePages
from lazylibrarian.web.series import SeriesPages
from lazylibrarian.web.settings import SettingsPages
from lazylibrarian.web.users import UserPages
from lazylibrarian.web.wall import WallPages


# noinspection PyProtectedMember,PyGlobalUndefined,PyGlobalUndefined
class WebInterface(UserPages, SeriesPages, SettingsPages, ConnectionTestPages, AuthorPages, BookPages, FilePages, WallPages, ComicPages, MagazinePages, BasePages):
    _cp_config = {'tools.ui_language.on': True}

    auth = AuthController()

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

    # MAGAZINES #########################################################

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
    def opds(self, **kwargs):
        self.label_thread('OPDS Server')
        op = OPDS()
        op.check_params(**kwargs)
        data = op.fetch_data()
        return data
