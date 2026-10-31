#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/connections.py

import contextlib
from unittest import mock

from lazylibrarian import notifiers
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import InvalidRequestError, ServiceError, connections
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS

KEYS = ('PUSHOVER_PRIORITY', 'PUSHOVER_APITOKEN', 'QBITTORRENT_IGNORE_SSL', 'QBITTORRENT_HOST', 'EMAIL_TLS', 'SAB_HOST',
        'SAB_PORT', 'DELUGE_HOST', 'DELUGE_USER', 'DELUGE_LABEL', 'DELUGE_LABEL_AUDIO', 'DELUGE_LABEL_MAG',
        'DELUGE_LABEL_COMIC', 'DELUGE_CERT', 'FFMPEG', 'EXT_PREPROCESS',
        'PROWL_PRIORITY', 'SLACK_TOKEN', 'GB_API')


class ConnectionServiceTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        super().setUp()
        saved = {key: CONFIG[key] for key in KEYS}

        def restore():
            for key, value in saved.items():
                with contextlib.suppress(Exception):
                    CONFIG.set_from_ui(key, value)
        self.addCleanup(restore)
        patch = mock.patch.object(CONFIG, 'save_config_and_backup_old')
        self.save = patch.start()
        self.addCleanup(patch.stop)

    def test_apply_settings(self):
        bad = connections.apply_settings('pushover', {'apitoken': 'a=b', 'priority': '5'})
        self.assertEqual(bad, ['apitoken'])
        self.assertEqual(CONFIG.get_int('PUSHOVER_PRIORITY'), 0, 'Out of range')
        connections.apply_settings('pushover', {'priority': '-2'})
        self.assertEqual(CONFIG.get_int('PUSHOVER_PRIORITY'), -2)
        connections.apply_settings('qbittorrent', {'ignore_ssl': '1', 'host': 'qbit'})
        self.assertEqual((CONFIG.get_bool('QBITTORRENT_IGNORE_SSL'), CONFIG['QBITTORRENT_HOST']), (True, 'qbit'))
        connections.apply_settings('email', {'tls': 'False'})
        self.assertFalse(CONFIG.get_bool('EMAIL_TLS'))
        self.assertEqual(connections.apply_settings('prowl', {'priority': '2<'}), ['priority'])
        self.assertEqual(connections.apply_settings('pushbullet', {'token': 'a=b'}), [], 'Pushbullet allows =')

    def test_notifier(self):
        with mock.patch.object(notifiers.pushover_notifier, 'test_notify', return_value='sent'):
            self.assertEqual(connections.test_notifier('pushover', {'apitoken': 'a'}),
                             {'bad': [], 'ok': True, 'result': 'sent'})
        self.save.assert_called_once_with(section='Pushover')
        with mock.patch.object(notifiers.slack_notifier, 'test_notify', return_value='invalid_token'):
            self.assertFalse(connections.test_notifier('slack', {'token': 't'})['ok'], 'Slack says ok when it works')
        self.assertEqual(connections.test_notifier('slack', {'token': 't<'})['bad'], ['token'])
        self.assertEqual(self.save.call_count, 1)

    def test_client(self):
        with mock.patch('lazylibrarian.sabnzbd.check_link', return_value=('SABnzbd OK', True)):
            self.assertEqual(connections.test_client('sabnzbd', {'host': 'sab', 'port': '8080'}),
                             {'bad': [], 'ok': True, 'message': 'SABnzbd OK'})
        self.assertEqual((CONFIG['SAB_HOST'], CONFIG.get_int('SAB_PORT')), ('sab', 8080))
        self.save.assert_called_once_with(section='sab_nzbd')
        self.assertEqual(connections.test_client('sabnzbd', {'host': 's<ab'})['bad'], ['host'])

    def test_deluge_webui(self):
        with mock.patch('lazylibrarian.deluge.check_link', return_value=('Deluge webui OK', True)):
            found = connections.test_deluge({'user': '', 'host': 'http://deluge'})
        self.assertEqual((found['daemon'], found['webui']), (False, 'Deluge webui OK'))
        with mock.patch('lazylibrarian.deluge.check_link', return_value=('No connection', False)):
            self.assertEqual(connections.test_deluge({'user': ''})['webui'], 'No connection')

    def test_deluge_daemon_adds_the_label(self):
        client = mock.MagicMock()
        client.return_value.call.side_effect = lambda name, *args: [b'other'] if name == 'label.get_labels' else None
        with mock.patch.object(connections, 'DelugeRPCClient', client):
            found = connections.test_deluge({'user': 'me', 'host': 'http://deluge', 'label': 'Books'})
        self.assertEqual((found['daemon'], found['checked']),
                         (True, [{'label': 'books', 'added': True, 'error': ''}]))
        self.assertEqual((CONFIG['DELUGE_HOST'], CONFIG['DELUGE_LABEL']), ('deluge', 'books'))
        client.return_value.call.assert_any_call('label.add', 'books')

    def test_deluge_daemon_checks_each_media_types_label(self):
        client = mock.MagicMock()
        client.return_value.call.side_effect = lambda name, *args: [b'books'] if name == 'label.get_labels' else None
        with mock.patch.object(connections, 'DelugeRPCClient', client):
            found = connections.test_deluge({'user': 'me', 'host': 'deluge', 'label': 'Books', 'label_audio': 'Audio',
                                             'label_mag': 'books', 'label_comic': ''})
        self.assertEqual(found['checked'], [{'label': 'books', 'added': False, 'error': ''},
                                            {'label': 'audio', 'added': True, 'error': ''}])
        self.assertEqual(CONFIG['DELUGE_LABEL_AUDIO'], 'audio')
        client.return_value.call.assert_any_call('label.add', 'audio')

    def test_deluge_daemon_failure(self):
        client = mock.MagicMock()
        client.return_value.connect.side_effect = ConnectionRefusedError('Connection refused')
        with mock.patch.object(connections, 'DelugeRPCClient', client):
            found = connections.test_deluge({'user': 'me'})
        self.assertIsInstance(found['error'], ConnectionRefusedError)
        self.save.assert_not_called()

    def test_provider(self):
        self.assertEqual(connections.test_provider('p<rov')['bad'], ['name'])
        with mock.patch.object(connections, 'provider_test', return_value=(3, 'Prov')), \
                mock.patch.object(connections, 'wishlist_type', return_value='goodreads'):
            self.assertEqual(connections.test_provider('prov', host='h')['name'], 'Wishlist goodreads Prov')
        with mock.patch.object(connections, 'provider_test', return_value=(False, 'Prov')):
            self.assertIs(connections.test_provider('prov')['result'], False)
        self.save.assert_called_once_with(section='prov')

    def test_hardcover_auth(self):
        with mock.patch('lazylibrarian.hc.test_auth', return_value='123'):
            self.assertEqual(connections.test_hardcover_auth(token='t'), 'Pass: whoami=123')

    def test_tools(self):
        with self.assertRaises(InvalidRequestError):
            connections.test_ffmpeg('ff<mpeg')
        with mock.patch.object(connections.subprocess, 'check_output', return_value=b'ffmpeg version 6.1 Copyright'):
            self.assertEqual(connections.test_ffmpeg('ffmpeg'), '6.1')
        with mock.patch.object(connections.subprocess, 'check_output', side_effect=OSError('missing')), \
                self.assertRaises(ServiceError):
            connections.test_ffmpeg('ffmpeg')
        CONFIG.set_str('EXT_PREPROCESS', '')
        self.assertIsNone(connections.test_preprocessor())
        with mock.patch.object(connections, 'run_script', return_value=(0, 'ok', '')):
            self.assertEqual(connections.test_preprocessor('pre'), (0, 'ok', ''))

    def test_googlebooks(self):
        """ What Google says of the key as it's kept, and what the key is like, never the key itself """
        key = 'AIzaSyExampleExampleExampleExample12345'
        CONFIG.set_str('GB_API', '')
        self.assertEqual(connections.test_googlebooks(), (False, 'There is no GoogleBooks API key'))
        CONFIG.set_str('GB_API', f'{key}\n')
        refused = mock.Mock(status_code=400)
        refused.json.return_value = {'error': {'message': 'API key not valid. Please pass a valid API key.'}}
        with mock.patch('requests.get', return_value=refused) as asked:
            ok, message = connections.test_googlebooks()
        self.assertFalse(ok)
        self.assertEqual(asked.call_args.kwargs['params']['key'], f'{key}\n', 'The key as it is kept')
        self.assertIn('spaces or a line break around it', message)
        self.assertNotIn(key, message)
        CONFIG.set_str('GB_API', key)
        with mock.patch('requests.get', return_value=mock.Mock(status_code=200)):
            self.assertEqual(connections.test_googlebooks(), (True, f'Google takes the key. It has {len(key)} characters'))
