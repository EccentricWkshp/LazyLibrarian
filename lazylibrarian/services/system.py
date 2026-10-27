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

""" Background tasks, scans and imports, updates, restarting, jobs, logs and syncing """

import contextlib
import logging
import os
import platform
import threading
import time
from datetime import datetime

import lazylibrarian
from lazylibrarian import database, grsync, hc, magazinescan, versioncheck
from lazylibrarian.calibre import sync_calibre_list
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.common import create_support_zip, docker, url_root
from lazylibrarian.config2 import CONFIG
from lazylibrarian.csvfile import export_csv, import_csv
from lazylibrarian.filesystem import DIRS, csv_file, path_exists, remove_file
from lazylibrarian.formatter import thread_name
from lazylibrarian.librarysync import library_scan
from lazylibrarian.logconfig import LOGCONFIG
from lazylibrarian.manual_import import process_alternate, process_issues
from lazylibrarian.oldump import update_openlibrary_dump
from lazylibrarian.postprocess import process_dir
from lazylibrarian.scheduling import (
    SchedulerCommand,
    all_author_update,
    restart_jobs,
    schedule_job,
    show_jobs,
    show_running,
    show_stats,
)
from lazylibrarian.searchmag import search_magazines
from lazylibrarian.searchrss import search_wishlist
from lazylibrarian.services import InvalidRequestError, NotFoundError
from lazylibrarian.services.paging import Page, page_of

# the columns of the log the web interface keeps in memory
LOG_FIELDS = ('Time', 'Level', 'Thread', 'File', 'Method', 'Line', 'Message')
# when LazyLibrarian started, near enough: this is loaded as it starts serving pages
STARTED = time.time()
# the levels each of Sonarr's event filters shows, at the level and above. All of them for ''
EVENT_LEVELS = {'': None, 'info': ('INFO', 'WARNING', 'ERROR', 'CRITICAL'), 'warn': ('WARNING', 'ERROR', 'CRITICAL'),
                'error': ('ERROR', 'CRITICAL')}


def is_running(name: str) -> bool:
    """ Is a thread with this name running """
    return name in [n.name for n in threading.enumerate()]


def start_task(name: str, target, *args) -> bool:
    """ Run target(*args) in a thread called name, unless one is already running.
        Returns whether it was started """
    logger = logging.getLogger(__name__)
    if is_running(name):
        logger.debug(f'{name} already running')
        return False
    try:
        threading.Thread(target=target, name=name, args=list(args)).start()
    except Exception as e:
        logger.error(f'Unable to start {name}: {type(e).__name__} {str(e)}')
        return False
    return True


def book_libraries() -> list[str]:
    """ The book libraries that are switched on, eBook first """
    types = []
    if CONFIG.get_bool('EBOOK_TAB'):
        types.append('eBook')
    if CONFIG.get_bool('AUDIO_TAB'):
        types.append('AudioBook')
    return types


def start_author_update() -> bool:
    """ Refresh every author """
    return start_task('AAUPDATE', all_author_update, False)


def start_openlibrary_dump() -> bool:
    """ Sync the OpenLibrary bulk dump now instead of at its next scheduled run,
        resuming a partly downloaded file - see oldump.download_dump_file """
    if not CONFIG['OL_USE_DUMP']:
        raise InvalidRequestError('OpenLibrary local dump indexing is not enabled in Config -> Importing')
    if is_running('OLDUMPUPDATE'):
        raise InvalidRequestError('OpenLibrary dump sync is already running')
    started = start_task('OLDUMPUPDATE', update_openlibrary_dump)
    if started:
        logging.getLogger(__name__).info("Manually triggered OpenLibrary bulk dump sync")
    return started


def start_library_scan(library: str) -> bool:
    """ Scan an eBook or AudioBook library folder, a full scan when FULL_SCAN is set """
    return start_task(f"{library.upper()}_SCAN", library_scan, None, library, None, CONFIG.get_bool('FULL_SCAN'))


def start_alternate_scan(library: str = 'eBook') -> bool:
    """ Scan the alternate folder for books to add to a library """
    return start_task('ALT-LIBRARYSCAN', library_scan, CONFIG['ALTERNATE_DIR'], library, None, False)


def clean_magazine_library():
    magazinescan.clean_maglibrary()


def start_magazine_scan(title: str = '') -> bool:
    """ Scan for the issues of one magazine, or of all of them """
    if title:
        return start_task(f'MAGAZINE_SCAN_{title}', magazinescan.magazine_scan, title)
    return start_task('MAGAZINE_SCAN', magazinescan.magazine_scan)


def start_issue_import(title: str) -> bool:
    """ Import issues of a magazine from the alternate folder """
    if not title:
        raise InvalidRequestError('No title to import')
    return start_task(f"IMPORTISSUES_{title}", process_issues, CONFIG['ALTERNATE_DIR'], title)


def start_alternate_import(library: str = 'eBook') -> bool:
    """ Import books from the alternate folder into a library """
    return start_task(f'IMPORTALT_{library}', process_alternate, CONFIG['ALTERNATE_DIR'], library)


def csv_import_file(library: str) -> str:
    """ The CSV file an import of this library reads, in the alternate folder """
    return csv_file(CONFIG['ALTERNATE_DIR'], library=library)


def start_csv_import(library: str) -> bool:
    """ Mark the books listed in the library's CSV file in the alternate folder as Wanted """
    if is_running(f'IMPORTCSV_{library}'):
        return False
    if not path_exists(csv_import_file(library)):
        raise InvalidRequestError(f"No {library} CSV file in [{CONFIG['ALTERNATE_DIR']}]")
    return start_task(f'IMPORTCSV_{library}', import_csv, CONFIG['ALTERNATE_DIR'], 'Wanted', library)


def export_library_csv(library: str) -> str:
    """ Write the library's wanted books to a CSV file in the alternate folder, returns what was done """
    return export_csv(CONFIG['ALTERNATE_DIR'], library=library)


def request_stop(signal: str):
    """ Ask LazyLibrarian to update, restart or shut down once this request is answered """
    if signal not in ('update', 'restart', 'shutdown'):
        raise InvalidRequestError(f'Unknown signal {signal}')
    remove_file(os.path.join(DIRS.CACHEDIR, 'alive.png'))
    lazylibrarian.SIGNAL = signal


def status() -> dict:
    """ What is running where, like Sonarr's system status """
    db = database.DBConnection()
    try:
        schema = db.match('PRAGMA user_version')['user_version']
    finally:
        db.close()
    return {'app_name': 'LazyLibrarian', 'version': CONFIG['CURRENT_VERSION'], 'branch': CONFIG['GIT_BRANCH'],
            'install_type': CONFIG['INSTALL_TYPE'], 'latest_version': CONFIG['LATEST_VERSION'],
            'commits_behind': CONFIG.get_int('COMMITS_BEHIND'), 'database_version': schema,
            'url_base': url_root(CONFIG['HTTP_ROOT']), 'authentication': CONFIG.get_str('AUTH_TYPE'),
            'is_docker': docker(), 'os_name': platform.system(), 'os_version': platform.release(),
            'python_version': platform.python_version(), 'app_data': DIRS.DATADIR, 'startup_path': DIRS.PROG_DIR,
            'database_path': DIRS.get_dbfile(),
            'start_time': datetime.fromtimestamp(STARTED).astimezone().isoformat(timespec='seconds')}


def update_status() -> dict:
    """ Check for a new version. behind is the number of commits behind, 0 when up to date or the status
        is unknown, below 0 when the version isn't recognised. commits lists them, manual says the update
        has to be installed by hand """
    versioncheck.check_for_updates()
    commits = lazylibrarian.COMMIT_LIST or ''
    return {'behind': CONFIG.get_int('COMMITS_BEHIND'), 'commits': commits, 'manual': '** MANUAL **' in commits,
            'version': CONFIG['CURRENT_VERSION'], 'branch': CONFIG['GIT_BRANCH'],
            'repo': f"https://{CONFIG['GIT_HOST']}/{CONFIG['GIT_USER']}/{CONFIG['GIT_REPO']}"}


def jobs() -> list[str]:
    """ The scheduled jobs and when they run next, one line each """
    return show_jobs()


def stats() -> list[str]:
    """ Database and activity statistics, one line each """
    return show_stats()


def running_tasks():
    """ The jobs running now """
    return show_running()


def restart_scheduled_jobs():
    restart_jobs(command=SchedulerCommand.RESTART)


def stop_scheduled_jobs():
    restart_jobs(command=SchedulerCommand.STOP)


def apprise_types() -> list[str]:
    """ The notification services Apprise can send to, in alphabetical order """
    entries = lazylibrarian.notifiers.apprise_notify.AppriseNotifier.notify_types()
    return sorted((e for e in entries if isinstance(e, str)), key=str.casefold)


def list_log(search: str = '', sort: str = 'Time', descending: bool = True, offset: int = 0,
             limit: int | None = None) -> Page:
    """ A page of the log the web interface keeps in memory, as dicts of LOG_FIELDS """
    rows, total = LOGCONFIG.get_ui_logrows(search)
    page = page_of([dict(zip(LOG_FIELDS, row, strict=True)) for row in rows], sort=sort, descending=descending,
                   offset=offset, limit=limit)
    page.total = total
    return page


def list_events(level: str = '', search: str = '', offset: int = 0, limit: int | None = None) -> Page:
    """ The log kept in memory as Sonarr's System, Events: the most recent first, at this level and
    above (info, warn or error), or all of it """
    if level not in EVENT_LEVELS:
        raise InvalidRequestError(f"The level is one of {', '.join(name for name in EVENT_LEVELS if name)}")
    shown = EVENT_LEVELS[level]
    rows, _total = LOGCONFIG.get_ui_logrows(search)
    records = [{'time': str(row[0]).replace(',', '.'), 'level': row[1], 'thread': row[2], 'file': row[3],
                'method': row[4], 'line': row[5], 'message': row[6]}
               for row in rows if not shown or row[1] in shown]
    records.reverse()
    return page_of(records, offset=offset, limit=limit)


def list_log_files() -> list[dict]:
    """ The log files, like Sonarr's System, Log Files, the most recently written first """
    folder = CONFIG['LOGDIR']
    files = []
    with contextlib.suppress(OSError):
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if '.log' in name and os.path.isfile(path):
                stat = os.stat(path)
                files.append({'filename': name, 'size': stat.st_size,
                              'last_write_time': datetime.fromtimestamp(stat.st_mtime).astimezone()
                              .isoformat(timespec='seconds')})
    return sorted(files, key=lambda f: f['last_write_time'], reverse=True)


def log_file_path(name: str) -> str:
    """ A log file's path, by a name from list_log_files, so a request can't name any other file """
    if name not in [f['filename'] for f in list_log_files()]:
        raise NotFoundError(f'No log file {name}')
    return os.path.join(CONFIG['LOGDIR'], name)


def clear_log():
    LOGCONFIG.clear_ui_log()
    logging.getLogger(__name__).info('Screen log cleared')


def toggle_detailed_log() -> bool:
    """ Switch the detailed web interface log on or off, returns whether it's on now """
    detail = not CONFIG.get_bool('DETAILEDUILOG')
    CONFIG.set_bool('DETAILEDUILOG', detail)
    return detail


def delete_log_files() -> str:
    """ Delete the log files, returns what was done """
    result = LOGCONFIG.delete_log_files(CONFIG['LOGDIR'])
    logging.getLogger(__name__).info(result)
    return result


def support_zip() -> str:
    """ Save the redacted log and config to a zip file, returns its path """
    msg, zipfile = create_support_zip()
    logging.getLogger(__name__).info(msg)
    return zipfile


def database_ok() -> bool:
    """ Can LazyLibrarian read its database """
    db = database.DBConnection()
    try:
        db.match('SELECT 1')
    except Exception:
        return False
    finally:
        db.close()
    return True


def sync_calibre(userid) -> str:
    """ Sync the user's reading lists with Calibre, returns what happened, or None if a sync is running """
    if is_running('CalSync'):
        return None
    # the thread name tells other requests a sync is running
    previous = thread_name()
    thread_name('CalSync')
    try:
        return sync_calibre_list(userid=userid)
    finally:
        thread_name(previous)


def sync_hardcover(confirmed: bool = False, readonly: bool = False) -> str:
    """ Sync reading lists with Hardcover, readonly doesn't send anything to Hardcover """
    return hc.hc_sync(library='', userid=None, confirmed=confirmed, readonly=readonly)


def sync_goodreads() -> str:
    return grsync.sync_to_gr()


def start_postprocessor() -> bool:
    """ Look for finished downloads now, and restart the postprocessor's schedule """
    if not start_task('POSTPROCESSOR', process_dir, True):
        return False
    schedule_job(action=SchedulerCommand.RESTART, target='PostProcessor')
    return True


def search_wishlists() -> bool:
    """ Search the wishlist providers now, returns False if there aren't any """
    if not CONFIG.use_wishlist():
        logging.getLogger(__name__).warning('WishList search called but no wishlist providers set')
        return False
    search_wishlist()
    return True


def start_search(source: str) -> bool:
    """ Search for every wanted book (source books or audio), magazine or comic now.
        Returns False if there are no download providers """
    if not CONFIG.use_any():
        logging.getLogger(__name__).warning('Search called but no download providers set')
        return False
    if source == 'magazines':
        if start_task('SEARCHALLMAG', search_magazines):
            schedule_job(action=SchedulerCommand.RESTART, target='search_magazines')
    elif source == 'comics':
        if start_task('SEARCHALLCOMICS', search_comics):
            schedule_job(action=SchedulerCommand.RESTART, target='search_comics')
    elif source in ('books', 'audio'):
        if not is_running('SEARCHALLBOOKS'):
            schedule_job(SchedulerCommand.STOP, "search_book")
            schedule_job(SchedulerCommand.STARTNOW, "search_book")
        if CONFIG.use_rss():
            schedule_job(SchedulerCommand.STOP, "search_rss_book")
            schedule_job(SchedulerCommand.STARTNOW, "search_rss_book")
    else:
        raise InvalidRequestError(f'Nothing to search for in {source}')
    return True
