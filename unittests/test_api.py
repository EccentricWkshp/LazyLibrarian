#  This file is part of Lazylibrarian.
#
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

# Purpose:
#   Test normalize_library_param() and the api key checks in api.py

import types
import unittest
from unittest import mock

import cherrypy

from lazylibrarian.api import Api, key_matches, normalize_library_param
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS, LLTestCaseWithStartup

FULL_KEY = '0123456789abcdef0123456789abcdef'
RO_KEY = 'fedcba9876543210fedcba9876543210'


class ApiKeyTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        super().setUp()
        old_enabled, old_full, old_ro = CONFIG.get_bool('API_ENABLED'), CONFIG['API_KEY'], CONFIG['API_RO_KEY']
        self.addCleanup(self.set_keys, old_full, old_ro, old_enabled)
        self.set_keys(FULL_KEY, RO_KEY)

    @staticmethod
    def set_keys(full, ro, enabled=True):
        CONFIG.set_bool('API_ENABLED', enabled)
        CONFIG.set_str('API_KEY', full)
        CONFIG.set_str('API_RO_KEY', ro)

    @staticmethod
    def check(headers=None, **kwargs) -> Api:
        api = Api()
        with mock.patch.object(cherrypy.serving, 'request', types.SimpleNamespace(headers=headers or {})):
            api.check_params(**kwargs)
        return api

    def assert_error(self, api: Api, code: int):
        self.assertIsInstance(api.data, dict, api.data)
        self.assertEqual(api.data['Error']['Code'], code, api.data)

    def test_key_in_parameter(self):
        api = self.check(apikey=FULL_KEY, cmd='getIndex', sort='name')
        self.assertEqual(api.data, 'OK')
        self.assertEqual(api.kwargs, {'sort': 'name'}, 'The key must not be passed on to the command')

    def test_key_in_header(self):
        api = self.check(headers={'X-Api-Key': FULL_KEY}, cmd='shutdown')
        self.assertEqual(api.data, 'OK')
        self.assertEqual(api.cmd, 'shutdown')

    def test_header_wins_over_parameter(self):
        self.assertEqual(self.check(headers={'X-Api-Key': FULL_KEY}, apikey='wrong', cmd='shutdown').data, 'OK')
        api = self.check(headers={'X-Api-Key': 'wrong'}, apikey=FULL_KEY, cmd='shutdown')
        self.assert_error(api, 401)

    def test_missing_and_wrong_keys(self):
        self.assert_error(self.check(cmd='getIndex'), 400)
        self.assert_error(self.check(apikey='', cmd='getIndex'), 400)
        self.assert_error(self.check(apikey=FULL_KEY[:-1] + '0', cmd='getIndex'), 401)
        self.assert_error(self.check(apikey='ключ', cmd='getIndex'), 401)
        self.assert_error(self.check(apikey=[FULL_KEY, FULL_KEY], cmd='getIndex'), 401)

    def test_read_only_key(self):
        self.assertEqual(self.check(headers={'X-Api-Key': RO_KEY}, cmd='getIndex').data, 'OK')
        self.assert_error(self.check(headers={'X-Api-Key': RO_KEY}, cmd='shutdown'), 405)

    def test_empty_key_is_not_full_access(self):
        # Only a read-only key is set. An empty key used to match the unset full access key
        self.set_keys('', RO_KEY)
        self.assert_error(self.check(apikey='', cmd='shutdown'), 400)
        self.assert_error(self.check(headers={'X-Api-Key': RO_KEY}, cmd='shutdown'), 405)

    def test_key_matches(self):
        self.assertTrue(key_matches(FULL_KEY, FULL_KEY))
        self.assertFalse(key_matches('', ''))
        self.assertFalse(key_matches(FULL_KEY, ''))
        self.assertFalse(key_matches(None, FULL_KEY))
        self.assertFalse(key_matches('é', FULL_KEY))


class NormalizeLibraryParamTest(unittest.TestCase):
    """_importalternate/_importbook used to pass their raw 'library' kwarg straight
    through with no validation, so any caller using "AudioBook" (a natural value --
    it's the display string used elsewhere in the codebase) instead of the
    undocumented internal literal "Audio" would silently fail deeper in the import
    pipeline. normalize_library_param() closes that gap at the API boundary."""

    def test_canonical_values_pass_through_unchanged(self):
        self.assertEqual(normalize_library_param("eBook"), "eBook")
        self.assertEqual(normalize_library_param("Audio"), "Audio")

    def test_audiobook_variants_normalized_to_audio(self):
        for variant in ("AudioBook", "audiobook", "Audio Book", "audio_book", "audio-book"):
            with self.subTest(variant=variant):
                self.assertEqual(normalize_library_param(variant), "Audio")

    def test_ebook_variants_normalized_to_ebook(self):
        for variant in ("ebook", "e Book", "e-book", "e_book"):
            with self.subTest(variant=variant):
                self.assertEqual(normalize_library_param(variant), "eBook")

    def test_unrecognized_value_passed_through_unchanged(self):
        # Not this function's job to error -- callers (process_book_from_dir,
        # process_alternate) already have their own handling for a value they
        # don't recognize; we just shouldn't mangle it into something else.
        self.assertEqual(normalize_library_param("NotARealBookType"), "NotARealBookType")

    def test_magazine_and_comic_passed_through_unchanged(self):
        # Recognized by BookType, but not eBook/Audio -- normalize_library_param
        # only ever maps to "Audio"/"eBook", so anything else (including other
        # valid BookType values) is left as-is rather than incorrectly coerced.
        self.assertEqual(normalize_library_param("magazine"), "magazine")
        self.assertEqual(normalize_library_param("comic"), "comic")


if __name__ == "__main__":
    unittest.main()

class AddMagazineTest(LLTestCaseWithStartup):

    def test_a_magazine_there_already_keeps_its_filters(self):
        with DBConnection() as db:
            db.action("DELETE FROM magazines")
            db.action("INSERT INTO magazines (Title, Regex, Reject, Status, MagazineAdded) VALUES "
                      "('Wired', 'wired mag', 'uk', 'Paused', '2020-01-01')")
        api = Api()
        api._addmagazine(name='wired')
        api._addmagazine(name='New Scientist')
        with DBConnection() as db:
            wired = db.match("SELECT * FROM magazines WHERE Title='Wired'")
            added = db.match("SELECT * FROM magazines WHERE Title='New Scientist'")
        self.assertEqual((wired['Regex'], wired['Reject'], wired['Status'], wired['MagazineAdded']),
                         ('wired mag', 'uk', 'Paused', '2020-01-01'))
        self.assertEqual(added['Status'], 'Active')
