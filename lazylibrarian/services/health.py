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

""" Health, like Sonarr's System, Status: what stops LazyLibrarian working as it should, each with
what to do about it. The checks only look, they change nothing: a folder that isn't there isn't
made, a download client is only logged in to. Asking the download clients is slow, so their
answers are kept a few minutes. Also the disk space where the libraries and downloads are """

import contextlib
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from lazylibrarian import (
    database,
    deluge,
    nzbget,
    qbittorrent,
    rtorrent,
    sabnzbd,
    synology,
    transmission,
    utorrent,
)
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import check_int, get_list, plural
from lazylibrarian.services import backups, queue, remotepaths

# seconds a download client's answer is kept
CLIENT_KEEP = 300
# seconds to wait for the download clients
CLIENT_WAIT = 30
# Settings pages to fix things in
SETTINGS = '/config'


def _deluge_link():
    """ Log in to Deluge, without check_link adding the labels """
    if not CONFIG['DELUGE_USER']:
        ok = bool(deluge._get_auth())
        return ('' if ok else 'Could not log in to its web interface'), ok
    from deluge_client import DelugeRPCClient
    client = DelugeRPCClient(CONFIG['DELUGE_HOST'].replace('https://', '').replace('http://', ''),
                             check_int(CONFIG['DELUGE_PORT'], 0), CONFIG['DELUGE_USER'], CONFIG['DELUGE_PASS'])
    client.connect()
    return '', True


# the download clients: setting that switches each on, its name, and how to check it
CLIENTS = (
    ('NZB_DOWNLOADER_SABNZBD', 'SABnzbd', sabnzbd.check_link),
    ('NZB_DOWNLOADER_NZBGET', 'NZBGet', nzbget.check_link),
    ('NZB_DOWNLOADER_SYNOLOGY', 'Synology Download Station', synology.check_link),
    ('TOR_DOWNLOADER_QBITTORRENT', 'qBittorrent', qbittorrent.check_link),
    ('TOR_DOWNLOADER_TRANSMISSION', 'Transmission', transmission.check_link),
    ('TOR_DOWNLOADER_DELUGE', 'Deluge', _deluge_link),
    ('TOR_DOWNLOADER_RTORRENT', 'rTorrent', rtorrent.check_link),
    ('TOR_DOWNLOADER_UTORRENT', 'uTorrent', utorrent.check_link),
    ('TOR_DOWNLOADER_SYNOLOGY', 'Synology Download Station', synology.check_link),
)
_answers: dict[str, tuple[float, bool, str]] = {}
_answers_lock = threading.Lock()


def _check(source: str, kind: str, message: str, link: str = '') -> dict:
    return {'source': source, 'type': kind, 'message': message, 'link': link}


def _folder(path: str) -> str:
    """ A folder setting as LazyLibrarian reads it, ./ is below where it runs from """
    if path and path[:2] in ('./', '.\\'):
        return os.path.join(DIRS.PROG_DIR, path[2:])
    return path


def _client_answer(setting: str, name: str, check) -> tuple[bool, str]:
    now = time.monotonic()
    with _answers_lock:
        kept = _answers.get(setting)
    if kept and now - kept[0] < CLIENT_KEEP:
        return kept[1], kept[2]
    try:
        message, ok = check()
    except Exception as why:
        message, ok = f"{type(why).__name__}: {why}", False
    message = ' '.join(str(message or '').split())
    with _answers_lock:
        _answers[setting] = (now, ok, message)
    return ok, message


def client_checks() -> list[dict]:
    """ Can each download client that is switched on be reached """
    enabled = [client for client in CLIENTS if CONFIG.get_bool(client[0])]
    checks = []
    if not enabled:
        return checks
    pool = ThreadPoolExecutor(max_workers=len(enabled))
    try:
        futures = [(name, pool.submit(_client_answer, setting, name, check)) for setting, name, check in enabled]
        for name, future in futures:
            try:
                ok, message = future.result(timeout=CLIENT_WAIT)
            except Exception:
                ok, message = False, 'It did not answer'
            if not ok:
                checks.append(_check('DownloadClientStatusCheck', 'error',
                                     f"Unable to communicate with {name}. {message}".strip(), SETTINGS))
    finally:
        pool.shutdown(wait=False)
    return checks


def checks() -> list[dict]:
    """ Everything that needs looking at, errors first """
    found = []
    if not CONFIG.use_any():
        found.append(_check('IndexerCheck', 'warning', "No indexers are enabled, LazyLibrarian won't find "
                            "releases automatically. Add one in Settings, Providers", SETTINGS))
    blocked = BLOCKHANDLER.blocked()
    if blocked:
        names = ', '.join(entry['name'] for entry in blocked)
        found.append(_check('IndexerStatusCheck', 'warning',
                            f"{plural(len(blocked), 'Indexer')} unavailable due to failures: {names}", ''))

    usenet = [name for setting, name, _check_link in CLIENTS if setting.startswith('NZB') and CONFIG.get_bool(setting)]
    torrent = [name for setting, name, _check_link in CLIENTS if setting.startswith('TOR') and CONFIG.get_bool(setting)]
    if CONFIG.use_nzb() and not usenet and not CONFIG.get_bool('NZB_DOWNLOADER_BLACKHOLE'):
        found.append(_check('DownloadClientCheck', 'warning', "There are usenet indexers but no usenet download "
                            "client to send their releases to. Add one in Settings, Downloaders", SETTINGS))
    if CONFIG.use_tor() and not torrent and not CONFIG.get_bool('TOR_DOWNLOADER_BLACKHOLE'):
        found.append(_check('DownloadClientCheck', 'warning', "There are torrent indexers but no torrent download "
                            "client to send their releases to. Add one in Settings, Downloaders", SETTINGS))
    found.extend(client_checks())

    libraries = []
    if CONFIG.get_bool('EBOOK_TAB'):
        libraries.append(('eBook', CONFIG['EBOOK_DIR']))
    if CONFIG.get_bool('AUDIO_TAB'):
        libraries.append(('Audiobook', CONFIG['AUDIO_DIR']))
    for label, path in libraries:
        folder = _folder(path)
        if not folder:
            found.append(_check('RootFolderCheck', 'error', f"No {label} library folder is set. "
                                f"Set it in Settings, Processing", SETTINGS))
        elif not os.path.isdir(folder):
            found.append(_check('RootFolderCheck', 'error', f"The {label} library folder [{folder}] is missing",
                                SETTINGS))
        elif not os.access(folder, os.W_OK):
            found.append(_check('RootFolderCheck', 'error', f"LazyLibrarian can't write to the {label} library "
                                f"folder [{folder}]", SETTINGS))
    for path in get_list(CONFIG['DOWNLOAD_DIR'], ','):
        folder = _folder(path)
        if folder and not os.path.isdir(folder):
            found.append(_check('DownloadFolderCheck', 'warning', f"The download folder [{folder}] is missing",
                                SETTINGS))

    for mapping in remotepaths.mappings():
        if not os.path.isdir(mapping['LocalPath']):
            found.append(_check('RemotePathMappingCheck', 'error',
                                f"The remote path mapping of {mapping['RemotePath']} on {mapping['Host']} goes to "
                                f"[{mapping['LocalPath']}], which LazyLibrarian can't see", SETTINGS))

    db = database.DBConnection()
    try:
        # as the queue shows them, without asking the download clients how far they've got
        row = db.match("SELECT COUNT(*) AS counter FROM wanted WHERE Status='Snatched' AND "
                       "IFNULL(Source,'')!='MANUAL' AND DLResult LIKE ?", (f"{queue.BLOCKED}%",))
    finally:
        db.close()
    blocked_imports = row['counter'] if row else 0
    if blocked_imports:
        found.append(_check('ImportBlockedCheck', 'warning',
                            f"{blocked_imports} {plural(blocked_imports, 'download')} could not be imported. "
                            f"Hover the warning in the queue to see why, and use Manual Import",
                            '/activity/queue'))

    if backups.RESTORED:
        found.append(_check('RestoreCheck', 'notice', backups.RESTORED, '/system/backup'))

    behind = CONFIG.get_int('COMMITS_BEHIND')
    if behind > 0:
        found.append(_check('UpdateCheck', 'notice', f"A new version is available, {behind} "
                            f"{plural(behind, 'change')} behind", '/system/updates'))
    order = {'error': 0, 'warning': 1, 'notice': 2}
    return sorted(found, key=lambda check: order.get(check['type'], 3))


def disk_space() -> list[dict]:
    """ The free and total space of each disk the libraries, downloads and LazyLibrarian's data are on """
    places = [(DIRS.DATADIR, 'LazyLibrarian data')]
    if CONFIG.get_bool('EBOOK_TAB'):
        places.append((_folder(CONFIG['EBOOK_DIR']), 'eBook library'))
    if CONFIG.get_bool('AUDIO_TAB'):
        places.append((_folder(CONFIG['AUDIO_DIR']), 'Audiobook library'))
    places += [(_folder(path), 'Downloads') for path in get_list(CONFIG['DOWNLOAD_DIR'], ',')]
    disks = {}
    for path, label in places:
        if not path or not os.path.isdir(path):
            continue
        with contextlib.suppress(OSError):
            device = os.stat(path).st_dev
            if device in disks:
                if label not in disks[device]['label']:
                    disks[device]['label'] += f", {label}"
                continue
            usage = shutil.disk_usage(path)
            disks[device] = {'path': path, 'label': label, 'free_space': usage.free, 'total_space': usage.total}
    return list(disks.values())
