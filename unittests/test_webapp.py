#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the FastAPI app that hosts the CherryPy pages, and starting and stopping it with uvicorn

import socket
from unittest import mock

import requests
import uvicorn
from fastapi.testclient import TestClient

from lazylibrarian import webapp, webStart
from unittests.unittesthelpers import LLTestCaseWithDB


def legacy_app(environ, start_response):
    """ Stands in for the CherryPy pages, answers with what it was asked for """
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [f"{environ['SCRIPT_NAME']}|{environ['PATH_INFO']}|{environ['QUERY_STRING']}".encode()]


class WebAppTest(LLTestCaseWithDB):

    def client(self, http_root=''):
        return TestClient(webapp.create_app(http_root, legacy_app))

    def test_url_root(self):
        for http_root, root in (('', ''), ('/', ''), ('ll', '/ll'), ('/ll/', '/ll'), (' /ll ', '/ll')):
            self.assertEqual(webapp.url_root(http_root), root, http_root)

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
