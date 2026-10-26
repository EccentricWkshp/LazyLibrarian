#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the FastAPI app that hosts the CherryPy pages and /api/v1, and starting and stopping it

import os
import socket
from unittest import mock

import requests
import uvicorn
from fastapi.testclient import TestClient

from lazylibrarian import auth, passwords, sessions, webapp, webStart
from lazylibrarian.common import url_root
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.services import queue
from lazylibrarian.sessions import SESSION_COOKIE
from unittests.unittesthelpers import TESTDIR, LLTestCaseWithDB


def legacy_app(environ, start_response):
    """ Stands in for the CherryPy pages, answers with what it was asked for """
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [f"{environ['SCRIPT_NAME']}|{environ['PATH_INFO']}|{environ['QUERY_STRING']}".encode()]


class WebAppTest(LLTestCaseWithDB):

    def client(self, http_root=''):
        return TestClient(webapp.create_app(http_root, legacy_app))

    def test_url_root(self):
        for http_root, root in (('', ''), ('/', ''), ('ll', '/ll'), ('/ll/', '/ll'), (' /ll ', '/ll')):
            self.assertEqual(url_root(http_root), root, http_root)

    def test_no_telemetry(self):
        with mock.patch.dict('os.environ', {'FASTAPI_OTEL_AUTO_CONFIGURE': 'true'}):
            app = webapp.create_app('', legacy_app)
        self.assertFalse(app._native_telemetry.enabled())
        self.assertFalse(any(app._telemetry[key] for key in webapp.NO_TELEMETRY))

    def test_ping(self):
        for http_root in ('', '/ll'):
            response = self.client(http_root).get(f'{http_root}/ping')
            self.assertEqual((response.status_code, response.json()), (200, {'status': 'OK'}), http_root)

    def test_ping_without_database(self):
        broken = mock.MagicMock()
        broken.return_value.match.side_effect = Exception('database is locked')
        with mock.patch('lazylibrarian.database.DBConnection', broken):
            response = self.client().get('/ping')
        self.assertEqual((response.status_code, response.json()), (503, {'status': 'Error'}))
        broken.return_value.close.assert_called_once()

    def test_everything_else_goes_to_cherrypy(self):
        client = self.client('/ll')
        # CherryPy is mounted at HTTP_ROOT itself, so it gets the whole path
        self.assertEqual(client.get('/ll/books?a=1').text, '|/ll/books|a=1')
        self.assertEqual(client.get('/ping').text, '|/ping|', 'Outside HTTP_ROOT is not ours')
        self.assertEqual(client.post('/ll/api', data={'cmd': 'x'}).text, '|/ll/api|')


class ServerTest(LLTestCaseWithDB):
    """ uvicorn serving the app in its own thread """

    def serve(self, port):
        patch = mock.patch.object(webStart, '_server_config', uvicorn.Config(
            webapp.create_app('', legacy_app), host='127.0.0.1', port=port, log_config=None))
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(webStart.stop)
        return webStart.start()

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def test_start_and_stop(self):
        port = self.free_port()
        self.assertTrue(self.serve(port))
        self.assertTrue(webStart.running())
        self.assertEqual(requests.get(f'http://127.0.0.1:{port}/ping', timeout=5).json(), {'status': 'OK'})
        webStart.stop()
        self.assertFalse(webStart.running())
        with self.assertRaises(requests.ConnectionError):
            requests.get(f'http://127.0.0.1:{port}/ping', timeout=5)

    def test_port_in_use(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen()
            with self.assertLogs('uvicorn.error', 'ERROR'):
                self.assertFalse(self.serve(sock.getsockname()[1]))
        self.assertFalse(webStart.running())


class UiTest(LLTestCaseWithDB):
    """ The single page front end's pages and files """

    def setUp(self):
        super().setUp()
        self.ui_dir = os.path.join(TESTDIR, 'ui')
        os.makedirs(os.path.join(self.ui_dir, 'assets'), exist_ok=True)
        with open(os.path.join(self.ui_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html><head><script src="./assets/app.js"></script></head><body></body></html>')
        with open(os.path.join(self.ui_dir, 'assets', 'app.js'), 'w', encoding='utf-8') as f:
            f.write('console.log(1)')
        saved = {key: CONFIG[key] for key in ('AUTH_TYPE', 'AUTH_REQUIRED', 'HTTP_ROOT')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
        CONFIG.set_str('AUTH_TYPE', 'FORM')
        CONFIG.set_str('AUTH_REQUIRED', 'ENABLED')
        CONFIG.set_str('HTTP_ROOT', '/ll')
        patch = mock.patch.object(passwords, 'ITERATIONS', 1000)
        patch.start()
        self.addCleanup(patch.stop)
        auth.reset_owner_cache()
        self.addCleanup(auth.reset_owner_cache)

    def test_pages(self):
        client = TestClient(webapp.create_app('/ll', legacy_app, self.ui_dir))
        with DBConnection() as db:
            auth.set_owner_credentials(db, username='owner', password='correct horse')
            token = sessions.create_session(db, auth.owner_id(), False)
        response = client.get('/ll/activity/queue', follow_redirects=False)
        self.assertEqual((response.status_code, response.headers['Location']),
                         (303, '/ll/auth/login?from_page=/ll/activity/queue'))
        self.assertEqual(client.get('/ll/ui/assets/app.js').text, 'console.log(1)', 'Its files need no login')

        client.cookies.set(SESSION_COOKIE, token)
        for path in ('/ll/activity', '/ll/activity/queue', '/ll/activity/some/thing'):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('<base href="/ll/ui/">', response.text)
            self.assertIn('window.LazyLibrarian = {"urlBase": "/ll"', response.text)
        self.assertEqual(client.get('/ll/history').text, '|/ll/history|', 'The old pages are still CherryPy')

    def test_without_a_build(self):
        client = TestClient(webapp.create_app('/ll', legacy_app, os.path.join(TESTDIR, 'noui')))
        self.assertEqual(client.get('/ll/activity/queue').text, '|/ll/activity/queue|')

    def test_settings_cannot_end_the_script(self):
        with mock.patch.object(webapp, 'CONFIG') as config:
            config.__getitem__.return_value = '</script><script>alert(1)'
            config.get_bool.return_value = True
            page = webapp.ui_page(self.ui_dir, '/ll')
        self.assertNotIn('</script><script>alert', page)


class ApiV1Test(LLTestCaseWithDB):
    """ /api/v1 takes an API key or the pages' login, with the same checks as the pages """
    FULL_KEY = 'f' * 32
    READ_KEY = 'r' * 32
    SETTINGS = ('API_ENABLED', 'API_KEY', 'API_RO_KEY', 'AUTH_TYPE', 'AUTH_REQUIRED', 'WHITELIST', 'HTTP_ROOT')

    def setUp(self):
        super().setUp()
        saved = {key: CONFIG[key] for key in self.SETTINGS}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
        CONFIG.set_bool('API_ENABLED', True)
        CONFIG.set_str('API_KEY', self.FULL_KEY)
        CONFIG.set_str('API_RO_KEY', self.READ_KEY)
        CONFIG.set_str('AUTH_TYPE', 'FORM')
        CONFIG.set_str('AUTH_REQUIRED', 'ENABLED')
        CONFIG.set_str('WHITELIST', '')
        CONFIG.set_str('HTTP_ROOT', '/ll')
        patch = mock.patch.object(passwords, 'ITERATIONS', 1000)
        patch.start()
        self.addCleanup(patch.stop)
        auth.reset_owner_cache()
        self.addCleanup(auth.reset_owner_cache)
        self.client = TestClient(webapp.create_app('/ll', legacy_app))

    @staticmethod
    def set_owner():
        """ Finish first-run setup, return a login session token """
        with DBConnection() as db:
            auth.set_owner_credentials(db, username='owner', password='correct horse')
            return sessions.create_session(db, auth.owner_id(), False)

    def get(self, path='/ll/api/v1/system/status', **kwargs):
        return self.client.get(path, **kwargs)

    def test_status(self):
        self.set_owner()
        response = self.get(headers={'X-Api-Key': self.FULL_KEY})
        self.assertEqual(response.status_code, 200)
        status = response.json()
        self.assertEqual(status['appName'], 'LazyLibrarian')
        self.assertEqual(status['urlBase'], '/ll')
        self.assertIsInstance(status['databaseVersion'], int)
        self.assertIn('pythonVersion', status, 'camelCase, like Sonarr')

    def test_api_keys(self):
        self.set_owner()
        self.assertEqual(self.get(headers={'X-Api-Key': self.READ_KEY}).status_code, 200)
        self.assertEqual(self.get(params={'apikey': self.FULL_KEY}).status_code, 200)
        response = self.get(headers={'X-Api-Key': 'x' * 32})
        self.assertEqual((response.status_code, response.json()['detail']),
                         (401, 'Incorrect API key, or the API is not enabled'))
        CONFIG.set_bool('API_ENABLED', False)
        self.assertEqual(self.get(headers={'X-Api-Key': self.FULL_KEY}).status_code, 401)

    def test_read_only_key_cannot_change_things(self):
        self.set_owner()
        response = self.client.post('/ll/api/v1/system/status', headers={'X-Api-Key': self.READ_KEY})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/ll/api/v1/system/status', headers={'X-Api-Key': self.FULL_KEY})
        self.assertEqual(response.status_code, 404, 'Allowed in, but there is no such endpoint')

    def test_login_session(self):
        token = self.set_owner()
        response = self.get()
        self.assertEqual((response.status_code, response.json()), (401, {'detail': 'Unauthorized'}),
                         'An API answers 401, it does not redirect to the login page')
        self.client.cookies.set(SESSION_COOKIE, token)
        self.assertEqual(self.get().status_code, 200)
        response = self.get(headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'cors'})
        self.assertEqual((response.status_code, response.json()['detail']), (403, 'Cross-site request refused'))

    def test_before_setup(self):
        response = self.get()
        self.assertEqual((response.status_code, response.json()['detail']),
                         (401, 'Authentication has not been set up'))

    def test_basic_auth(self):
        self.set_owner()
        CONFIG.set_str('AUTH_TYPE', 'BASIC')
        response = self.get()
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers['WWW-Authenticate'].startswith('Basic'))
        self.assertEqual(self.get(auth=('owner', 'correct horse')).status_code, 200)

    def test_whitelist(self):
        self.set_owner()
        with mock.patch.object(auth, 'client_ip', return_value='192.168.1.20'):
            self.assertEqual(self.get().status_code, 401)
            CONFIG.set_str('WHITELIST', '192.168.1.0/24')
            self.assertEqual(self.get().status_code, 200)

    def test_docs(self):
        token = self.set_owner()
        response = self.get('/ll/api/v1/docs', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['Location'], '/ll/auth/login?from_page=/ll/api/v1/docs')
        self.client.cookies.set(SESSION_COOKIE, token)
        response = self.get('/ll/api/v1/docs')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/ll/api/v1/openapi.json', response.text)
        schema = self.get('/ll/api/v1/openapi.json').json()
        self.assertIn('/ll/api/v1/system/status', schema['paths'])
        self.client.cookies.clear()
        self.assertEqual(self.get('/ll/api/v1/openapi.json').status_code, 401)

    def test_remote_path_mappings(self):
        self.set_owner()
        key = {'X-Api-Key': self.FULL_KEY}
        local = os.path.join(TESTDIR, 'apimapping')
        os.makedirs(local, exist_ok=True)
        url = '/ll/api/v1/remotepathmapping'
        response = self.client.post(url, headers=key, json={'host': 'NAS', 'remotePath': '/downloads/books',
                                                            'localPath': local})
        self.assertEqual(response.status_code, 201, response.text)
        mapping = response.json()
        self.assertEqual({k: v for k, v in mapping.items() if k != 'id'},
                         {'host': 'nas', 'remotePath': '/downloads/books', 'localPath': local}, 'Like Sonarr')
        self.assertEqual(self.get(url, headers=key).json(), [mapping])
        response = self.client.post(url, headers=key, json={'host': 'nas', 'remotePath': '/downloads/books',
                                                            'localPath': local})
        self.assertEqual((response.status_code, response.json()['detail']),
                         (400, 'There is already a mapping for that host and remote path'))
        response = self.client.put(f"{url}/{mapping['id']}", headers=key,
                                   json={'host': 'nas', 'remotePath': '/downloads/ebooks', 'localPath': local})
        self.assertEqual(response.json()['remotePath'], '/downloads/ebooks')
        self.assertEqual(self.client.delete(f"{url}/{mapping['id']}", headers={'X-Api-Key': self.READ_KEY}).status_code,
                         403, 'The read-only key')
        self.assertEqual(self.client.delete(f"{url}/{mapping['id']}", headers=key).status_code, 204)
        self.assertEqual(self.get(f"{url}/{mapping['id']}", headers=key).status_code, 404)

    def test_queue_and_manual_import(self):
        self.set_owner()
        key = {'X-Api-Key': self.FULL_KEY}
        with DBConnection() as db:
            db.action("DELETE FROM wanted")
            db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,"
                      "Source,DownloadID,DLResult) VALUES ('2024-05','u1','Mag.May','2026-10-26 10:00:00','prov',"
                      "'Snatched','1.5','2024-05','torrent','QBITTORRENT','abc','Import blocked: no files')")
        queue._asked.clear()
        with mock.patch('lazylibrarian.services.queue.get_download_progress', return_value=(100, True)):
            items = self.get('/ll/api/v1/queue', headers=key).json()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item['mediaType'], item['issue'], item['protocol'], item['downloadClient'], item['size']),
                         ('magazine', '2024-05', 'torrent', 'qBittorrent', 1572864))
        self.assertEqual((item['trackedDownloadState'], item['statusMessages'][0]['messages']),
                         ('importBlocked', ['no files']), 'Like Sonarr')

        response = self.get('/ll/api/v1/manualimport', headers=key, params={'folder': 'relative'})
        self.assertEqual((response.status_code, response.json()['detail']), (400, 'Choose a folder, as a full path'))
        response = self.get('/ll/api/v1/filesystem', headers=key, params={'path': TESTDIR})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(os.path.isdir(folder['path']) for folder in response.json()['directories']))
        self.assertEqual(self.get('/ll/api/v1/book', headers=key, params={'term': 'zzzznothing'}).json(), [])

        response = self.client.post('/ll/api/v1/command', headers=key, json={
            'name': 'ManualImport', 'files': [{'path': '/nowhere', 'mediaType': 'ebook', 'bookId': 'x'}]})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['name'], 'ManualImport')
        self.assertEqual(self.get(f"/ll/api/v1/command/{response.json()['id']}", headers=key).status_code, 200)

        with mock.patch('lazylibrarian.services.queue.delete_task', return_value=True):
            response = self.client.delete(f"/ll/api/v1/queue/{item['id']}", headers=key,
                                          params={'removeFromClient': 'false', 'blocklist': 'true'})
        self.assertEqual((response.status_code, response.json()), (200, {'message': ''}))
        with DBConnection() as db:
            self.assertEqual(db.match("SELECT Status FROM wanted WHERE NZBurl='u1'")['Status'], 'Failed')

    def test_unknown_endpoint_is_not_the_old_api(self):
        self.set_owner()
        response = self.get('/ll/api/v1/nosuch', headers={'X-Api-Key': self.FULL_KEY})
        self.assertEqual((response.status_code, response.json()['detail']), (404, 'No such endpoint: nosuch'))
        self.assertEqual(self.get('/ll/api', params={'cmd': 'help'}).text, '|/ll/api|cmd=help', 'Still CherryPy')
