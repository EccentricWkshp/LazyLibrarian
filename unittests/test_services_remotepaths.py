#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/remotepaths.py, the remote path mappings, and moving the old per-client settings to them

import io
import os
from unittest import mock

from lazylibrarian import database, download_client
from lazylibrarian.config2 import CONFIG, LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS
from lazylibrarian.dbupgrade import migrate_remote_path_settings
from lazylibrarian.services import InvalidRequestError, NotFoundError, remotepaths, settings
from unittests.unittesthelpers import TESTDIR, LLTestCaseWithDB

HOSTS = ('SAB_HOST', 'QBITTORRENT_HOST', 'DELUGE_HOST', 'SYNOLOGY_HOST', 'NZBGET_HOST', 'TRANSMISSION_HOST',
         'RTORRENT_HOST', 'UTORRENT_HOST', 'SLSK_HOST')


class RemotePathsTestCase(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        saved = {key: CONFIG[key] for key in HOSTS}
        self.addCleanup(lambda: [CONFIG.set_str(key, value) for key, value in saved.items()])
        for key in HOSTS:
            CONFIG.set_str(key, '')
        self.local = os.path.join(TESTDIR, 'remotepaths')
        for name in ('books', 'audio', 'downloads'):
            os.makedirs(os.path.join(self.local, name), exist_ok=True)

    def here(self, *names):
        return os.path.join(self.local, *names)


class MatchingTest(RemotePathsTestCase):

    def test_host_name(self):
        for value, host in (('nas', 'nas'), ('NAS:8080', 'nas'), ('http://192.168.1.5:8080/sab', '192.168.1.5'),
                            ('https://[::1]:9091', '::1'), ('', ''), ('  qbit.lan ', 'qbit.lan')):
            self.assertEqual(remotepaths.host_name(value), host, value)

    def test_each_media_type_can_have_its_own(self):
        remotepaths.add_mapping('nas', '/downloads', self.here('downloads'))
        remotepaths.add_mapping('nas', '/downloads/audiobooks/', self.here('audio'))
        self.assertEqual(remotepaths.remote_to_local('nas', '/downloads/audiobooks/A Book'), self.here('audio', 'A Book'),
                         'The most specific mapping')
        self.assertEqual(remotepaths.remote_to_local('NAS:8080', '/downloads/books/A Book'),
                         self.here('downloads', 'books', 'A Book'))
        self.assertEqual(remotepaths.remote_to_local('nas', '/downloads/audiobooks'), self.here('audio'))
        self.assertEqual(remotepaths.remote_to_local('nas', '/downloadsextra/x'), '/downloadsextra/x',
                         'A folder, not just the start of the text')
        self.assertEqual(remotepaths.remote_to_local('other', '/downloads/x'), '/downloads/x', 'Another host')
        self.assertIsNone(remotepaths.remote_to_local('nas', None))

    def test_a_windows_client(self):
        remotepaths.add_mapping('winbox', 'D:\\Downloads\\Books', self.here('books'))
        self.assertEqual(remotepaths.remote_to_local('winbox', 'd:\\downloads\\books\\Author\\A Book.epub'),
                         self.here('books', 'Author', 'A Book.epub'), 'Windows paths ignore case')

    def test_a_relative_synology_destination(self):
        CONFIG.set_str('SYNOLOGY_HOST', 'diskstation')
        remotepaths.add_mapping('diskstation', 'downloads/books', self.here('books'))
        self.assertEqual(remotepaths.source_to_local('SYNOLOGY_NZB', 'downloads/books/A Book'), self.here('books', 'A Book'))
        self.assertEqual(remotepaths.source_to_local('DIRECT', 'downloads/books/A Book'), 'downloads/books/A Book')

    def test_download_client_uses_the_clients_host(self):
        CONFIG.set_str('QBITTORRENT_HOST', 'http://nas:8080')
        remotepaths.add_mapping('nas', '/data/torrents/books', self.here('books'))
        self.assertEqual(download_client.map_remote_path('QBITTORRENT', '/data/torrents/books/x'), self.here('books', 'x'))
        self.assertEqual(download_client.map_remote_path('SABNZBD', '/data/torrents/books/x'), '/data/torrents/books/x')

    def test_client_hosts(self):
        CONFIG.set_str('SAB_HOST', 'http://nas:8080')
        CONFIG.set_str('QBITTORRENT_HOST', 'NAS')
        CONFIG.set_str('DELUGE_HOST', 'seedbox.example')
        self.assertEqual(remotepaths.client_hosts(), [{'host': 'nas', 'names': 'SABnzbd, qBittorrent'},
                                                      {'host': 'seedbox.example', 'names': 'Deluge'}])


class EditingTest(RemotePathsTestCase):

    def test_add_update_delete(self):
        mapping = remotepaths.add_mapping('Nas:8080', '/downloads/books', self.here('books'))
        self.assertEqual({k: v for k, v in mapping.items() if k != 'Id'},
                         {'Host': 'nas', 'RemotePath': '/downloads/books', 'LocalPath': self.here('books')})
        updated = remotepaths.update_mapping(mapping['Id'], 'nas', '/downloads/books', self.here('audio'))
        self.assertEqual(updated['LocalPath'], self.here('audio'))
        self.assertEqual(remotepaths.mappings(), [updated])
        remotepaths.delete_mapping(mapping['Id'])
        self.assertEqual(remotepaths.mappings(), [])
        with self.assertRaises(NotFoundError):
            remotepaths.delete_mapping(mapping['Id'])

    def test_sonarrs_rules(self):
        remotepaths.add_mapping('nas', '/downloads/books', self.here('books'))
        for host, remote, local, message in (
                ('', '/x', self.here('books'), 'Choose the download client host'),
                ('nas', ' ', self.here('books'), 'Enter the remote path'),
                ('nas', '/x', 'relative/path', 'Enter the local path as a full path'),
                ('nas', '/x', self.here('missing'), 'does not exist'),
                ('NAS', '/downloads/books/', self.here('audio'), 'There is already a mapping')):
            with self.assertRaises(InvalidRequestError) as cm:
                remotepaths.add_mapping(host, remote, local)
            self.assertIn(message, str(cm.exception), (host, remote, local))
        # its own host and remote path are fine when it's updated
        mapping = remotepaths.mappings()[0]
        remotepaths.update_mapping(mapping['Id'], 'nas', '/downloads/books', self.here('audio'))

    def test_settings_page(self):
        first = remotepaths.add_mapping('nas', '/downloads/books', self.here('books'))
        second = remotepaths.add_mapping('nas', '/downloads/audio', self.here('audio'))
        messages = settings.update_remote_path_mappings({
            f"rpm_host_{first['Id']}": 'nas', f"rpm_remote_{first['Id']}": '/downloads/ebooks',
            f"rpm_local_{first['Id']}": self.here('books'), f"rpm_delete_{second['Id']}": '1',
            'rpm_host_new': 'seedbox', 'rpm_remote_new': '/data', 'rpm_local_new': self.here('missing')})
        self.assertEqual(len(messages), 1)
        self.assertIn('does not exist', messages[0])
        self.assertEqual([m['RemotePath'] for m in remotepaths.mappings()], ['/downloads/ebooks'])
        self.assertEqual(settings.update_remote_path_mappings({'rpm_host_new': '', 'rpm_remote_new': '',
                                                               'rpm_local_new': ''}), [], 'An empty new row is fine')


class MigrationTest(RemotePathsTestCase):

    def test_old_settings_are_read_without_warnings(self):
        ini = os.path.join(TESTDIR, 'remotepaths.ini')
        with open(ini, 'w') as f:
            f.write("[QBITTORRENT]\nqbittorrent_host = nas\nqbittorrent_remote = /downloads\n"
                    "qbittorrent_local = /mnt/downloads\n")
        with self.assertNoLogs('lazylibrarian.config2', 'WARNING'):
            cfg = LLConfigHandler(defaults=BASE_DEFAULTS, configfile=ini)
        self.assertEqual(cfg.retired_values, {'qbittorrent_remote': '/downloads', 'qbittorrent_local': '/mnt/downloads'})
        self.assertNotIn('qbittorrent_remote', cfg.save_config_to_string()[1], 'Gone when saved')

    def test_they_become_mappings(self):
        CONFIG.set_str('QBITTORRENT_HOST', 'http://nas:8080')
        CONFIG.set_str('SAB_HOST', 'nas')
        retired = {'qbittorrent_remote': '/downloads', 'qbittorrent_local': self.here('downloads'),
                   'sab_remote': '/downloads', 'sab_local': self.here('downloads'),
                   'deluge_remote': '/x', 'deluge_local': '/y', 'nzbget_remote': '/only/one/half'}
        log = io.StringIO()
        with mock.patch.object(CONFIG, 'retired_values', retired):
            db = database.DBConnection()
            try:
                migrate_remote_path_settings(db, log)
            finally:
                db.close()
        self.assertEqual([(m['Host'], m['RemotePath'], m['LocalPath']) for m in remotepaths.mappings()],
                         [('nas', '/downloads', self.here('downloads'))], 'One for the host the two clients share')
        self.assertIn('Deluge'.lower(), log.getvalue(), 'Deluge has no host, so its paths are not kept')
