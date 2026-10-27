#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test Health and disk space (services/health.py), like Sonarr's System, Status

import os
from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.filesystem import DIRS
from lazylibrarian.services import health
from unittests.unittesthelpers import LLTestCaseWithStartup

CLIENT_SETTINGS = [setting for setting, _name, _check in health.CLIENTS] + ['NZB_DOWNLOADER_BLACKHOLE',
                                                                            'TOR_DOWNLOADER_BLACKHOLE']


class HealthTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        saved = {key: CONFIG[key] for key in ['EBOOK_DIR', 'AUDIO_DIR', 'DOWNLOAD_DIR', 'EBOOK_TAB', 'AUDIO_TAB',
                                              'COMMITS_BEHIND', *CLIENT_SETTINGS]}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
        for setting in CLIENT_SETTINGS:
            CONFIG.set_bool(setting, False)
        CONFIG.set_int('COMMITS_BEHIND', 0)
        CONFIG.set_bool('EBOOK_TAB', True)
        CONFIG.set_bool('AUDIO_TAB', False)
        CONFIG.set_str('EBOOK_DIR', DIRS.DATADIR)
        CONFIG.set_str('DOWNLOAD_DIR', DIRS.DATADIR)
        health._answers.clear()
        with DBConnection() as db:
            db.action("DELETE FROM wanted")
        for name, value in (('use_any', True), ('use_nzb', False), ('use_tor', False)):
            patch = mock.patch.object(CONFIG, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(health.remotepaths, 'mappings', return_value=[])
        patch.start()
        self.addCleanup(patch.stop)

    def sources(self):
        return [check['source'] for check in health.checks()]

    def test_all_well(self):
        self.assertEqual(health.checks(), [])

    def test_no_indexers(self):
        with mock.patch.object(CONFIG, 'use_any', return_value=False):
            self.assertEqual(self.sources(), ['IndexerCheck'])

    def test_indexers_without_a_download_client(self):
        with mock.patch.object(CONFIG, 'use_nzb', return_value=1):
            found = health.checks()
        self.assertEqual([check['source'] for check in found], ['DownloadClientCheck'])
        self.assertIn('usenet', found[0]['message'])
        CONFIG.set_bool('NZB_DOWNLOADER_BLACKHOLE', True)
        with mock.patch.object(CONFIG, 'use_nzb', return_value=1):
            self.assertEqual(self.sources(), [], 'A blackhole is somewhere to send them')

    def test_a_download_client_that_cant_be_reached(self):
        CONFIG.set_bool('NZB_DOWNLOADER_NZBGET', True)
        check = mock.Mock(return_value=('NZBget connection FAILED\nConnection refused', False))
        with mock.patch.object(health, 'CLIENTS', [('NZB_DOWNLOADER_NZBGET', 'NZBGet', check)]):
            found = health.checks()
            health.checks()
        self.assertEqual((found[0]['source'], found[0]['type']), ('DownloadClientStatusCheck', 'error'))
        self.assertEqual(found[0]['message'],
                         'Unable to communicate with NZBGet. NZBget connection FAILED Connection refused')
        check.assert_called_once()  # kept a while, asking can be slow

    def test_a_missing_library_folder_is_not_made(self):
        missing = os.path.join(DIRS.DATADIR, 'no', 'such', 'library')
        CONFIG.set_str('EBOOK_DIR', missing)
        found = health.checks()
        self.assertEqual([(check['source'], check['type']) for check in found], [('RootFolderCheck', 'error')])
        self.assertIn(missing, found[0]['message'])
        self.assertFalse(os.path.exists(missing), 'Only looked at')

    def test_a_mapping_to_nowhere(self):
        with mock.patch.object(health.remotepaths, 'mappings', return_value=[
                {'Id': 1, 'Host': 'nas', 'RemotePath': '/downloads', 'LocalPath': '/no/such/place'}]):
            found = health.checks()
        self.assertEqual(found[0]['source'], 'RemotePathMappingCheck')
        self.assertIn('/downloads on nas', found[0]['message'])

    def test_downloads_that_cant_be_imported_and_others(self):
        with DBConnection() as db:
            db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,Status,AuxInfo,Source,DLResult) VALUES "
                      "('h1','u1','A','Snatched','eBook','NZBGET','Import blocked: [/x] was not found')")
        CONFIG.set_int('COMMITS_BEHIND', 3)
        with mock.patch.object(health.BLOCKHANDLER, 'blocked',
                               return_value=[{'name': 'NZBgeek', 'resume': 0, 'reason': '503'}]):
            found = health.checks()
        self.assertEqual([check['source'] for check in found], ['IndexerStatusCheck', 'ImportBlockedCheck',
                                                                'UpdateCheck'], 'Warnings before notices')
        self.assertEqual(found[0]['message'], 'Indexer unavailable due to failures: NZBgeek')
        self.assertTrue(found[1]['message'].startswith('1 download could not be imported'))
        self.assertEqual(found[1]['link'], '/activity/queue')

    def test_disk_space(self):
        disks = health.disk_space()
        self.assertEqual(len(disks), 1, 'The data, library and downloads are on one disk here')
        self.assertIn('LazyLibrarian data', disks[0]['label'])
        self.assertIn('eBook library', disks[0]['label'])
        self.assertGreater(disks[0]['total_space'], disks[0]['free_space'])
