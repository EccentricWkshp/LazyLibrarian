#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test Interactive Search (services/releases.py and resultlist.evaluate_results), Wanted,
#   Missing (services/wanted.py) and the search commands

import time
from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.resultlist import evaluate_results, find_best_result
from lazylibrarian.services import InvalidRequestError, NotFoundError, commands, releases, wanted
from unittests.test_resultlist import _make_book, _make_tor_result
from unittests.unittesthelpers import LLTestCaseWithStartup


class SettingsMixin:
    SETTINGS = ('IMP_PREFLANG', 'REJECT_WORDS', 'MATCH_RATIO', 'MIN_SEEDERS', 'EBOOK_TAB', 'AUDIO_TAB')

    def keep_settings(self):
        saved = {key: CONFIG[key] for key in self.SETTINGS}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])


class EvaluateTest(SettingsMixin, LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        self.keep_settings()
        CONFIG.set_csv('IMP_PREFLANG', 'en, eng, English')
        CONFIG.set_str('REJECT_WORDS', 'audiobook, mp3')
        CONFIG.set_int('MIN_SEEDERS', 1)

    def test_every_reason_is_given(self):
        book = _make_book("Some Author", "Some Book")
        results = evaluate_results([_make_tor_result("Some Author - Some Book audiobook [SWE]", seeders=0),
                                    _make_tor_result("Some Author - Some Book epub", url="http://x/2")],
                                   book, "book", "tor")
        rejected, approved = results
        self.assertEqual(len(rejected['rejections']), 3, rejected['rejections'])
        self.assertIn("Contains audiobook, one of the words to reject", rejected['rejections'])
        self.assertIn("Language 'swe' is not a preferred language", rejected['rejections'])
        self.assertIn("Only 0 seeders, the minimum is 1", rejected['rejections'])
        self.assertEqual(approved['rejections'], [])
        self.assertGreater(rejected['score'], 0, 'Rejected ones are scored too, to show')

    def test_the_automatic_search_takes_what_has_no_rejections(self):
        book = _make_book("Some Author", "Some Book")
        match = find_best_result([_make_tor_result("Some Author - Some Book audiobook", url="http://x/1"),
                                  _make_tor_result("Some Author - Some Book epub", url="http://x/2")],
                                 book, "book", "tor")
        self.assertEqual(match[2], {'NZBurl': 'http://x/2'})
        self.assertIsNone(find_best_result([_make_tor_result("Some Author - Some Book mp3")], book, "book", "tor"))


class InteractiveSearchTest(SettingsMixin, LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        self.keep_settings()
        CONFIG.set_int('MATCH_RATIO', 80)
        CONFIG.set_int('MIN_SEEDERS', 0)
        with DBConnection() as db:
            db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES ('ra1', 'Lee Child', 'Active')")
            db.action("INSERT OR REPLACE INTO books (BookID, AuthorID, BookName, Status, AudioStatus) VALUES "
                      "('rb1', 'ra1', 'Without Fail', 'Skipped', 'Wanted')")
        for name, value in (('total_active_providers', 1),):
            patch = mock.patch.object(CONFIG, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def search(self, *results):
        with mock.patch.object(releases, '_provider_results', return_value=[('tor', list(results))]):
            return releases.search('rb1', 'audiobook')

    def test_releases_with_their_rejections(self):
        found = self.search(_make_tor_result("Lee Child - Without Fail mp3", url="http://x/good"),
                            _make_tor_result("Without Fail Read by Dick Hill Unabridged 2002 64kbps", url="http://x/2"))
        self.assertEqual([release['approved'] for release in found], [True, False], 'What it would take first')
        self.assertEqual(found[0]['protocol'], 'torrent')
        self.assertTrue(found[1]['rejections'][0].startswith('Scores '), found[1]['rejections'])
        self.assertIn('the automatic search needs', found[1]['rejections'][0])

    def test_download_by_id(self):
        release = self.search(_make_tor_result("Lee Child - Without Fail mp3", url="http://x/good"))[0]
        with mock.patch.object(releases, 'download_result', return_value=2) as downloaded:
            self.assertEqual(releases.download(release['id']), 'Downloading Lee Child - Without Fail mp3')
        match, book = downloaded.call_args.args
        self.assertEqual((match[2], book['bookid'], book['library']), ({'NZBurl': 'http://x/good'}, 'rb1', 'AudioBook'))
        with mock.patch.object(releases, 'download_result', return_value=1), self.assertRaises(InvalidRequestError):
            releases.download(release['id'])
        with self.assertRaises(NotFoundError):
            releases.download('nosuchrelease')

    def test_needs_a_book_and_providers(self):
        with self.assertRaises(NotFoundError):
            releases.search('nosuchbook', 'ebook')
        with self.assertRaises(InvalidRequestError):
            releases.search('rb1', 'magazine')
        with mock.patch.object(CONFIG, 'total_active_providers', return_value=0), \
                self.assertRaises(InvalidRequestError):
            releases.search('rb1', 'ebook')


class WantedTest(SettingsMixin, LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        self.keep_settings()
        CONFIG.set_bool('EBOOK_TAB', True)
        CONFIG.set_bool('AUDIO_TAB', True)
        with DBConnection() as db:
            db.action("DELETE FROM books")
            db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES ('wa1', 'Lee Child', 'Active')")
            for book_id, name, status, audio, added in (('w1', 'Without Fail', 'Wanted', 'Wanted', '2026-10-01'),
                                                        ('w2', 'Persuader', 'Open', 'Wanted', '2026-10-02'),
                                                        ('w3', 'The Enemy', 'Skipped', 'Skipped', '2026-10-03')):
                db.action("INSERT INTO books (BookID, AuthorID, BookName, Status, AudioStatus, BookAdded) VALUES "
                          "(?, 'wa1', ?, ?, ?, ?)", (book_id, name, status, audio, added))

    def test_missing(self):
        page = wanted.list_missing()
        self.assertEqual([(r['book_id'], r['media_type']) for r in page.items],
                         [('w2', 'audiobook'), ('w1', 'ebook'), ('w1', 'audiobook')], 'Most recently added first')
        self.assertEqual(wanted.list_missing('ebook').matched, 1)
        self.assertEqual(wanted.list_missing(search='persuader').matched, 1)
        CONFIG.set_bool('AUDIO_TAB', False)
        self.assertEqual(wanted.list_missing().matched, 1, 'Only the libraries shown')
        with self.assertRaises(InvalidRequestError):
            wanted.list_missing(sort='nosuch')

    def wait(self, command):
        for _ in range(200):
            command = commands.get(command['id'])
            if command['status'] in ('completed', 'failed'):
                return command
            time.sleep(0.05)
        raise AssertionError(f'{command} did not finish')

    def test_search_commands(self):
        with mock.patch.object(CONFIG, 'total_active_providers', return_value=1), \
                mock.patch('lazylibrarian.searchbook.search_book', return_value=0) as search:
            command = self.wait(commands.start('BookSearch', {'books': [{'book_id': 'w1', 'media_type': 'audiobook'}]}))
            self.assertEqual(command['status'], 'completed')
            self.assertIn('nothing found', command['message'], 'Not only in the log')
            self.assertEqual(command['result'], {'found': 0})
            search.assert_called_once_with([{'bookid': 'w1'}], 'AudioBook')
            search.reset_mock(return_value=True)
            search.return_value = 2
            command = self.wait(commands.start('MissingBookSearch', {}))
            self.assertEqual(command['message'], 'Search for wanted books completed, 2 books found')
            search.assert_called_once_with(None, None)
        with mock.patch.object(CONFIG, 'total_active_providers', return_value=0):
            command = self.wait(commands.start('BookSearch', {'books': [{'book_id': 'w1', 'media_type': 'ebook'}]}))
        self.assertEqual(command['status'], 'failed')
        self.assertIn('No search providers', command['message'])
