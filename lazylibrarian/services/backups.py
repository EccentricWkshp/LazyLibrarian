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

""" Backups, like Sonarr's System, Backup: the database and settings in a .tgz, made on a schedule,
by hand, or before an update, kept in Backups/<type> in the data folder, and restored.

A restore can't replace the database while LazyLibrarian has it open, so, as Sonarr does, it is
unpacked into a folder of its own and put in place when LazyLibrarian next starts, before it
reads its settings or opens the database. What was there is kept as a backup of its own first """

import contextlib
import datetime
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time

from lazylibrarian.filesystem import DIRS

FOLDER = 'Backups'
TYPES = ('scheduled', 'manual', 'update', 'restore')
# what the source passed to dbbackup was called before backups had types
SOURCES = {'scheduled': 'scheduled', 'lazylibrarian': 'manual', 'api': 'manual', 'manual': 'manual',
           'upgrade': 'update', 'update': 'update', 'restore': 'restore'}
# what a backup holds, besides the database
SETTINGS_FILES = ('config.ini', 'dicts.json', 'genres.json', 'filetemplate.text')
# the folder a restore waits in until LazyLibrarian starts again
PENDING = 'restore'
# what the restore done as LazyLibrarian started did, for Health to say
RESTORED = ''


class BackupError(Exception):
    pass


def backup_type(source: str) -> str:
    return SOURCES.get(source, 'manual')


def folder(kind: str = '') -> str:
    path = os.path.join(DIRS.DATADIR, FOLDER, kind) if kind else os.path.join(DIRS.DATADIR, FOLDER)
    return path


def file_name(kind: str, when: float | None = None) -> str:
    """ lazylibrarian_manual_2026.10.26_16.12.52.tgz, like Sonarr's names """
    stamp = time.strftime('%Y.%m.%d_%H.%M.%S', time.localtime(when or time.time()))
    return f"lazylibrarian_{kind}_{stamp}.tgz"


def archive(database_file: str, kind: str, settings_dir: str, config_file: str = '') -> str:
    """ Pack a database file and the settings into a new backup of this kind, returns its path """
    target_dir = folder(kind)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, file_name(kind))
    if os.path.exists(target):  # two in one second
        target = target.replace('.tgz', f"_{int(time.time() * 1000) % 1000:03d}.tgz")
    with tarfile.open(target, mode='w:gz') as tar:
        tar.add(database_file, arcname=DIRS.DBFILENAME)
        for name in SETTINGS_FILES:
            path = config_file if name == 'config.ini' and config_file else os.path.join(settings_dir, name)
            if os.path.isfile(path):
                tar.add(path, arcname=name)
    return target


def _legacy(name: str) -> str:
    """ The type of a backup from before they had folders, scheduled_Mon_Oct_26_16_12_52_2026.tgz in
    the data folder, '' for any other file """
    prefix = name.split('_', 1)[0]
    if name.endswith('.tgz') and prefix in SOURCES and name.count('_') >= 5:
        return SOURCES[prefix]
    return ''


def _entries() -> list[tuple[str, str, str]]:
    """ (id, type, path) of every backup. An id is the type and file name, which is all a request
    can name, so it can't reach other files """
    found = []
    for kind in TYPES:
        with contextlib.suppress(OSError):
            for name in os.listdir(folder(kind)):
                if name.endswith('.tgz'):
                    found.append((f"{kind}/{name}", kind, os.path.join(folder(kind), name)))
    with contextlib.suppress(OSError):
        for name in os.listdir(DIRS.DATADIR):
            kind = _legacy(name)
            if kind and os.path.isfile(os.path.join(DIRS.DATADIR, name)):
                found.append((f"legacy/{name}", kind, os.path.join(DIRS.DATADIR, name)))
    return found


def list_backups() -> list[dict]:
    """ The backups, the most recent first """
    backups = []
    for backup_id, kind, path in _entries():
        with contextlib.suppress(OSError):
            stat = os.stat(path)
            backups.append({'id': backup_id, 'name': os.path.basename(path), 'type': kind, 'size': stat.st_size,
                            'time': datetime.datetime.fromtimestamp(stat.st_mtime).astimezone()
                            .isoformat(timespec='seconds')})
    return sorted(backups, key=lambda backup: backup['time'], reverse=True)


def path_of(backup_id: str) -> str:
    from lazylibrarian.services import NotFoundError
    for found_id, _kind, path in _entries():
        if found_id == backup_id:
            return path
    raise NotFoundError(f'No backup {backup_id}')


def delete(backup_id: str):
    path = path_of(backup_id)
    os.remove(path)
    logging.getLogger(__name__).info(f"Deleted the backup {os.path.basename(path)}")


def clean_scheduled(days: int, now: float | None = None) -> int:
    """ Delete scheduled backups older than days, as Sonarr does, returns how many. 0 keeps them """
    if days <= 0:
        return 0
    limit = (now or time.time()) - days * 86400
    removed = 0
    for _backup_id, kind, path in _entries():
        if kind == 'scheduled':
            with contextlib.suppress(OSError):
                if os.path.getmtime(path) < limit:
                    os.remove(path)
                    removed += 1
    if removed:
        logging.getLogger(__name__).info(f"Deleted {removed} scheduled backups older than {days} days")
    return removed


def _check(staging: str):
    """ That a backup unpacked here is LazyLibrarian's: its database can be read """
    from lazylibrarian.services import InvalidRequestError
    database_file = os.path.join(staging, DIRS.DBFILENAME)
    if not os.path.isfile(database_file):
        raise InvalidRequestError(f"That isn't a LazyLibrarian backup, it has no {DIRS.DBFILENAME}")
    try:
        connection = sqlite3.connect(f"file:{database_file}?mode=ro", uri=True)
        try:
            result = connection.execute('PRAGMA quick_check').fetchone()[0]
            connection.execute('SELECT COUNT(*) FROM books').fetchone()
        finally:
            connection.close()
    except sqlite3.Error as why:
        raise InvalidRequestError(f"The backup's database can't be read: {why}") from None
    if result != 'ok':
        raise InvalidRequestError(f"The backup's database is damaged: {result}")


def stage_restore(archive_path: str, name: str = ''):
    """ Unpack a backup to be put in place when LazyLibrarian next starts. Only the files a backup
    holds are taken, by name, so nothing in it can land anywhere else """
    from lazylibrarian.services import InvalidRequestError
    pending = os.path.join(DIRS.DATADIR, PENDING)
    shutil.rmtree(pending, ignore_errors=True)
    staging = tempfile.mkdtemp(prefix='restore-', dir=DIRS.DATADIR)
    try:
        try:
            with tarfile.open(archive_path, mode='r:*') as tar:
                for member in tar.getmembers():
                    if member.isfile() and member.name in (DIRS.DBFILENAME, *SETTINGS_FILES):
                        source = tar.extractfile(member)
                        with open(os.path.join(staging, member.name), 'wb') as out:
                            shutil.copyfileobj(source, out)
        except (tarfile.TarError, OSError, EOFError) as why:
            raise InvalidRequestError(f"That backup can't be read: {why}") from None
        _check(staging)
        with open(os.path.join(staging, 'restore-from.txt'), 'w', encoding='utf-8') as note:
            note.write(name or os.path.basename(archive_path))
        os.replace(staging, pending)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logging.getLogger(__name__).info(f"Restoring {name or os.path.basename(archive_path)} when LazyLibrarian restarts")


def apply_pending_restore(config_file: str) -> str:
    """ At startup, before the settings are read or the database opened: put a staged restore in
    place. Returns what was done, '' when there was nothing to do """
    pending = os.path.join(DIRS.DATADIR, PENDING)
    if not os.path.isdir(pending):
        return ''
    database_file = DIRS.get_dbfile()
    note = os.path.join(pending, 'restore-from.txt')
    restored = 'a backup'
    if os.path.isfile(note):
        with open(note, encoding='utf-8') as f:
            restored = f.read().strip() or restored
    if not os.path.isfile(os.path.join(pending, DIRS.DBFILENAME)):
        shutil.rmtree(pending, ignore_errors=True)
        return f"Did not restore {restored}, it has no database"
    kept = ''
    if os.path.isfile(database_file):
        # what was there, its write-ahead log included, so nothing in it is lost
        target_dir = folder('restore')
        os.makedirs(target_dir, exist_ok=True)
        kept = os.path.join(target_dir, file_name('restore'))
        with tarfile.open(kept, mode='w:gz') as tar:
            for suffix in ('', '-wal', '-shm'):
                if os.path.isfile(database_file + suffix):
                    tar.add(database_file + suffix, arcname=DIRS.DBFILENAME + suffix)
            for name in SETTINGS_FILES:
                path = config_file if name == 'config.ini' else os.path.join(DIRS.DATADIR, name)
                if os.path.isfile(path):
                    tar.add(path, arcname=name)
    # the old database's write-ahead log would be played into the restored one
    for suffix in ('-wal', '-shm'):
        with contextlib.suppress(FileNotFoundError):
            os.remove(database_file + suffix)
    for name in os.listdir(pending):
        if name == DIRS.DBFILENAME:
            os.replace(os.path.join(pending, name), database_file)
        elif name in SETTINGS_FILES:
            os.replace(os.path.join(pending, name), config_file if name == 'config.ini' else
                       os.path.join(DIRS.DATADIR, name))
    shutil.rmtree(pending, ignore_errors=True)
    message = f"Restored {restored}"
    if kept:
        message += f", what was there before is in {kept}"
    return message
