#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/system.py

import os
import threading
from unittest import mock

import lazylibrarian
from lazylibrarian.config2 import CONFIG
from lazylibrarian.dbupgrade import db_current_version
from lazylibrarian.formatter import thread_name
from lazylibrarian.services import InvalidRequestError, system
from unittests.unittesthelpers import TESTDIR, LLTestCaseWithDB


class StartTaskTest(LLTestCaseWithDB):

    def test_starts_once(self):
        release = threading.Event()
        calls = []

        def task(value):
            calls.append(value)
            release.wait(5)

        self.assertTrue(system.start_task('LLTESTTASK', task, 1))
        self.assertTrue(system.is_running('LLTESTTASK'))
        self.assertFalse(system.start_task('LLTESTTASK', task, 2), 'Already running')
        release.set()
        for t in threading.enumerate():
            if t.name == 'LLTESTTASK':
                t.join(5)
        self.assertEqual(calls, [1])
        self.assertFalse(system.is_running('LLTESTTASK'))

    def test_scans_and_imports_use_their_thread_names(self):
        with mock.patch.object(system, 'start_task', return_value=True) as start:
            system.start_library_scan('AudioBook')
            system.start_magazine_scan()
            system.start_magazine_scan('Wired')
            system.start_alternate_import('eBook')
        names = [c.args[0] for c in start.call_args_list]
        self.assertEqual(names, ['AUDIOBOOK_SCAN', 'MAGAZINE_SCAN', 'MAGAZINE_SCAN_Wired', 'IMPORTALT_eBook'])

    def test_issue_import_needs_a_title(self):
        with self.assertRaises(InvalidRequestError):
            system.start_issue_import('')


class SystemServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        saved = {key: CONFIG[key] for key in ('EBOOK_TAB', 'AUDIO_TAB', 'OL_USE_DUMP', 'ALTERNATE_DIR',
                                              'DETAILEDUILOG')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])

    def test_book_libraries(self):
        for ebook, audio, expected in ((True, True, ['eBook', 'AudioBook']), (False, True, ['AudioBook']),
                                       (False, False, [])):
            CONFIG.set_bool('EBOOK_TAB', ebook)
            CONFIG.set_bool('AUDIO_TAB', audio)
            self.assertEqual(system.book_libraries(), expected)

    def test_openlibrary_dump_must_be_switched_on(self):
        CONFIG.set_bool('OL_USE_DUMP', False)
        with self.assertRaises(InvalidRequestError):
            system.start_openlibrary_dump()

    def test_csv_import_needs_the_file(self):
        CONFIG.set_str('ALTERNATE_DIR', os.path.join(TESTDIR, 'no-such-folder'))
        with self.assertRaises(InvalidRequestError):
            system.start_csv_import('eBook')

    def test_request_stop(self):
        self.addCleanup(setattr, lazylibrarian, 'SIGNAL', lazylibrarian.SIGNAL)
        system.request_stop('restart')
        self.assertEqual(lazylibrarian.SIGNAL, 'restart')
        with self.assertRaises(InvalidRequestError):
            system.request_stop('explode')

    def test_update_status(self):
        self.addCleanup(setattr, lazylibrarian, 'COMMIT_LIST', lazylibrarian.COMMIT_LIST)
        lazylibrarian.COMMIT_LIST = 'abc fix\n** MANUAL **'
        with mock.patch.object(system.versioncheck, 'check_for_updates') as check, \
                mock.patch.object(CONFIG, 'get_int', return_value=2):
            status = system.update_status()
        check.assert_called_once()
        self.assertEqual((status['behind'], status['manual']), (2, True))
        self.assertIn('abc fix', status['commits'])

    def test_list_log(self):
        rows = [['2026-01-02', 'INFO', 'MAIN', 'a.py', 'f', 10, 'second'],
                ['2026-01-01', 'ERROR', 'MAIN', 'b.py', 'g', 20, 'first']]
        with mock.patch.object(system.LOGCONFIG, 'get_ui_logrows', return_value=(rows, 5)) as logrows:
            page = system.list_log(search='x')
            logrows.assert_called_with('x')
            self.assertEqual([i['Message'] for i in page.items], ['second', 'first'])
            self.assertEqual((page.total, page.matched), (5, 2))
            page = system.list_log(sort='Line', descending=False, limit=1)
            self.assertEqual(page.items, [dict(zip(system.LOG_FIELDS, rows[0], strict=True))])

    def test_toggle_detailed_log(self):
        CONFIG.set_bool('DETAILEDUILOG', False)
        self.assertTrue(system.toggle_detailed_log())
        self.assertTrue(CONFIG.get_bool('DETAILEDUILOG'))
        self.assertFalse(system.toggle_detailed_log())

    def test_database_ok(self):
        self.assertTrue(system.database_ok())
        broken = mock.MagicMock()
        broken.return_value.match.side_effect = Exception('database is locked')
        with mock.patch.object(system.database, 'DBConnection', broken):
            self.assertFalse(system.database_ok())

    def test_status(self):
        saved = CONFIG['HTTP_ROOT']
        self.addCleanup(CONFIG.set_str, 'HTTP_ROOT', saved)
        CONFIG.set_str('HTTP_ROOT', 'books/')
        status = system.status()
        self.assertEqual((status['app_name'], status['url_base']), ('LazyLibrarian', '/books'))
        self.assertEqual(status['database_version'], db_current_version, 'The test database is a new one')

    def test_sync_calibre_marks_itself_running(self):
        seen = []
        with mock.patch.object(system, 'sync_calibre_list', side_effect=lambda userid: seen.append(thread_name())
                               or 'synced'):
            before = thread_name()
            self.assertEqual(system.sync_calibre('u1'), 'synced')
            self.assertEqual(seen, ['CalSync'])
            self.assertEqual(thread_name(), before)
        with mock.patch.object(system, 'is_running', return_value=True):
            self.assertIsNone(system.sync_calibre('u1'))

    def test_search_needs_providers(self):
        with mock.patch.object(CONFIG, 'use_any', return_value=False), \
                mock.patch.object(system, 'schedule_job') as schedule:
            self.assertFalse(system.start_search('books'))
        schedule.assert_not_called()

    def test_search_books_restarts_the_search_jobs(self):
        with mock.patch.object(CONFIG, 'use_any', return_value=True), \
                mock.patch.object(CONFIG, 'use_rss', return_value=True), \
                mock.patch.object(system, 'schedule_job') as schedule:
            self.assertTrue(system.start_search('audio'))
        self.assertEqual([c.args[1] for c in schedule.call_args_list],
                         ['search_book', 'search_book', 'search_rss_book', 'search_rss_book'])
        with mock.patch.object(CONFIG, 'use_any', return_value=True), self.assertRaises(InvalidRequestError):
            system.start_search('nothing')

    def test_search_magazines_starts_a_task(self):
        with mock.patch.object(CONFIG, 'use_any', return_value=True), \
                mock.patch.object(system, 'start_task', return_value=True) as start, \
                mock.patch.object(system, 'schedule_job') as schedule:
            system.start_search('magazines')
        self.assertEqual(start.call_args.args[0], 'SEARCHALLMAG')
        self.assertEqual(schedule.call_args.kwargs['target'], 'search_magazines')

    def test_postprocessor_schedule_only_restarts_when_it_starts(self):
        with mock.patch.object(system, 'start_task', return_value=False), \
                mock.patch.object(system, 'schedule_job') as schedule:
            self.assertFalse(system.start_postprocessor())
        schedule.assert_not_called()

    def test_wishlist_search_needs_providers(self):
        with mock.patch.object(CONFIG, 'use_wishlist', return_value=False), \
                mock.patch.object(system, 'search_wishlist') as search:
            self.assertFalse(system.search_wishlists())
        search.assert_not_called()
