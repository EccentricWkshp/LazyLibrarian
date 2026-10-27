#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test System, Backup (services/backups.py and common.dbbackup), Updates (services/updates.py),
#   and the log as System, Events and Log Files

import io
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from unittest import mock

import lazylibrarian
from lazylibrarian.common import dbbackup
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.services import InvalidRequestError, NotFoundError, backups, system, updates
from unittests.unittesthelpers import LLTestCaseWithStartup


def _tgz(path, members: dict):
    with tarfile.open(path, mode='w:gz') as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _database(path, title='Restored Book'):
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE books (BookID TEXT, BookName TEXT)')
    connection.execute("INSERT INTO books VALUES ('r1', ?)", (title,))
    connection.commit()
    connection.close()
    with open(path, 'rb') as f:
        return f.read()


class BackupsTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        shutil.rmtree(backups.folder(), ignore_errors=True)
        self.addCleanup(shutil.rmtree, backups.folder(), True)

    def test_a_backup(self):
        path, error = dbbackup('lazylibrarian')
        self.assertEqual(error, '')
        self.assertEqual(os.path.dirname(path), backups.folder('manual'), 'In its type\'s folder, like Sonarr')
        self.assertRegex(os.path.basename(path), r'^lazylibrarian_manual_\d{4}\.\d\d\.\d\d_\d\d\.\d\d\.\d\d\.tgz$')
        with tarfile.open(path) as tar:
            self.assertIn(DIRS.DBFILENAME, tar.getnames())
        found = backups.list_backups()
        self.assertEqual([(b['type'], b['name']) for b in found], [('manual', os.path.basename(path))])

    def test_the_old_backups_are_listed(self):
        old = os.path.join(DIRS.DATADIR, 'scheduled_Mon_Oct_26_16_12_52_2026.tgz')
        _tgz(old, {DIRS.DBFILENAME: b'x'})
        self.addCleanup(lambda: os.path.exists(old) and os.remove(old))
        found = backups.list_backups()
        self.assertEqual([(b['id'], b['type']) for b in found],
                         [('legacy/scheduled_Mon_Oct_26_16_12_52_2026.tgz', 'scheduled')])
        self.assertEqual(backups.path_of(found[0]['id']), old)

    def test_only_backups_can_be_named(self):
        for backup_id in ('manual/../../config.ini', 'legacy/config.ini', 'nosuch/x.tgz'):
            with self.assertRaises(NotFoundError):
                backups.path_of(backup_id)

    def test_scheduled_backups_are_kept_a_while(self):
        os.makedirs(backups.folder('scheduled'))
        os.makedirs(backups.folder('manual'))
        old = os.path.join(backups.folder('scheduled'), 'lazylibrarian_scheduled_2026.01.01_00.00.00.tgz')
        new = os.path.join(backups.folder('scheduled'), 'lazylibrarian_scheduled_2026.10.26_00.00.00.tgz')
        manual = os.path.join(backups.folder('manual'), 'lazylibrarian_manual_2026.01.01_00.00.00.tgz')
        for path in (old, new, manual):
            _tgz(path, {DIRS.DBFILENAME: b'x'})
        month_ago = time.time() - 40 * 86400
        os.utime(old, (month_ago, month_ago))
        os.utime(manual, (month_ago, month_ago))
        self.assertEqual(backups.clean_scheduled(0), 0, '0 keeps them all')
        self.assertEqual(backups.clean_scheduled(28), 1)
        self.assertEqual((os.path.exists(old), os.path.exists(new), os.path.exists(manual)), (False, True, True),
                         'Only scheduled ones, as Sonarr')

    def test_a_restore(self):
        data = tempfile.mkdtemp(dir=DIRS.DATADIR)
        self.addCleanup(shutil.rmtree, data, True)
        with mock.patch.object(DIRS, 'DATADIR', data):
            config = os.path.join(data, 'config.ini')
            current = os.path.join(data, DIRS.DBFILENAME)
            _database(current, 'Current Book')
            with open(config, 'w') as f:
                f.write('[General]\ncurrent = 1\n')
            with open(current + '-wal', 'wb') as f:
                f.write(b'the current database\'s log')
            archive = os.path.join(data, 'upload.tgz')
            staged = _database(os.path.join(data, 'staged.db'))
            _tgz(archive, {DIRS.DBFILENAME: staged, 'config.ini': b'[General]\nrestored = 1\n',
                           '../outside.txt': b'no', 'notes.txt': b'no'})

            backups.stage_restore(archive, 'lazylibrarian_manual_2026.10.26_00.00.00.tgz')
            pending = os.path.join(data, backups.PENDING)
            self.assertEqual(sorted(os.listdir(pending)), sorted(['config.ini', DIRS.DBFILENAME, 'restore-from.txt']),
                             'Only what a backup holds')
            self.assertFalse(os.path.exists(os.path.join(DIRS.DATADIR, '..', 'outside.txt')))

            message = backups.apply_pending_restore(config)
            self.assertTrue(message.startswith('Restored lazylibrarian_manual_2026.10.26_00.00.00.tgz'), message)
            connection = sqlite3.connect(current)
            self.assertEqual(connection.execute('SELECT BookName FROM books').fetchone()[0], 'Restored Book')
            connection.close()
            with open(config) as f:
                self.assertIn('restored = 1', f.read())
            self.assertFalse(os.path.exists(current + '-wal'), 'The old log would be played into it')
            self.assertFalse(os.path.exists(pending))
            kept = [b for b in backups.list_backups() if b['type'] == 'restore']
            self.assertEqual(len(kept), 1, 'What was there is a backup of its own')
            with tarfile.open(backups.path_of(kept[0]['id'])) as tar:
                self.assertEqual(sorted(tar.getnames()),
                                 sorted(['config.ini', DIRS.DBFILENAME, f'{DIRS.DBFILENAME}-wal']))
            self.assertEqual(backups.apply_pending_restore(config), '', 'Once')

    def test_not_a_backup(self):
        archive = os.path.join(DIRS.DATADIR, 'notabackup.tgz')
        self.addCleanup(lambda: os.path.exists(archive) and os.remove(archive))
        _tgz(archive, {'readme.txt': b'hello'})
        with self.assertRaises(InvalidRequestError):
            backups.stage_restore(archive)
        with open(archive, 'wb') as f:
            f.write(b'not even a tar')
        with self.assertRaises(InvalidRequestError):
            backups.stage_restore(archive)
        self.assertFalse(os.path.exists(os.path.join(DIRS.DATADIR, backups.PENDING)))


class UpdatesTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        saved = CONFIG.get_int('COMMITS_BEHIND'), CONFIG['INSTALL_TYPE'], lazylibrarian.COMMIT_LIST
        self.addCleanup(lambda: (CONFIG.set_int('COMMITS_BEHIND', saved[0]), CONFIG.set_str('INSTALL_TYPE', saved[1]),
                                 setattr(lazylibrarian, 'COMMIT_LIST', saved[2])))
        patch = mock.patch.object(updates, 'docker', return_value=False)
        patch.start()
        self.addCleanup(patch.stop)

    def test_behind(self):
        CONFIG.set_int('COMMITS_BEHIND', 2)
        CONFIG.set_str('INSTALL_TYPE', 'git')
        lazylibrarian.COMMIT_LIST = 'Newest change\nOlder change\n'
        found = updates.info()
        self.assertEqual((found['changes'], found['can_install'], found['why_not']),
                         (['Newest change', 'Older change'], True, ''))
        with mock.patch.object(updates.system, 'request_stop') as stop:
            self.assertEqual(updates.install(), 'Updating, LazyLibrarian will restart')
        stop.assert_called_once_with('update')

    def test_not_by_itself(self):
        CONFIG.set_int('COMMITS_BEHIND', 2)
        CONFIG.set_str('INSTALL_TYPE', 'git')
        with mock.patch.object(updates, 'docker', return_value=True):
            found = updates.info()
            self.assertFalse(found['can_install'])
            self.assertIn('Docker', found['why_not'])
            with self.assertRaises(InvalidRequestError):
                updates.install()
        lazylibrarian.COMMIT_LIST = 'Big change ** MANUAL **\n'
        self.assertIn('by hand', updates.info()['why_not'])

    def test_up_to_date_or_unknown(self):
        CONFIG.set_int('COMMITS_BEHIND', 0)
        lazylibrarian.COMMIT_LIST = ''
        self.assertEqual((updates.info()['changes'], updates.info()['can_install']), ([], False))
        CONFIG.set_int('COMMITS_BEHIND', -1)
        lazylibrarian.COMMIT_LIST = 'Unknown version of lazylibrarian (x)\nRun lazylibrarian with --update'
        self.assertTrue(updates.info()['message'].startswith('Unknown version'))


class LogTest(LLTestCaseWithStartup):

    def test_events(self):
        rows = [['2026-10-26 14:52:36,140', 'INFO', 'MAIN', 'a.py', 'f', 1, 'first'],
                ['2026-10-26 14:52:37,140', 'WARNING', 'MAIN', 'a.py', 'f', 2, 'second'],
                ['2026-10-26 14:52:38,140', 'DEBUG', 'MAIN', 'a.py', 'f', 3, 'third']]
        with mock.patch.object(system.LOGCONFIG, 'get_ui_logrows', return_value=(rows, 3)):
            everything = system.list_events().items
            warnings = system.list_events('warn').items
            with self.assertRaises(InvalidRequestError):
                system.list_events('loud')
        self.assertEqual([event['message'] for event in everything], ['third', 'second', 'first'], 'Newest first')
        self.assertEqual(everything[0]['time'], '2026-10-26 14:52:38.140')
        self.assertEqual([event['message'] for event in warnings], ['second'])

    def test_log_files(self):
        names = [f['filename'] for f in system.list_log_files()]
        self.assertTrue(names, 'The tests write a log')
        self.assertEqual(system.log_file_path(names[0]), os.path.join(CONFIG['LOGDIR'], names[0]))
        with self.assertRaises(NotFoundError):
            system.log_file_path('../config.ini')
