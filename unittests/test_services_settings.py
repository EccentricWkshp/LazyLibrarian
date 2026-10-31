#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/settings.py

import json
import os
from unittest import mock

import lazylibrarian
from lazylibrarian.auth import reset_owner_cache
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.services import InvalidRequestError, settings
from unittests.unittesthelpers import LLTestCaseWithDB


class SettingsServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        saved = {key: CONFIG[key] for key in ('BOOK_API', 'OL_API', 'HC_API', 'GR_API', 'GB_API', 'DNB_API', 'BN_API',
                                              'DBK_API', 'RAN_API', 'API_KEY', 'API_RO_KEY', 'GIT_USER')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(k, v) for k, v in saved.items()])
        for name in ('GRGENRES', 'MONTHNAMES', 'SEASONS'):
            self.addCleanup(setattr, lazylibrarian, name, getattr(lazylibrarian, name))
        self.sql("UPDATE users SET UserID='u1', UserName='alice', Password=''")
        reset_owner_cache()
        self.addCleanup(reset_owner_cache)

    def test_owner_login(self):
        self.assertEqual(settings.owner_summary(), {'username': 'alice', 'userid': 'u1'})
        self.assertEqual(settings.update_owner_login('b:ob'), [settings.INVALID_USERNAME])
        self.assertEqual(settings.update_owner_login('bob', 'abcdefgh1', 'abcdefgh2'),
                         [settings.USERNAME_CHANGED, settings.PASSWORDS_DIFFER])
        self.assertEqual(settings.update_owner_login('', 'short', 'short'), [settings.PASSWORD_TOO_WEAK])
        self.assertEqual(settings.update_owner_login('', 'abcdefgh1', 'abcdefgh1'), [settings.PASSWORD_CHANGED])
        self.assertEqual(settings.update_owner_login('bob'), [], 'Already that name')

    def test_the_owners_hardcover_token(self):
        """ The owner's HardCover token among the settings, masked, kept with the owner; sent back masked
        it stays, and tested it's kept only when HardCover takes it """
        patch = mock.patch.object(settings, 'save_config')  # the config file, which this isn't about
        patch.start()
        self.addCleanup(patch.stop)
        self.assertEqual(settings.config_values(['HC_TOKEN'])[0]['value'], '')
        settings.save_values({'HC_TOKEN': 'first-token'})
        self.assertEqual(self.sql("SELECT hc_token FROM users WHERE UserID='u1'"), [{'hc_token': 'first-token'}])
        self.assertEqual(settings.config_values(['HC_TOKEN'])[0], {'key': 'HC_TOKEN', 'kind': 'password',
                                                                   'value': settings.MASK, 'default': '', 'unit': ''})
        settings.save_values({'HC_TOKEN': settings.MASK})
        self.assertEqual(self.sql("SELECT hc_token FROM users WHERE UserID='u1'"), [{'hc_token': 'first-token'}])
        with mock.patch.object(settings.connections, 'test_hardcover_token', return_value=(False, 'No')) as asked:
            self.assertFalse(settings.run_test('HARDCOVER', {'HC_TOKEN': 'bad-token'})['ok'])
        self.assertEqual(asked.call_args.args, ('u1', 'bad-token'))
        self.assertEqual(self.sql("SELECT hc_token FROM users WHERE UserID='u1'"), [{'hc_token': 'first-token'}])
        with mock.patch.object(settings.connections, 'test_hardcover_token', return_value=(True, 'Yes')) as asked:
            self.assertTrue(settings.run_test('HARDCOVER', {'HC_TOKEN': 'good-token'})['ok'])
            settings.run_test('HARDCOVER', {'HC_TOKEN': settings.MASK})
        self.assertEqual(asked.call_args.args, ('u1', ''), 'The one kept, when the page has it masked')
        self.assertEqual(self.sql("SELECT hc_token FROM users WHERE UserID='u1'"), [{'hc_token': 'good-token'}])

    def test_check_auth_settings(self):
        values = {'auth_type': 'NONSENSE', 'auth_required': 'MAYBE'}
        self.assertEqual(settings.check_auth_settings(values), [])
        self.assertEqual(values, {})
        values = {'auth_type': 'EXTERNAL', 'proxy_auth_user': ' '}
        self.assertEqual(settings.check_auth_settings(values), [settings.EXTERNAL_NEEDS_HEADER])
        self.assertNotIn('auth_type', values)

    def test_update_genres(self):
        lazylibrarian.GRGENRES = {'genreLimit': 10, 'genreUsers': 10, 'genreExclude': [], 'genreExcludeParts': [],
                                  'genreReplace': {'sci-fi': 'SF'}}
        with mock.patch.object(settings, 'check_db') as check_db:
            self.assertEqual(settings.update_genres(10, 10, [], [], {'sci-fi': 'SF'}), '')
            check_db.assert_not_called()
            changes = settings.update_genres(5, 10, ['b', 'a'], [], {'sci-fi': 'Science Fiction'})
            check_db.assert_called_once()
        self.assertEqual(changes, 'limit excludes shared-values ')
        self.assertEqual(lazylibrarian.GRGENRES['genreExclude'], ['a', 'b'])
        with open(os.path.join(DIRS.DATADIR, 'genres.json')) as f:
            self.assertEqual(json.load(f)['genreReplace'], {'sci-fi': 'Science Fiction'})

    def test_update_seasons(self):
        lazylibrarian.SEASONS = {'winter': 1}
        self.assertFalse(settings.update_seasons({'winter': 1}))
        self.assertTrue(settings.update_seasons({'winter': 1, 'spring': 4}))
        self.assertEqual(lazylibrarian.SEASONS, {'winter': 1, 'spring': 4})

    def test_clean_setting(self):
        self.assertEqual(settings.clean_setting('USER_AGENT', 'Agent<1>'), 'Agent1')
        self.assertEqual(settings.clean_setting('SAB_PASS', 'p<a>s=s'), 'p<a>s=s', 'Passwords can be anything')
        self.assertEqual(settings.clean_setting('PROXY_HOST', 'http://h:8080/?a=b'), 'http://h:8080/?a=b')
        self.assertEqual(settings.clean_setting('EBOOK_DIR', ''), '')

    def test_update_settings(self):
        settings.update_settings({'git_user': 'Some<one>'}, clear_unsent_switches=False)
        self.assertEqual(CONFIG['GIT_USER'], 'Someone')

    def test_update_magazine_filters(self):
        self.sql("INSERT INTO magazines (Title,Reject,DateType,CoverPage,IssueDate,Language) VALUES "
                 "('Wired','x','',1,'2026-01','en'),('Zine','',NULL,1,'20260003',NULL)")
        count = settings.update_magazine_filters({
            'Wired': {'Reject': 'x', 'Regex': None, 'Genre': None, 'DateType': 'I', 'CoverPage': '2', 'Language': 'en'},
            'Zine': {'Reject': '', 'Regex': None, 'Genre': None, 'DateType': None, 'CoverPage': '1', 'Language': None},
        })
        self.assertEqual(count, 1)
        self.assertEqual(self.sql("SELECT DateType,CoverPage,IssueDate FROM magazines WHERE Title='Wired'")[0],
                         {'DateType': 'I', 'CoverPage': 2, 'IssueDate': ''},
                         'Issue numbers now, so the dated latest issue is forgotten')

    def test_log_level_from_form(self):
        self.assertEqual(settings.log_level_from_form({'log_type': 'Debug'}), 10)
        self.assertEqual(settings.log_level_from_form({'loglevel': '30'}), 30)
        self.assertEqual(settings.log_level_from_form({}), 20)

    def test_set_source(self):
        settings.set_source('HC_API', '1')
        self.assertEqual((CONFIG.get_bool('HC_API'), CONFIG['BOOK_API']), (True, 'HardCover'))
        settings.set_source('GR_API', 'KEY')
        self.assertEqual((CONFIG['GR_API'], CONFIG['BOOK_API']), ('KEY', 'GoodReads'))
        for setting in ('HC_API', 'DNB_API', 'BN_API', 'DBK_API', 'RAN_API'):
            settings.set_source(setting, '')
        settings.set_source('GR_API', '')
        settings.set_source('GB_API', '')
        self.assertEqual((CONFIG.get_bool('OL_API'), CONFIG['BOOK_API']), (True, 'OpenLibrary'), 'Something stays on')
        with self.assertRaises(InvalidRequestError):
            settings.set_source('GR_API', 'K<EY')
        with self.assertRaises(InvalidRequestError):
            settings.set_source('NO_API', '1')

    def test_goodreads_auth(self):
        with mock.patch.object(settings.grsync, 'GrAuth') as grauth:
            grauth.return_value.goodreads_oauth2.return_value = 'Authorisation complete'
            self.addCleanup(CONFIG.set_from_ui, 'GR_SYNC', CONFIG['GR_SYNC'])
            settings.goodreads_auth_finish()
            self.assertTrue(CONFIG.get_bool('GR_SYNC'))
            with self.assertRaises(InvalidRequestError):
                settings.goodreads_auth_start('K<EY')

    def test_new_api_key(self):
        key = settings.new_api_key()
        self.assertEqual((len(key), CONFIG['API_KEY']), (32, key))
        key = settings.new_api_key(read_only=True)
        self.assertEqual(CONFIG['API_RO_KEY'], key)
