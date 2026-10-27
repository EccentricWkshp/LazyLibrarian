#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test qualities (quality.py), quality profiles (services/profiles.py), how the search decides with
#   them (resultlist), and Wanted, Cutoff Unmet with its upgrade search

import os
import shutil
import tempfile
from unittest import mock

from lazylibrarian import quality, searchbook
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.resultlist import evaluate_results, find_best_result
from lazylibrarian.services import InvalidRequestError, profiles, wanted
from unittests.test_resultlist import _make_book, _make_tor_result
from unittests.unittesthelpers import LLTestCaseWithStartup

SETTINGS = ('EBOOK_TYPE', 'AUDIOBOOK_TYPE', 'EBOOK_PROFILE', 'AUDIO_PROFILE', 'MATCH_RATIO', 'EBOOK_TAB', 'AUDIO_TAB',
            'REJECT_WORDS', 'IMP_PREFLANG', 'MIN_SEEDERS')


class ProfilesTestCase(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        saved = {key: CONFIG[key] for key in SETTINGS}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
        CONFIG.set_csv('EBOOK_TYPE', 'epub, mobi, pdf')
        CONFIG.set_csv('AUDIOBOOK_TYPE', 'mp3, m4b')
        CONFIG.set_int('EBOOK_PROFILE', 0)
        CONFIG.set_int('AUDIO_PROFILE', 0)
        CONFIG.set_int('MATCH_RATIO', 80)
        CONFIG.set_str('REJECT_WORDS', '')
        CONFIG.set_csv('IMP_PREFLANG', 'en, eng, English')
        CONFIG.set_int('MIN_SEEDERS', 0)
        with DBConnection() as db:
            db.action('DELETE FROM qualityprofiles')
            profiles.ensure_defaults(db)

    def profile(self, name) -> dict:
        return next(p for p in profiles.list_profiles() if p['name'] == name)

    def make_default(self, name):
        profiles.set_default(self.profile(name)['id'])


class QualityTest(ProfilesTestCase):

    def test_a_release_says_its_format(self):
        self.assertEqual(quality.of_release('Lee Child - Without Fail (retail) EPUB', 'ebook'), ['epub'])
        self.assertEqual(quality.of_release('Author.Title.azw3.mobi', 'ebook'), ['azw3', 'mobi'])
        self.assertEqual(quality.of_release('Lee Child - Without Fail', 'ebook'), [], 'Unknown')
        self.assertEqual(quality.of_release('Lee Child - Without Fail [M4B]', 'audiobook'), ['m4b'])
        self.assertEqual(quality.of_release('Kepub edition', 'ebook'), ['epub'], 'Another word for it')

    def test_a_file(self):
        self.assertEqual(quality.of_file('/books/A/B.MOBI', 'ebook'), 'mobi')
        self.assertEqual(quality.of_file('/books/A/B.txt', 'ebook'), 'unknown')
        CONFIG.set_csv('EBOOK_TYPE', 'epub, fb2')
        self.assertEqual(quality.of_file('/books/A/B.fb2', 'ebook'), 'fb2', 'Another type is a quality of its own')
        self.assertIn('fb2', quality.qualities('ebook'))


class DefaultsTest(ProfilesTestCase):

    def test_the_defaults_follow_the_types_settings(self):
        any_ebook = self.profile('Any eBook')
        allowed = [item['quality'] for item in any_ebook['items'] if item['allowed']]
        self.assertEqual(allowed, ['epub', 'mobi', 'unknown', 'pdf'],
                         'As the types setting orders them, an unlabelled release above a PDF')
        self.assertEqual((any_ebook['cutoff'], any_ebook['upgrade_allowed'], any_ebook['is_default']),
                         ('epub', False, True))
        self.assertNotIn('azw3', allowed, 'Not imported, so not wanted')
        prefer = self.profile('Prefer EPUB')
        self.assertEqual((prefer['cutoff'], prefer['upgrade_allowed'], prefer['is_default']), ('epub', True, False))
        audio = self.profile('Any Audiobook')
        self.assertEqual([item['quality'] for item in audio['items'] if item['allowed']], ['mp3', 'm4b', 'unknown'])
        self.assertEqual(self.profile('Prefer M4B')['cutoff'], 'm4b')

    def test_editing(self):
        epub_only = profiles.save({'name': 'EPUB only', 'media_type': 'ebook',
                                   'items': [{'quality': 'epub', 'allowed': True}], 'cutoff': 'epub'})
        self.assertEqual([item['quality'] for item in epub_only['items'] if item['allowed']], ['epub'])
        self.assertEqual(len(epub_only['items']), len(quality.qualities('ebook')), 'Every quality, the rest not wanted')
        for bad in ({'name': '', 'media_type': 'ebook', 'items': [{'quality': 'epub', 'allowed': True}]},
                    {'name': 'X', 'media_type': 'ebook', 'items': [{'quality': 'epub', 'allowed': False}]},
                    {'name': 'X', 'media_type': 'ebook', 'items': [{'quality': 'epub', 'allowed': True}],
                     'cutoff': 'pdf'},
                    {'name': 'Any eBook', 'media_type': 'ebook', 'items': [{'quality': 'epub', 'allowed': True}]},
                    {'name': 'X', 'media_type': 'video', 'items': []}):
            with self.assertRaises(InvalidRequestError, msg=bad):
                profiles.save(bad)
        with self.assertRaises(InvalidRequestError):
            profiles.save({**epub_only, 'media_type': 'audiobook'}, epub_only['id'])
        with self.assertRaises(InvalidRequestError):
            profiles.delete(self.profile('Any eBook')['id'])
        profiles.set_default(epub_only['id'])
        self.assertEqual(profiles.for_media('ebook')['name'], 'EPUB only')
        profiles.delete(self.profile('Any eBook')['id'])
        self.assertNotIn('Any eBook', [p['name'] for p in profiles.list_profiles()])


class DecisionTest(ProfilesTestCase):

    def rejections(self, title, **book):
        found = evaluate_results([_make_tor_result(title, url=f"http://x/{title}")],
                                 {**_make_book('Lee Child', 'Without Fail'), **book}, 'book', 'tor')
        return found[0]['rejections'], found[0]['quality']

    def test_a_quality_the_profile_doesnt_want(self):
        profiles.set_default(profiles.save({'name': 'EPUB only', 'media_type': 'ebook',
                                            'items': [{'quality': 'epub', 'allowed': True}]})['id'])
        self.assertEqual(self.rejections('Lee Child - Without Fail pdf'),
                         (["PDF isn't wanted by the EPUB only quality profile"], 'pdf'))
        self.assertEqual(self.rejections('Lee Child - Without Fail')[0],
                         ["Unknown isn't wanted by the EPUB only quality profile"])
        self.assertEqual(self.rejections('Lee Child - Without Fail epub'), ([], 'epub'))
        self.assertEqual(self.rejections('Lee Child - Without Fail epub mobi pdf'), ([], 'epub'),
                         'A pack, by the best of its formats')

    def test_a_quality_that_isnt_imported(self):
        profiles.set_default(profiles.save({'name': 'Kindle', 'media_type': 'ebook',
                                            'items': [{'quality': 'azw3', 'allowed': True}]})['id'])
        self.assertEqual(self.rejections('Lee Child - Without Fail azw3')[0],
                         ["AZW3 files aren't imported, add azw3 to the eBook types in Settings"])

    def test_the_file_there_is(self):
        self.assertEqual(self.rejections('Lee Child - Without Fail pdf', current_quality='mobi')[0],
                         ['PDF is worse than the MOBI there is'])
        self.assertEqual(self.rejections('Lee Child - Without Fail mobi', current_quality='mobi')[0], [],
                         'The same again when it is wanted again')
        self.assertEqual(self.rejections('Lee Child - Without Fail mobi', current_quality='mobi', upgrade=True)[0],
                         ['Not an upgrade for the MOBI there is'])
        self.assertEqual(self.rejections('Lee Child - Without Fail epub', current_quality='mobi', upgrade=True)[0], [])

    def test_the_best_quality_first(self):
        match = find_best_result([_make_tor_result('Lee Child - Without Fail', url='http://x/plain'),
                                  _make_tor_result('Lee Child - Without Fail epub extra words', url='http://x/epub'),
                                  _make_tor_result('Lee Child - Without Fail pdf', url='http://x/pdf')],
                                 _make_book('Lee Child', 'Without Fail'), 'book', 'tor')
        self.assertEqual(match[2], {'NZBurl': 'http://x/epub'}, 'EPUB first, though it scores lower')
        match = find_best_result([_make_tor_result('Lee Child - Without Fail', url='http://x/plain'),
                                  _make_tor_result('Lee Child - Without Fail pdf', url='http://x/pdf')],
                                 _make_book('Lee Child', 'Without Fail'), 'book', 'tor')
        self.assertEqual(match[2], {'NZBurl': 'http://x/plain'}, 'Unknown above PDF by default')


class CutoffUnmetTest(ProfilesTestCase):

    def setUp(self):
        super().setUp()
        CONFIG.set_bool('EBOOK_TAB', True)
        CONFIG.set_bool('AUDIO_TAB', True)
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.mobi = os.path.join(self.folder, 'Without Fail.mobi')
        with open(self.mobi, 'w') as f:
            f.write('a book')
        with DBConnection() as db:
            db.action("DELETE FROM books")
            db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES ('ca1', 'Lee Child', "
                      "'Active')")
            db.action("INSERT INTO books (BookID, AuthorID, BookName, Status, AudioStatus, BookFile) VALUES "
                      "('c1', 'ca1', 'Without Fail', 'Open', 'Skipped', ?)", (self.mobi,))
            db.action("INSERT INTO books (BookID, AuthorID, BookName, Status, AudioStatus) VALUES "
                      "('c2', 'ca1', 'Persuader', 'Wanted', 'Skipped')")

    def test_listed_when_upgrades_are_allowed(self):
        self.assertEqual(wanted.list_cutoff_unmet().items, [], 'Any eBook allows no upgrades')
        self.make_default('Prefer EPUB')
        items = wanted.list_cutoff_unmet().items
        self.assertEqual([(i['book_id'], i['quality'], i['cutoff'], i['profile']) for i in items],
                         [('c1', 'MOBI', 'EPUB', 'Prefer EPUB')])
        with open(os.path.join(self.folder, 'Without Fail.epub'), 'w') as f:
            f.write('the same book')
        self.assertEqual(wanted.list_cutoff_unmet().items, [], 'It has an EPUB beside it')

    def test_searching_for_upgrades(self):
        self.make_default('Prefer EPUB')
        with mock.patch.object(CONFIG, 'total_active_providers', return_value=1), \
                mock.patch('lazylibrarian.searchbook.search_book') as search:
            found, message = wanted.search_upgrades([])
        search.assert_called_once_with([{'bookid': 'c1'}], 'eBook', upgrade=True)
        self.assertEqual(message, 'Search for an upgrade of Without Fail completed, nothing better found')

    def test_the_search_looks_for_an_upgrade(self):
        self.make_default('Prefer EPUB')
        searched = []

        def fake_znab(book, searchtype):
            searched.append(book)
            return [], 1

        config = searchbook.CONFIG
        with mock.patch.object(config, 'total_active_providers', return_value=1), \
                mock.patch.object(config, 'use_nzb', return_value=1), \
                mock.patch.object(config, 'use_tor', return_value=0), \
                mock.patch.object(config, 'use_direct', return_value=0), \
                mock.patch.object(config, 'use_rss', return_value=0), \
                mock.patch.object(config, 'use_irc', return_value=0), \
                mock.patch.object(searchbook, 'iterate_over_znab_sites', side_effect=fake_znab):
            searchbook.search_book([{'bookid': 'c1'}], 'eBook')
            self.assertEqual(searched, [], 'Not wanted, without upgrade')
            searchbook.search_book([{'bookid': 'c1'}], 'eBook', upgrade=True)
        self.assertTrue(searched)
        self.assertEqual((searched[0]['current_quality'], searched[0]['upgrade']), ('mobi', True))
