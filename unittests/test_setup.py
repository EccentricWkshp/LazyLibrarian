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

    def shutdown(self, **kwargs):
        """ Run shutdown with everything that would touch the system mocked out,
        return the mock standing in for starting a new LazyLibrarian process """
        starter = startup.StartupLazyLibrarian()
        starter.logger = logging.getLogger(__name__)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        logdir = tmp.name
        with mock.patch.object(startup, 'shutdownscheduler'), \
                mock.patch.object(startup, 'docker', return_value=False), \
                mock.patch.object(startup.subprocess, 'Popen') as popen, \
                mock.patch.object(startup.cherrypy.server, 'httpserver', None), \
                mock.patch.object(startup.DIRS, 'get_logfile', side_effect=lambda f: os.path.join(logdir, f)), \
                mock.patch.object(startup.DIRS, 'FULL_PATH', 'LazyLibrarian.py', create=True), \
                mock.patch.object(startup.DIRS, 'ARGS', [], create=True):
            starter.shutdown(testing=True, **kwargs)
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
