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
    SETTINGS = ('IMP_PREFLANG', 'REJECT_WORDS', 'MATCH_RATIO', 'MIN_SEEDERS', 'EBOOK_TAB', 'AUDIO_TAB', 'MAG_TAB',
                'COMIC_TAB')

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

    def test_a_provider_or_result_that_fails_leaves_the_rest(self):
        good = _make_tor_result("Lee Child - Without Fail mp3", url="http://x/good")
        odd = {**_make_tor_result("Lee Child - Without Fail m4b", url="http://x/odd"), 'tor_title': None}
        with mock.patch.object(CONFIG, 'use_nzb', return_value=True), \
                mock.patch.object(CONFIG, 'use_tor', return_value=True), \
                mock.patch.object(CONFIG, 'use_direct', return_value=False), \
                mock.patch.object(CONFIG, 'use_irc', return_value=False), \
                mock.patch.object(CONFIG, 'use_rss', return_value=False), \
                mock.patch.object(releases, 'iterate_over_znab_sites', side_effect=ValueError('bad page')), \
                mock.patch.object(releases, 'iterate_over_torrent_sites', return_value=([good, odd], 1)):
            found = releases.search('rb1', 'audiobook')
        self.assertEqual([release['title'] for release in found], ['Lee Child - Without Fail mp3'])

    def test_a_torrent_site_that_fails_is_blocked_not_the_search(self):
        from lazylibrarian import providers
        with mock.patch.object(providers, 'torrent_abb', side_effect=AttributeError('no post')), \
                mock.patch.object(providers.BLOCKHANDLER, 'block_provider') as block:
            saved = {key: CONFIG[key] for key in ('ABB', 'ABB_DLTYPES', 'TPB', 'TDL', 'LIME')}
            self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
            for key in ('TPB', 'TDL', 'LIME'):
                CONFIG.set_from_ui(key, False)
            CONFIG.set_from_ui('ABB', True)
            CONFIG.set_from_ui('ABB_DLTYPES', 'A')
            results, count = providers.iterate_over_torrent_sites(_make_book('Lee Child', 'Without Fail'), 'audio')
        self.assertEqual((results, count), ([], 0))
        block.assert_called_once_with('ABB', 'AttributeError: no post')

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
        CONFIG.set_bool('MAG_TAB', False)
        CONFIG.set_bool('COMIC_TAB', False)
        with DBConnection() as db:
            db.action("DELETE FROM books")
            db.action("DELETE FROM magazines")
            db.action("DELETE FROM comics")
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

    def add_magazine_and_comic(self):
        CONFIG.set_bool('MAG_TAB', True)
        CONFIG.set_bool('COMIC_TAB', True)
        with DBConnection() as db:
            db.action("INSERT INTO magazines (Title, Status, IssueDate, MagazineAdded) VALUES "
                      "('The Economist', 'Active', '2026-10-24', '2026-10-04')")
            db.action("INSERT INTO magazines (Title, Status, IssueDate) VALUES ('Paused Weekly', 'Paused', '')")
            db.action("INSERT INTO comics (ComicID, Title, Status, Publisher, LatestIssue, Added) VALUES "
                      "('CV1', 'Saga', 'Active', 'Image', '66', '2026-10-05')")

    def test_magazines_and_comics(self):
        self.add_magazine_and_comic()
        items = {r['id']: r for r in wanted.list_missing().items}
        self.assertEqual(set(items), {'w1:ebook', 'w1:audiobook', 'w2:audiobook', 'The Economist:magazine', 'CV1:comic'},
                         'Active ones, each looked for issue by issue')
        self.assertEqual(items['The Economist:magazine']['subtitle'], 'Latest issue 2026-10-24')
        self.assertEqual((items['CV1:comic']['title'], items['CV1:comic']['author']), ('Saga', 'Image'))
        self.assertEqual(wanted.list_missing('comic').matched, 1)

    def test_searching_for_a_magazine_or_comic(self):
        self.add_magazine_and_comic()
        with mock.patch.object(CONFIG, 'total_active_providers', return_value=1), \
                mock.patch('lazylibrarian.searchmag.search_magazines',
                           side_effect=lambda mags: self.snatch('The Economist')) as mags, \
                mock.patch('lazylibrarian.comicsearch.search_comics') as comics:
            found, message = wanted.search_books([{'book_id': 'The Economist', 'media_type': 'magazine'},
                                                  {'book_id': 'CV1', 'media_type': 'comic'}])
        mags.assert_called_once_with([{'bookid': 'The Economist'}])
        comics.assert_called_once_with('CV1')
        self.assertEqual((found, message), (1, 'Search for 2 items completed, 1 download found'))

    def test_unmonitor(self):
        self.add_magazine_and_comic()
        message = wanted.set_monitored([{'book_id': 'w1', 'media_type': 'audiobook'},
                                        {'book_id': 'The Economist', 'media_type': 'magazine'},
                                        {'book_id': 'CV1', 'media_type': 'comic'}], False)
        self.assertEqual(message, 'No longer looking for 3 items')
        with DBConnection() as db:
            book = db.match("SELECT Status, AudioStatus FROM books WHERE BookID='w1'")
            self.assertEqual((book['Status'], book['AudioStatus']), ('Wanted', 'Skipped'), 'Only the audiobook')
            self.assertEqual(db.match("SELECT Status FROM magazines WHERE Title='The Economist'")['Status'], 'Paused')
            self.assertEqual(db.match("SELECT Status FROM comics WHERE ComicID='CV1'")['Status'], 'Paused')
        self.assertEqual({r['id'] for r in wanted.list_missing().items}, {'w1:ebook', 'w2:audiobook'})
        with self.assertRaises(InvalidRequestError):
            wanted.set_monitored([], False)

    def wait(self, command):
        for _ in range(200):
            command = commands.get(command['id'])
            if command['status'] in ('completed', 'failed'):
                return command
            time.sleep(0.05)
        raise AssertionError(f'{command} did not finish')

    @staticmethod
    def snatch(*books):
        """ What a search does when it finds something: a download in the wanted table """
        with DBConnection() as db:
            for book_id in books:
                db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,Status,AuxInfo) VALUES (?,?,?,'Snatched','eBook')",
                          (book_id, f"http://x/{book_id}", book_id))

    def test_search_commands(self):
        with DBConnection() as db:
            db.action("DELETE FROM wanted")
        with mock.patch.object(CONFIG, 'total_active_providers', return_value=1), \
                mock.patch('lazylibrarian.searchbook.search_book', return_value=0) as search:
            command = self.wait(commands.start('BookSearch', {'books': [{'book_id': 'w1', 'media_type': 'audiobook'}]}))
            self.assertEqual(command['status'], 'completed')
            self.assertIn('nothing found', command['message'], 'Not only in the log')
            self.assertEqual(command['result'], {'found': 0})
            search.assert_called_once_with([{'bookid': 'w1'}], 'AudioBook')
            search.reset_mock()
            search.side_effect = lambda *args: self.snatch('w1', 'w2')
            command = self.wait(commands.start('MissingBookSearch', {}))
            self.assertEqual(command['message'], 'Search for wanted items completed, 2 downloads found')
            search.assert_called_once_with(None, None)
        with mock.patch.object(CONFIG, 'total_active_providers', return_value=0):
            command = self.wait(commands.start('BookSearch', {'books': [{'book_id': 'w1', 'media_type': 'ebook'}]}))
        self.assertEqual(command['status'], 'failed')
        self.assertIn('No search providers', command['message'])
