#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the settings by name for the Settings pages (services/settings.py config_values,
#   config_choices and save_values)

from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import NotFoundError, settings
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
