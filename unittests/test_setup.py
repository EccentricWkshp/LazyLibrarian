#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing the startup sequence

import logging
import os
import tempfile
from unittest import mock

from lazylibrarian import startup
from lazylibrarian.config2 import CONFIG
from lazylibrarian.notifiers import APPRISE_VER
from unittests.unittesthelpers import LLTestCase


class SetupTest(LLTestCase):

    def testConfig(self):
        # Validate that basic global objects and configs have run
        self.assertIsNotNone(CONFIG)
        self.assertIsInstance(CONFIG.get_int('LOGLIMIT'), int)

    def testApprise(self):
        # Validate that APPRISE is defined properly; it's set up as a global in notifiers,
        # copied from the value received during load in apprise_notify. This allows us to
        # avoid circular dependencies.
        self.assertIsNotNone(APPRISE_VER)


class ShutdownTest(LLTestCase):

    def shutdown(self, docker=False, env=None, serving=False, **kwargs):
        """ Run shutdown with everything that would touch the system mocked out,
        return the mock standing in for starting a new LazyLibrarian process.
        The exit status shutdown chose is left in self.status, and the mock that
        checks the new process is up in self.get """
        starter = startup.StartupLazyLibrarian()
        starter.logger = logging.getLogger(__name__)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        logdir = tmp.name
        with mock.patch.object(startup, 'shutdownscheduler'), \
                mock.patch.object(startup, 'docker', return_value=docker), \
                mock.patch.dict(os.environ, env or {}), \
                mock.patch.object(startup.versioncheck, 'update', return_value=False), \
                mock.patch.object(startup.subprocess, 'Popen') as popen, \
                mock.patch('lazylibrarian.webStart.running', return_value=serving), \
                mock.patch('lazylibrarian.webStart.stop'), \
                mock.patch.object(startup.requests, 'get', return_value=mock.Mock(status_code=200)) as get, \
                mock.patch.object(startup.DIRS, 'get_logfile', side_effect=lambda f: os.path.join(logdir, f)), \
                mock.patch.object(startup.DIRS, 'FULL_PATH', 'LazyLibrarian.py', create=True), \
                mock.patch.object(startup.DIRS, 'ARGS', [], create=True):
            if env is None:
                os.environ.pop('LAZYLIBRARIAN_SUPERVISED', None)  # patch.dict puts it back afterwards
            self.status = starter.shutdown(testing=True, **kwargs)
        self.get = get
        return popen

    def test_plain_shutdown_does_not_restart(self):
        # this used to start a new instance whenever doquit was False
        self.shutdown().assert_not_called()
        self.shutdown(doquit=True).assert_not_called()

    def test_restart_starts_new_instance(self):
        popen = self.shutdown(restart=True)
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[1:], ['LazyLibrarian.py', '--nolaunch'])
        self.assertEqual(self.status, 0)

    def test_restart_waits_for_new_instance(self):
        saved = {key: CONFIG[key] for key in ('HTTPS_ENABLED', 'HTTP_HOST', 'HTTP_ROOT')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
        CONFIG.set_str('HTTP_HOST', '0.0.0.0')
        CONFIG.set_str('HTTP_ROOT', '')
        for https, scheme in ((False, 'http'), (True, 'https')):
            CONFIG.set_bool('HTTPS_ENABLED', https)
            self.shutdown(restart=True, serving=True).assert_called_once()
            # a self-signed certificate is fine, it's our own server
            self.get.assert_called_once_with(f"{scheme}://localhost:{CONFIG['HTTP_PORT']}", verify=False,
                                             timeout=10)

    def test_restart_under_service_manager_exits(self):
        # systemd and Docker restart LazyLibrarian when it exits with RESTART_EXIT_STATUS.
        # In Docker a restart used to stop the scheduler and file logging, then carry on running
        for setup in [{'env': {'LAZYLIBRARIAN_SUPERVISED': '1'}}, {'docker': True}]:
            for action in ['restart', 'update']:
                self.shutdown(**setup, **{action: True}).assert_not_called()
                self.assertEqual(self.status, startup.RESTART_EXIT_STATUS, (setup, action))

    def test_shutdown_under_service_manager_stays_stopped(self):
        self.shutdown(env={'LAZYLIBRARIAN_SUPERVISED': 'true'}, doquit=True).assert_not_called()
        self.assertEqual(self.status, 0)
        self.shutdown(docker=True, doquit=True).assert_not_called()
        self.assertEqual(self.status, 0)

    def test_supervised_setting_values(self):
        with mock.patch.object(startup, 'docker', return_value=False):
            for value, expected in [('1', True), ('yes', True), ('ON', True), ('0', False), ('', False)]:
                with mock.patch.dict(os.environ, {'LAZYLIBRARIAN_SUPERVISED': value}):
                    self.assertEqual(startup.restart_by_exit(), expected, value)
