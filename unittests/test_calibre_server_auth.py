#  This file is part of Lazylibrarian.
#
# Purpose:
#   Issue #3102: the REST client in calibre.py sent HTTP Basic auth, but a Calibre
#   Content Server with auth enabled only accepts HTTP Digest. Basic credentials
#   are rejected with "400 Unsupported authentication method", so every REST call
#   failed and the code silently fell back to calibredb CLI / local metadata.db.
#   calibre_server_request() must build an HTTPDigestAuth when CALIBRE_USER/PASS
#   are set, and pass no auth object at all when they are empty (so servers
#   without auth are unaffected - Digest only sends credentials after a 401
#   challenge, it never volunteers them).

from unittest import mock

from requests.auth import HTTPDigestAuth

from lazylibrarian import calibre
from unittests.unittesthelpers import LLTestCase


class FakeConfig(dict):
    def get_bool(self, key):
        return bool(self.get(key))


class CalibreServerRequestAuthTest(LLTestCase):

    def _run(self, user, passwd, server='http://192.0.2.10:8081/#my-library'):
        cfg = FakeConfig(CALIBRE_SERVER=server, CALIBRE_USER=user,
                         CALIBRE_PASS=passwd, HTTPS_ENABLED=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre.requests, 'request', return_value=mock.Mock(status_code=200)) as req:
            calibre.calibre_server_request('ajax/library-info')
        return req.call_args

    def test_credentials_set_uses_digest_auth(self):
        auth = self._run('terje', 'secret').kwargs['auth']
        self.assertIsInstance(auth, HTTPDigestAuth)
        self.assertEqual(auth.username, 'terje')
        self.assertEqual(auth.password, 'secret')

    def test_empty_credentials_send_no_auth(self):
        # no auth object at all - not a BasicAuth tuple, not a DigestAuth
        self.assertIsNone(self._run('', '').kwargs['auth'])

    def test_library_fragment_becomes_query_param_not_url_fragment(self):
        # "#library" suffix must not stay in the URL (would swallow the endpoint);
        # it is passed as ?library= so the ajax endpoint is actually reached
        called_url = self._run('terje', 'secret').args[1]
        self.assertNotIn('#', called_url)
        self.assertIn('ajax/library-info', called_url)
        self.assertIn('library=my-library', called_url)

    def test_server_without_fragment_unchanged(self):
        called_url = self._run('terje', 'secret', server='http://192.0.2.10:8081').args[1]
        self.assertNotIn('#', called_url)
        self.assertNotIn('library=', called_url)
        self.assertTrue(called_url.startswith('http://192.0.2.10:8081/ajax/library-info'))
