#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the settings by name for the Settings pages (services/settings.py config_values,
#   config_choices and save_values)

from unittest import mock

import lazylibrarian
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import InvalidRequestError, NotFoundError, settings
from unittests.unittesthelpers import LLTestCaseWithStartup


class ConfigValuesTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        for key in ('HTTP_PORT', 'LAUNCH_BROWSER', 'SAB_PASS', 'EBOOK_DEST_FOLDER', 'SEARCH_BOOKINTERVAL',
                    'ADMIN_EMAIL', 'AUTH_TYPE', 'PROXY_AUTH_USER', 'HTTPS_KEY'):
            saved = CONFIG.config[key].value
            self.addCleanup(setattr, CONFIG.config[key], 'value', saved)
        patcher = mock.patch.object(settings, 'save_config')
        self.saved = patcher.start()
        self.addCleanup(patcher.stop)

    def values(self, *keys) -> dict:
        return {item['key']: item for item in settings.config_values(list(keys))}

    def test_kinds_and_values(self):
        CONFIG.set_str('SAB_PASS', 'secret')
        found = self.values('http_port', 'LAUNCH_BROWSER', 'SAB_PASS', 'EBOOK_DEST_FOLDER', 'SEARCH_BOOKINTERVAL',
                            'HTTPS_KEY')
        self.assertEqual(found['HTTP_PORT']['kind'], 'int')
        self.assertEqual(found['LAUNCH_BROWSER']['kind'], 'bool')
        self.assertIsInstance(found['LAUNCH_BROWSER']['value'], bool)
        self.assertEqual(found['SAB_PASS']['value'], settings.MASK, 'A password is never sent back')
        self.assertEqual((found['SEARCH_BOOKINTERVAL']['kind'], found['SEARCH_BOOKINTERVAL']['unit']), ('interval', 'min'))
        self.assertEqual(found['HTTPS_KEY']['kind'], 'str')
        self.assertFalse(settings.is_secret('HTTPS_KEY'), "It's the key file's path")
        with self.assertRaises(NotFoundError):
            settings.config_values(['NO_SUCH_SETTING'])

    def test_saving(self):
        CONFIG.set_str('SAB_PASS', 'secret')
        messages = settings.save_values({'http_port': '5301', 'launch_browser': False, 'sab_pass': settings.MASK,
                                         'search_bookinterval': 'often'})
        self.assertEqual(CONFIG.get_int('HTTP_PORT'), 5301)
        self.assertFalse(CONFIG.get_bool('LAUNCH_BROWSER'))
        self.assertEqual(CONFIG['SAB_PASS'], 'secret', 'Saved masked, the password stays')
        self.assertEqual(messages, ["SEARCH_BOOKINTERVAL wasn't changed, often isn't a number"])
        self.saved.assert_called_once()
        settings.save_values({'SAB_PASS': 'new'})
        self.assertEqual(CONFIG['SAB_PASS'], 'new')
        with self.assertRaises(NotFoundError):
            settings.save_values({'NO_SUCH_SETTING': 1})

    def test_checks_as_the_old_page_does(self):
        CONFIG.set_str('AUTH_TYPE', 'FORM')
        CONFIG.set_str('PROXY_AUTH_USER', '')
        messages = settings.save_values({'AUTH_TYPE': 'EXTERNAL', 'ADMIN_EMAIL': 'not an email'})
        self.assertEqual(CONFIG['AUTH_TYPE'], 'FORM', 'External needs the proxy header')
        self.assertEqual(messages, [settings.EXTERNAL_NEEDS_HEADER, settings.INVALID_ADMIN_EMAIL])
        settings.save_values({'AUTH_TYPE': 'EXTERNAL', 'PROXY_AUTH_USER': 'Remote-User'})
        self.assertEqual(CONFIG['AUTH_TYPE'], 'EXTERNAL')

    def test_choices(self):
        choices = settings.config_choices()
        self.assertEqual(choices['ui_languages'][0]['value'], 'auto')
        self.assertTrue(choices['date_formats'] and choices['date_formats'][0]['example'])
        english = next(lang for lang in choices['book_languages'] if lang['label'] == 'English')
        self.assertIn('en', english['value'].split(', '), "A language's value is its codes")
        self.assertIn({'value': 'fuzz', 'label': 'Fuzzy matching'}, choices['special_logs'])

    def test_settings_outside_the_config_file(self):
        with mock.patch.dict(lazylibrarian.GRGENRES, {'genreLimit': 4, 'genreUsers': 10, 'genreExclude': ['a', 'b'],
                                                      'genreExcludeParts': [], 'genreReplace': {'sf': 'science fiction'}},
                             clear=True):
            found = self.values('GENRE_LIMIT', 'GENRE_EXCLUDE', 'GENRE_REPLACE')
            self.assertEqual(found['GENRE_LIMIT']['value'], 4)
            self.assertEqual(found['GENRE_EXCLUDE']['value'], 'a, b')
            self.assertEqual(found['GENRE_REPLACE']['value'], 'sf = science fiction')
            with mock.patch.object(settings, 'update_genres') as update:
                messages = settings.save_values({'GENRE_LIMIT': '6', 'GENRE_REPLACE': 'sf = science fiction\nnonsense'})
            update.assert_called_once_with(6, 10, ['a', 'b'], [], {'sf': 'science fiction'})
            self.assertEqual(len(messages), 1, "A line that isn't old = new isn't added")
        with mock.patch.object(lazylibrarian, 'SEASONS', {'winter': 1, 'xmas': 12, 'christmas': 12}), \
                mock.patch.object(settings, 'update_seasons') as update:
            self.assertEqual(self.values('SEASON_12')['SEASON_12']['value'], 'xmas, christmas')
            settings.save_values({'SEASON_2': 'late winter'})
            update.assert_called_once_with({'winter': 1, 'late winter': 2, 'xmas': 12, 'christmas': 12})

    def test_month_names(self):
        table = [['en_GB.UTF-8'], *[[f'month{n}'] for n in range(1, 13)]]
        with mock.patch.object(lazylibrarian, 'MONTHNAMES', [table, table]), \
                mock.patch.object(settings, 'update_month_names', return_value=False) as update:
            self.assertEqual(self.values('MONTH_3')['MONTH_3']['value'], 'month3')
            messages = settings.save_values({'MONTH_3': 'march, mars'})
        self.assertEqual(update.call_args.args[0][3], ['march', 'mars'])
        self.assertEqual(len(messages), 1, 'Months with a different number of names are refused')

    def test_info_sources_and_debug_logs(self):
        for key in ('BOOK_API', 'DNB_API', 'OL_API', 'LOGSPECIALDEBUG'):
            self.addCleanup(setattr, CONFIG.config[key], 'value', CONFIG.config[key].value)
        CONFIG.set_bool('DNB_API', True)
        CONFIG.set_str('BOOK_API', 'DNB')
        messages = settings.save_values({'DNB_API': False})
        self.assertNotEqual(CONFIG['BOOK_API'], 'DNB', 'The source searched first has to be on')
        self.assertEqual(messages, [settings.INFO_SOURCES_CHANGED.format(CONFIG['BOOK_API'])])
        with mock.patch.object(settings.LOGCONFIG, 'enable_only_these_special_debuglogs') as enable:
            settings.save_values({'LOGSPECIALDEBUG': 'fuzz, dlcomms'})
        enable.assert_called_once_with('fuzz, dlcomms')

    def test_reset(self):
        CONFIG.set_str('SAB_PASS', 'secret')
        settings.reset_values(['SAB_PASS'])
        self.assertEqual(CONFIG['SAB_PASS'], '')


class ConfigListsTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        for patched in ('save_config', 'get_capabilities'):
            patcher = mock.patch.object(settings, patched)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_adding_changing_and_deleting(self):
        with self.assertRaises(InvalidRequestError):
            settings.save_array_item('newznab', {'DISPNAME': 'No address'})
        added = settings.save_array_item('newznab', {'host': 'https://indexer.test/api', 'API': 'abc',
                                                     'ENABLED': True, 'DLPRIORITY': '2'})
        self.addCleanup(settings.delete_array_item, 'newznab', added['index'])
        values = {item['key']: item['value'] for item in added['values']}
        self.assertEqual(values['HOST'], 'https://indexer.test/api')
        self.assertEqual(values['API'], settings.MASK, 'An api key is never sent back')
        self.assertEqual((values['ENABLED'], values['DLPRIORITY']), (True, 2))
        settings.get_capabilities.assert_called_once()
        self.assertIn(added['index'], [item['index'] for item in settings.array_items('NEWZNAB')])
        changed = settings.save_array_item('newznab', {'API': settings.MASK, 'HOST': 'https://x.test/(bad)'},
                                           added['index'])
        self.assertEqual(len(changed['messages']), 1, "An address with brackets isn't taken")
        provider = CONFIG.get_array('NEWZNAB')[added['index']]
        self.assertEqual((provider['HOST'], provider['API']), ('https://indexer.test/api', 'abc'))
        with self.assertRaises(InvalidRequestError):
            settings.save_array_item('newznab', {'NAME': 'newznab_9'}, added['index'])
        with self.assertRaises(NotFoundError):
            settings.array_items('NOPE')

    def test_a_test_that_fails_puts_the_settings_back(self):
        CONFIG.set_str('SAB_HOST', 'old.test')
        self.addCleanup(CONFIG.set_str, 'SAB_HOST', '')
        with mock.patch.object(settings, '_run_test', return_value=(False, 'refused')):
            result = settings.run_test('sabnzbd', {'SAB_HOST': 'new.test'})
        self.assertEqual(result, {'ok': False, 'message': 'refused', 'index': None})
        self.assertEqual(CONFIG['SAB_HOST'], 'old.test')
        with mock.patch.object(settings, '_run_test', return_value=(True, 'ok')):
            result = settings.run_test('sabnzbd', {'SAB_HOST': 'new.test'})
        self.assertTrue(result['ok'])
        self.assertEqual(CONFIG['SAB_HOST'], 'new.test')
        with self.assertRaises(InvalidRequestError):
            settings.run_test('nothing', {})

    def test_testing_a_new_item_adds_it_if_it_works(self):
        before = len(settings.array_items('TORZNAB'))
        with mock.patch.object(settings, '_run_test', return_value=(False, 'no')):
            settings.run_test('', {'HOST': 'https://tracker.test'}, 'torznab')
        self.assertEqual(len(settings.array_items('TORZNAB')), before)
        with mock.patch.object(settings, '_run_test', return_value=(True, 'yes')):
            result = settings.run_test('', {'HOST': 'https://tracker.test'}, 'torznab')
        self.addCleanup(settings.delete_array_item, 'torznab', result['index'])
        self.assertEqual(len(settings.array_items('TORZNAB')), before + 1)
