#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing the logconfig module.

import logging
import os
import sys
import unittest
from typing import List

import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import credential_params
from lazylibrarian.logconfig import LOGCONFIG, CredentialCleanser, LogConfig
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


class TestLogConfig(LLTestCaseWithConfigandDIRS):
    """ Test the logconfig.py class """

    def setUp(self) -> None:
        # For each test, clear the old config and read a fresh one
        LOGCONFIG.initialize_log_config(max_size=10000, max_number=2, redactui=False, redactfiles=False)
        LOGCONFIG.clear_ui_log()
        root = logging.getLogger('root')
        root.disabled = False  # Sometimes, logging sets it to disabled after loading. Hmm.
        root.setLevel(logging.INFO)
        logging.getLogger(None).setLevel(logging.WARNING)
        super().setUp()

    def test_read_log_config(self):
        """ Very basic test: Just load the config and validate it loaded """

        def exercise_logger(logname: str, loglevels: List[int], num: int):
            """ Look up a logger, emit some messages, see if they appear as expected """
            logger = logging.getLogger(logname)
            self.assertIsNotNone(logger)
            with self.assertLogs(logger, logger.level) as logrecs:
                for level in loglevels:
                    logger.log(level, f'Test level {level} for logger {logname}')
            self.assertEqual(num, len(logrecs.output), f'Unexpected result for logger {logname}')

        exercise_logger('root', [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR], 3)
        exercise_logger('unittest', [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR], 3)
        exercise_logger('special', [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR], 4)
        # All of the special loggers default to INFO
        exercise_logger('special.configread', [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR], 4)
        exercise_logger('special.configwrite', [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR], 4)
        exercise_logger('special.dbcomms.dbtiming', [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR], 3)

    def test_setting_log_level(self):
        def test_enabled(logname: str, yes: List[int], no: List[int]) -> logging.Logger:
            """ Look up a logger, emit some messages, see if they appear as expected """
            testlogger = logging.getLogger(logname)
            try:
                self.assertIsNotNone(testlogger)
                for level in yes:
                    self.assertTrue(testlogger.isEnabledFor(level))
                for level in no:
                    self.assertFalse(testlogger.isEnabledFor(level))
            finally:
                return testlogger

        # Test that only DEBUG messages are filtered by default
        logger = test_enabled('root', [logging.INFO, logging.WARNING, logging.ERROR], [logging.DEBUG])
        # Test that setting ERRORs+ filter works
        logger.setLevel(logging.ERROR)
        test_enabled('root', [logging.ERROR], [logging.DEBUG, logging.INFO, logging.WARNING])
        logger.setLevel(logging.INFO)

        # Test that the special.configread logger logs everything but DEBUG by default
        logger = test_enabled('special.configread', [logging.INFO, logging.WARNING, logging.ERROR], [logging.DEBUG])
        # Test that the special.configread logger log level can be changed, and that it didn't affect the root logger
        logger.setLevel(logging.ERROR)
        test_enabled('special.configread', [logging.ERROR], [logging.DEBUG, logging.INFO, logging.WARNING])
        logger.setLevel(logging.INFO)  # Restore to default
        test_enabled('root', [logging.INFO, logging.WARNING, logging.ERROR], [logging.DEBUG])

    def test_disabling_loggers(self):
        """ Test disabling and enabling loggers """
        logger = LOGCONFIG.enable_logger('special.configread', True)
        try:
            self.assertTrue(logger.isEnabledFor(logging.INFO))
            logger = LOGCONFIG.enable_logger('special.configread', False)
            self.assertFalse(logger.isEnabledFor(logging.INFO))
        finally:
            LOGCONFIG.enable_logger('special.configread', True)

        # Get some random logger, which defaults to the root logger
        logger = LOGCONFIG.enable_logger('some_module', True)
        self.assertTrue(logger.isEnabledFor(logging.ERROR))

        # Try disabling the root logger
        logger = LOGCONFIG.enable_logger('root', False)
        self.assertFalse(logger.isEnabledFor(logging.ERROR))

    def test_get_loglevel(self):
        self.assertEqual(logging.INFO, LOGCONFIG.get_loglevel('root'), 'Root not INFO')
        self.assertEqual(logging.DEBUG, LOGCONFIG.get_loglevel('special'), 'Special not DEBUG')
        self.assertEqual(logging.DEBUG, LOGCONFIG.get_loglevel('special.fuzz'), 'Special.fuzz not DEBUG')
        self.assertEqual(logging.INFO, LOGCONFIG.get_loglevel(None), 'None not WARNING')
        self.assertEqual(logging.INFO, LOGCONFIG.get_loglevel(''), 'blank not WARNING')

    def test_get_loglevel_name(self):
        self.assertEqual('INFO', LOGCONFIG.get_loglevel_name('root'), 'Root not INFO')
        self.assertEqual('DEBUG', LOGCONFIG.get_loglevel_name('special'), 'special not DEBUG')
        self.assertEqual('DEBUG', LOGCONFIG.get_loglevel_name('special.fuzz'), 'special.fuzz not DEBUG')
        # Undefined logger gets root level:
        self.assertEqual('INFO', LOGCONFIG.get_loglevel_name('somelogger-notdefinedyet'), 'Undefined is not INFO')

    def test_set_loglevel(self):
        self.assertEqual(logging.WARNING, LOGCONFIG.set_loglevel(logging.WARNING, 'root'), 'root not WARNING')
        self.assertEqual(logging.DEBUG, LOGCONFIG.set_loglevel(logging.DEBUG, 'special.fuzz'), 'special.FUZZ not DEBUG')
        self.assertEqual(logging.WARNING, LOGCONFIG.get_loglevel('root'), 'root not WARNING again')
        self.assertEqual(logging.DEBUG, LOGCONFIG.get_loglevel('special.fuzz'), 'special.fuzz not DEBUG')

    def test_is_logger_enabled_for(self):
        self.assertTrue(LOGCONFIG.is_logger_enabled_for('root', logging.INFO))
        self.assertFalse(LOGCONFIG.is_logger_enabled_for('root', logging.DEBUG))

    def test_get_special_logger_list(self):
        loggers = LOGCONFIG.get_special_logger_list()
        self.assertGreater(len(loggers), 10, 'Expect more than 10 special loggers')

    def test_is_special_logger_enabled(self):
        # Test with special.fuzz
        LOGCONFIG.enable_special_logger('fuzz', True)
        self.assertTrue(LOGCONFIG.is_special_logger_enabled('fuzz'))
        LOGCONFIG.enable_special_logger('fuzz', False)
        self.assertFalse(LOGCONFIG.is_special_logger_enabled('fuzz'))

    def test_all_special_loggers(self):
        # The parent special logger is on and at debug level
        self.assertEqual(logging.DEBUG, LOGCONFIG.get_loglevel('special'))
        self.assertTrue(logging.getLogger('special').isEnabledFor(logging.DEBUG))

        loggers = LOGCONFIG.get_special_logger_list()
        for logger in loggers:
            shortname = LOGCONFIG.get_short_special_logger_name(logger.name)
            if shortname != "cherrypy":
                self.assertTrue(logger.isEnabledFor(logging.DEBUG), f'{shortname} is not DEBUG')
            else:
                self.assertFalse(logger.isEnabledFor(logging.DEBUG), f'{shortname} is DEBUG')

            with self.assertLogs(logger.name) as lm:
                self.assertFalse(logger.isEnabledFor(logging.DEBUG), logger.name)
                self.assertTrue(logger.isEnabledFor(logging.INFO), logger.name)
                logger.debug('Debug')
                logger.info('Info')
            self.assertEqual(1, len(lm.output), 'Expected 1 Info message')

            # This should now result in messages in the log:
            LOGCONFIG.enable_special_logger(shortname, True)
            self.assertTrue(logger.isEnabledFor(logging.DEBUG))
            with self.assertLogs(logger.name, logging.DEBUG) as lm:
                self.assertTrue(logger.isEnabledFor(logging.DEBUG))
                self.assertTrue(logger.isEnabledFor(logging.INFO))
                logger.debug('Debug')
                logger.info('Info')
            self.assertEqual(2, len(lm.output), 'Expected both debug and info message')

    def test_ensure_memoryhandler_for_ui(self):
        oldhandler = LOGCONFIG.get_ui_loghandler()
        self.assertIsNotNone(oldhandler)
        LOGCONFIG.ensure_memoryhandler_for_ui(capacity_lines=10, redact=False)
        newhandler = LOGCONFIG.get_ui_loghandler()
        self.assertIsNotNone(newhandler)
        self.assertEqual(newhandler, oldhandler)

    def test_get_ui_logrows_basic(self):
        logger = logging.getLogger('root')
        LOGCONFIG.ensure_memoryhandler_for_ui(capacity_lines=-1, redact=False)
        self.assertEqual(logging.INFO, logger.getEffectiveLevel())
        logger.debug('Testing debug')
        logger.info('Testing info')
        logger.info('Testing warning')

        rows, total = LOGCONFIG.get_ui_logrows()
        self.assertEqual(total, len(rows), 'Expect to return all rows')
        self.assertEqual(2, len(rows), 'Expected 2 rows')

        rows, _ = LOGCONFIG.get_ui_logrows('warn')
        self.assertEqual(1, len(rows), 'Expected 1 filtered row')

    def test_get_ui_logrows_overrun(self):
        logger = logging.getLogger('root')
        test_capacity = 5
        LOGCONFIG.ensure_memoryhandler_for_ui(capacity_lines=test_capacity, redact=False)
        self.assertEqual(logging.INFO, logger.getEffectiveLevel())
        for i in range(10):
            logger.info(f"Log {i}")
        rows, _ = LOGCONFIG.get_ui_logrows()
        lastrow = rows[-1]
        self.assertEqual(lastrow[6], 'Log 9', 'The message is not as expected')
        self.assertEqual(len(rows), test_capacity)

    def test_get_ui_logrows_redacted(self):
        logger = logging.getLogger('root')
        LOGCONFIG.ensure_memoryhandler_for_ui(capacity_lines=100, redact=True)
        LOGCONFIG.redact_list_updated(['9', 'INFO'])
        for i in range(10):
            logger.info("Log %d" % i)
        redactedrows, total = LOGCONFIG.get_ui_logrows('')
        self.assertEqual(10, total, 'Expected 10 rows total')
        self.assertEqual(len(redactedrows), total, 'Expected all rows to be returned')
        lastrow = redactedrows[-1]
        self.assertEqual('Log [redacted]', lastrow[6], 'The message is not redacted properly')

    def test_special_loggers_to_ui(self):
        logger = LOGCONFIG.enable_special_logger('fuzz', True)
        self.assertEqual(logging.DEBUG, logger.getEffectiveLevel())
        logger.debug('Testing debug')
        logger.debug('Testing info')

        rows, total = LOGCONFIG.get_ui_logrows()
        self.assertEqual(total, len(rows), 'Expect to return all rows')
        self.assertEqual(2, len(rows), 'Expected 2 rows')

    def test_get_full_filename(self):
        tests = [
            ['lazylibrarian.log', False, 'lazylibrarian.log'],
            ['lazylibrarian.log', True, 'lazylibrarian-redacted.log']
        ]
        for test in tests:
            fullname = LogConfig.get_full_filename(filename=test[0], redact=test[1])
            self.assertTrue(fullname.endswith(test[2]))

    @mock.patch('glob.glob')
    @mock.patch.object(os, 'remove')
    def test_delete_log_files(self, mock_remove, mock_glob):
        # Test no log files case
        mock_glob.return_value = []
        res = LogConfig.delete_log_files('/logs')
        self.assertEqual(0, mock_remove.call_count)
        self.assertEqual('No log files to delete', res)

        # Mock up a result that means 2 files should be deleted
        mock_glob.return_value = ['logs/lazy.log', 'logs/some.log.1']
        res = LogConfig.delete_log_files('/logs')
        self.assertEqual(2, mock_remove.call_count)
        self.assertEqual(f"2 log file(s) deleted from /logs", res)

    def test_enable_only_these_special_debuglogs(self):
        # Enable all of them!
        fulllist = ''
        loggers = LOGCONFIG.get_special_logger_list()
        fulllist = ','.join(LOGCONFIG.get_short_special_logger_name(logger.name) for logger in loggers)
        LogConfig.enable_only_these_special_debuglogs(fulllist)
        for logger in loggers:
            shortname = LOGCONFIG.get_short_special_logger_name(logger.name)
            self.assertTrue(LOGCONFIG.is_special_logger_enabled(shortname),
                            f'All special loggers should be enabled; {shortname} is not')
            self.assertTrue(logger.isEnabledFor(logging.DEBUG),
                             f'Result is not consistent for {shortname}')

        # Disable all special loggers
        LogConfig.enable_only_these_special_debuglogs('')
        loggers = LOGCONFIG.get_special_logger_list()
        for logger in loggers:
            shortname = LOGCONFIG.get_short_special_logger_name(logger.name)
            self.assertFalse(LOGCONFIG.is_special_logger_enabled(shortname),
                             f'Special logger {shortname} is not disabled')
            self.assertFalse(logger.isEnabledFor(logging.DEBUG),
                             f'Special logger {shortname} is disabled, but enabled for DEBUG')

    def test_get_redacted_logfilenames(self):
        LOGCONFIG.set_file_redact_filter(redact=False)
        redactednames = LOGCONFIG.get_redacted_logfilenames()
        self.assertEqual([], redactednames, 'Expected no redacted names when redact is off')

        LOGCONFIG.set_file_redact_filter(redact=True)
        redactednames = LOGCONFIG.get_redacted_logfilenames()
        self.assertTrue(len(redactednames) > 0, 'Expected at least one redacted name when redact is on')

    def test_change_logfileredact(self):
        """ Same as test_get_redacted_logfilenames, except we're enabling and disabling
        redact as if it was done from config """
        LOGCONFIG.change_logfileredact('0')
        redactednames = LOGCONFIG.get_redacted_logfilenames()
        self.assertEqual([], redactednames, 'Expected no redacted names when redact is off')

        LOGCONFIG.change_logfileredact('1')
        redactednames = LOGCONFIG.get_redacted_logfilenames()
        self.assertTrue(len(redactednames) > 0, 'Expected at least one redacted name when redact is on')


class TestCredentialCleanser(unittest.TestCase):
    """ Credentials go from every log line, whatever the redact settings """

    def setUp(self):
        self.cleanser = CredentialCleanser()

    def test_url_parameters(self):
        clean = self.cleanser.cleanse('GET /api?apikey=0123456789abcdef&cmd=getIndex HTTP/1.1')
        self.assertEqual(clean, 'GET /api?apikey=[redacted]&cmd=getIndex HTTP/1.1')
        clean = self.cleanser.cleanse('Fetching https://indexer.example/api?t=search&passkey=abc123 and back')
        self.assertEqual(clean, 'Fetching https://indexer.example/api?t=search&passkey=[redacted] and back')
        self.assertEqual(self.cleanser.cleanse('sort_key=title'), 'sort_key=title')

    def test_extra_parameters(self):
        self.assertEqual(self.cleanser.cleanse('/feed?uid=1&hash=99'), '/feed?uid=1&hash=99')
        self.cleanser.update([], credential_params(['hash']))
        self.assertEqual(self.cleanser.cleanse('/feed?uid=1&hash=99'), '/feed?uid=1&hash=[redacted]')
        self.assertEqual(self.cleanser.cleanse('/api?apikey=1'), '/api?apikey=[redacted]', 'Defaults stay')

    def test_header_dump(self):
        # what CherryPy logs on an error response
        dump = ('\nRequest Headers:\n  Host: books.lan\n  Authorization: Basic b3duZXI6c2VjcmV0\n'
                '  Cookie: ll_session=abcdef; theme=dark\n  X-Api-Key: 0123456789abcdef\n  Accept: */*')
        clean = self.cleanser.cleanse(dump)
        self.assertEqual(clean, '\nRequest Headers:\n  Host: books.lan\n  Authorization: [redacted]\n'
                                '  Cookie: [redacted]\n  X-Api-Key: [redacted]\n  Accept: */*')

    def test_dict_items(self):
        clean = self.cleanser.cleanse("Received API command from 1.2.3.4: addProvider "
                                      "{'name': 'Prowlarr', 'prov_apikey': 'abc123'}")
        self.assertEqual(clean, "Received API command from 1.2.3.4: addProvider "
                                "{'name': 'Prowlarr', 'prov_apikey': '[redacted]'}")
        self.assertEqual(self.cleanser.cleanse('{"Apikey": "abc", "Author": "Pratchett", "password": ""}'),
                         '{"Apikey": "[redacted]", "Author": "Pratchett", "password": "[redacted]"}')

    def test_configured_secrets(self):
        self.cleanser.update(['hunter2hunter2', 'abc', 'hunter2'], credential_params([]))
        self.assertEqual(self.cleanser.cleanse('Login with hunter2hunter2 failed, abc'),
                         'Login with [redacted] failed, abc', 'Whole secret goes, short ones are left alone')

    def test_record_with_args_and_exception(self):
        self.cleanser.update(['s3cretpassword'], credential_params([]))
        record = logging.LogRecord('test', logging.INFO, __file__, 1, 'Url %s with %s',
                                   ('/x?token=abc', 's3cretpassword'), None)
        self.cleanser.cleanse_record(record)
        self.assertEqual(record.getMessage(), 'Url /x?token=[redacted] with [redacted]')
        try:
            raise ValueError('Max retries exceeded with url: /api?apikey=abc123')
        except ValueError:
            record = logging.LogRecord('test', logging.ERROR, __file__, 1, 'Failed 100%', (), sys.exc_info())
        self.cleanser.cleanse_record(record)
        self.assertEqual(record.getMessage(), 'Failed 100%')
        formatted = logging.Formatter().format(record)
        self.assertIn('apikey=[redacted]', formatted)
        self.assertNotIn('abc123', formatted)


class TestCredentialsInLogs(LLTestCaseWithConfigandDIRS):
    """ The installed cleanser, fed by the config, on real loggers """

    def setUp(self):
        super().setUp()
        LOGCONFIG.initialize_log_config(max_size=10000, max_number=2, redactui=False, redactfiles=False)
        LOGCONFIG.clear_ui_log()
        logging.getLogger('root').setLevel(logging.INFO)
        old_key = CONFIG['API_KEY']
        self.addCleanup(self.restore, old_key)

    @staticmethod
    def restore(old_key):
        CONFIG.set_str('API_KEY', old_key)
        CONFIG._update_redactlist()

    @staticmethod
    def last_message() -> str:
        rows, _ = LOGCONFIG.get_ui_logrows()
        return rows[-1][6]

    def test_api_key_never_logged(self):
        CONFIG.set_str('API_KEY', '0123456789abcdef0123456789abcdef')
        CONFIG._update_redactlist()
        logging.getLogger('root').info('Key is 0123456789abcdef0123456789abcdef')
        self.assertEqual(self.last_message(), 'Key is [redacted]')

    def test_cherrypy_logs(self):
        # CherryPy logs through its own loggers, which the cleanser covers too
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        access = logging.getLogger('cherrypy.access.test')
        access.addHandler(handler)
        self.addCleanup(access.removeHandler, handler)
        access.propagate = False
        access.setLevel(logging.INFO)
        access.info('127.0.0.1 - - "GET /api?cmd=getIndex&apikey=0123456789abcdef HTTP/1.1" 200 12 "" "curl"')
        self.assertEqual(records[-1].getMessage(),
                         '127.0.0.1 - - "GET /api?cmd=getIndex&apikey=[redacted] HTTP/1.1" 200 12 "" "curl"')
