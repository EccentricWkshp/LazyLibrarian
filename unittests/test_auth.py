#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the single owner account: sessions, request authentication, the login form,
#   first-run setup, cross-site request checks and the v101 upgrade from user accounts / config file logins

import base64
import contextlib
import time
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest import mock

import cherrypy

import lazylibrarian
from lazylibrarian import auth, dbupgrade, passwords, sessions
from lazylibrarian.config2 import LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS
from lazylibrarian.database import DBConnection
from lazylibrarian.dbupgrade import db_upgrade, upgrade_needed
from lazylibrarian.filesystem import DIRS, remove_file
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS

FAST = 1000


class FakeConfig(dict):
    def get_bool(self, key):
        return bool(self.get(key))

    def get_str(self, key):
        return str(self.get(key, ''))

    def get_csv(self, key):
        return self.get(key, '')

    def set_str(self, key, value):
        self[key] = value

    def set_bool(self, key, value):
        self[key] = value

    save_config_and_backup_old = mock.Mock()


def make_config(**kwargs):
    cfg = FakeConfig(HTTP_ROOT='', PROXY_LOCAL='', WHITELIST='', PROXY_AUTH_USER='X-User', AUTH_TYPE='FORM',
                     AUTH_REQUIRED='ENABLED', USER_ACCOUNTS=False, SINGLE_USER=False, HTTP_USER='', HTTP_PASS='')
    cfg.update(kwargs)
    return cfg


class FakeRequest:
    def __init__(self, cookies=None, headers=None, ip='203.0.113.5', method='GET', path='/books'):
        self.cookie = SimpleCookie()
        for key, value in (cookies or {}).items():
            self.cookie[key] = value
        self.headers = headers or {}
        self.remote = SimpleNamespace(ip=ip)
        self.base = 'http://ll.example'
        self.method = method
        self.request_line = f'{method} {path} HTTP/1.1'
        self.path_info = path.split('?', 1)[0]
        self.config = {'auth.require': []}


class FakeResponse:
    def __init__(self):
        self.cookie = SimpleCookie()
        self.headers = {}


class AuthDBTestCase(LLTestCaseWithConfigandDIRS):
    """ Each test gets a fresh database, which has just the owner account """

    def setUp(self):
        super().setUp()
        # other test classes expect the default database name back
        self.addCleanup(setattr, DIRS, 'DBFILENAME', DIRS.DBFILENAME)
        DIRS.DBFILENAME = "test-auth.db"
        with contextlib.suppress(FileNotFoundError):
            remove_file(DIRS.get_dbfile())
        db_upgrade(upgrade_needed(), restartjobs=False)
        self.cfg = make_config()
        for patch in [mock.patch.object(auth, 'CONFIG', self.cfg), mock.patch.object(dbupgrade, 'CONFIG', self.cfg),
                      mock.patch.object(passwords, 'ITERATIONS', FAST)]:
            patch.start()
            self.addCleanup(patch.stop)
        auth.reset_owner_cache()
        with auth._lock:
            auth._failed_logins.clear()
            auth._basic_cache.clear()

    def tearDown(self):
        auth.reset_owner_cache()
        remove_file(DIRS.get_dbfile())
        super().tearDown()

    @staticmethod
    def query(sql, args=()):
        db = DBConnection()
        try:
            return db.select(sql, args)
        finally:
            db.close()

    @staticmethod
    def action(sql, args=()):
        db = DBConnection()
        try:
            db.action(sql, args)
        finally:
            db.close()

    def set_owner(self, username='owner', password='correct horse'):
        db = DBConnection()
        try:
            auth.set_owner_credentials(db, username=username, password=password)
        finally:
            db.close()
        return auth.owner_id()

    def use_request(self, **kwargs):
        request, response = FakeRequest(**kwargs), FakeResponse()
        # HTTPRedirect makes urls absolute with cherrypy.url(), which needs a real request
        for patch in [mock.patch.object(cherrypy, 'request', request),
                      mock.patch.object(cherrypy, 'response', response),
                      mock.patch.object(cherrypy, 'url', return_value='http://ll.example/')]:
            patch.start()
            self.addCleanup(patch.stop)
        return request, response


class OwnerAccountTest(AuthDBTestCase):

    def test_new_database_has_owner_without_credentials(self):
        rows = self.query('SELECT * from users')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Perms'], lazylibrarian.perm_admin)
        self.assertEqual(auth.owner_id(), rows[0]['UserID'])
        db = DBConnection()
        try:
            self.assertFalse(auth.credentials_set(auth.get_owner(db)))
        finally:
            db.close()

    def test_set_credentials(self):
        self.set_owner('owner', 'correct horse')
        db = DBConnection()
        try:
            owner = auth.get_owner(db)
            self.assertTrue(auth.credentials_set(owner))
            self.assertEqual(owner['UserName'], 'owner')
            self.assertTrue(passwords.verify_password('correct horse', owner['Password']))
        finally:
            db.close()

    def test_new_password_logs_out_other_sessions(self):
        userid = self.set_owner()
        db = DBConnection()
        try:
            keep = sessions.create_session(db, userid, False)
            other = sessions.create_session(db, userid, True)
            auth.set_owner_credentials(db, password='battery staple', keep_token=keep)
            self.assertIsNotNone(sessions.lookup_session(db, keep))
            self.assertIsNone(sessions.lookup_session(db, other))
        finally:
            db.close()


class SessionTest(AuthDBTestCase):

    def test_round_trip(self):
        userid = auth.owner_id()
        db = DBConnection()
        try:
            token = sessions.create_session(db, userid, True, '198.51.100.1', 'test agent')
            self.assertEqual(sessions.lookup_session(db, token), (userid, True))
            stored = db.match('SELECT * from sessions')
            self.assertNotEqual(stored['TokenHash'], token, 'Only the hash of the token is stored')
            sessions.delete_session(db, token)
            self.assertIsNone(sessions.lookup_session(db, token))
        finally:
            db.close()

    def test_unknown_or_empty_token(self):
        db = DBConnection()
        try:
            self.assertIsNone(sessions.lookup_session(db, ''))
            self.assertIsNone(sessions.lookup_session(db, 'not a token'))
        finally:
            db.close()

    def test_expired_session_is_removed(self):
        db = DBConnection()
        try:
            token = sessions.create_session(db, auth.owner_id(), False)
            db.action('UPDATE sessions SET Expires=?', (int(time.time()) - 1,))
            self.assertIsNone(sessions.lookup_session(db, token))
            self.assertEqual(db.match('SELECT count(*) as c from sessions')['c'], 0)
        finally:
            db.close()

    def test_session_slides(self):
        db = DBConnection()
        try:
            token = sessions.create_session(db, auth.owner_id(), False)
            old = int(time.time()) - sessions.REFRESH_SECONDS - 10
            db.action('UPDATE sessions SET LastSeen=?, Expires=?', (old, int(time.time()) + 60))
            self.assertIsNotNone(sessions.lookup_session(db, token))
            res = db.match('SELECT LastSeen, Expires from sessions')
            self.assertGreater(res['LastSeen'], old)
            self.assertGreater(res['Expires'], time.time() + sessions.TRANSIENT_SECONDS - 60)
        finally:
            db.close()


class AuthenticateRequestTest(AuthDBTestCase):

    def basic(self, username, password):
        return 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode('ascii')

    def test_nothing_gets_in_before_setup(self):
        self.cfg['WHITELIST'] = '10.0.0.0/8'
        self.cfg['AUTH_REQUIRED'] = 'DISABLED_LOCAL'
        for ip in ['203.0.113.5', '10.1.2.3', '127.0.0.1']:
            self.use_request(ip=ip)
            self.assertEqual(auth.authenticate_request(), '', ip)
            self.assertTrue(cherrypy.request.ll_setup)

    def test_check_auth_sends_page_loads_to_setup(self):
        self.use_request(path='/books')
        with self.assertRaises(cherrypy.HTTPRedirect) as cm:
            auth.check_auth()
        self.assertIn('/auth/setup?from_page=/books', cm.exception.urls[0])
        self.use_request(headers={'X-Requested-With': 'XMLHttpRequest'})
        with self.assertRaises(cherrypy.HTTPError) as cm:
            auth.check_auth()
        self.assertEqual(cm.exception.status, 401)

    def test_no_credentials_denied(self):
        self.set_owner()
        self.use_request()
        self.assertEqual(auth.authenticate_request(), '')
        self.assertIsNone(cherrypy.request.login)

    def test_session_cookie(self):
        userid = self.set_owner()
        db = DBConnection()
        try:
            token = sessions.create_session(db, userid, False)
        finally:
            db.close()
        self.use_request(cookies={sessions.SESSION_COOKIE: token})
        self.assertEqual(auth.authenticate_request(), 'session')
        self.assertEqual(cherrypy.request.login, 'owner')

    def test_old_user_id_cookie_is_not_a_login(self):
        userid = self.set_owner()
        self.use_request(cookies={'ll_uid': userid, sessions.SESSION_COOKIE: userid})
        self.assertEqual(auth.authenticate_request(), '')

    def test_basic_header(self):
        self.set_owner()
        self.use_request(headers={'Authorization': self.basic('owner', 'correct horse')})
        self.assertEqual(auth.authenticate_request(), 'basic')
        # and again from the cache, without checking the password
        with mock.patch.object(auth, 'check_user_password') as check:
            self.assertEqual(auth.authenticate_request(), 'basic')
            check.assert_not_called()

    def test_bad_basic_header(self):
        self.set_owner()
        for header in [self.basic('owner', 'wrong'), self.basic('someone', 'correct horse'), 'Basic !!!',
                       'Bearer abc', 'Basic ' + base64.b64encode(b'no-colon').decode('ascii')]:
            self.use_request(headers={'Authorization': header})
            self.assertEqual(auth.authenticate_request(), '', header)

    def test_password_change_clears_basic_cache(self):
        self.set_owner()
        self.use_request(headers={'Authorization': self.basic('owner', 'correct horse')})
        self.assertEqual(auth.authenticate_request(), 'basic')
        self.set_owner(password='battery staple')
        self.assertEqual(auth.authenticate_request(), '')

    def test_whitelist(self):
        self.set_owner()
        self.cfg['WHITELIST'] = '10.0.0.0/8'
        self.use_request(ip='10.1.2.3')
        self.assertEqual(auth.authenticate_request(), 'whitelist')
        self.use_request(ip='203.0.113.5')
        self.assertEqual(auth.authenticate_request(), '')

    def test_local_bypass(self):
        self.set_owner()
        self.use_request(ip='192.168.1.20')
        self.assertEqual(auth.authenticate_request(), '', 'Authentication required by default')
        self.cfg['AUTH_REQUIRED'] = 'DISABLED_LOCAL'
        self.assertEqual(auth.authenticate_request(), 'local')
        self.use_request(ip='203.0.113.5')
        self.assertEqual(auth.authenticate_request(), '')

    def test_is_local_address(self):
        for ip in ['127.0.0.1', '10.0.0.5', '172.16.4.4', '172.31.255.1', '192.168.0.1', '169.254.1.1', '::1',
                   'fd00::1', 'fe80::1', '::ffff:192.168.1.5']:
            self.assertTrue(auth.is_local_address(ip), ip)
        for ip in ['8.8.8.8', '172.32.0.1', '203.0.113.5', '2001:db8::1', '::ffff:8.8.8.8', '', None, 'nonsense']:
            self.assertFalse(auth.is_local_address(ip), ip)

    def test_external_uses_only_the_proxy_header(self):
        userid = self.set_owner()
        self.use_request(headers={'X-User': 'owner'})
        self.assertEqual(auth.authenticate_request(), '', 'The header is ignored unless the method is External')
        self.cfg['AUTH_TYPE'] = 'EXTERNAL'
        self.assertEqual(auth.authenticate_request(), 'external')
        self.use_request(headers={'X-User': 'someone'})
        self.assertEqual(auth.authenticate_request(), '')
        db = DBConnection()
        try:
            token = sessions.create_session(db, userid, False)
        finally:
            db.close()
        self.use_request(cookies={sessions.SESSION_COOKIE: token},
                         headers={'Authorization': self.basic('owner', 'correct horse')})
        self.assertEqual(auth.authenticate_request(), '', 'External ignores sessions and Basic auth')
        with self.assertRaises(cherrypy.HTTPError) as cm:
            auth.check_auth()
        self.assertEqual(cm.exception.status, 401)

    def test_check_auth_forms_redirects_to_login(self):
        self.set_owner()
        self.use_request(path='/books?x=1')
        with self.assertRaises(cherrypy.HTTPRedirect) as cm:
            auth.check_auth()
        self.assertIn('/auth/login?from_page=/books%3Fx%3D1', cm.exception.urls[0])

    def test_check_auth_ajax_gets_401(self):
        self.set_owner()
        self.use_request(headers={'X-Requested-With': 'XMLHttpRequest'})
        with self.assertRaises(cherrypy.HTTPError) as cm:
            auth.check_auth()
        self.assertEqual(cm.exception.status, 401)

    def test_check_auth_basic_challenges(self):
        self.set_owner()
        self.cfg['AUTH_TYPE'] = 'BASIC'
        _, response = self.use_request()
        with self.assertRaises(cherrypy.HTTPError) as cm:
            auth.check_auth()
        self.assertEqual(cm.exception.status, 401)
        self.assertIn('Basic realm="LazyLibrarian"', response.headers['WWW-Authenticate'])

    def test_check_auth_skips_undecorated(self):
        self.set_owner()
        request, _ = self.use_request()
        request.config = {}
        self.assertIsNone(auth.check_auth())


class LoginFormTest(AuthDBTestCase):

    def login(self, username, password, remember='', from_page='/books'):
        self.use_request(method='POST')
        with mock.patch.object(auth.AuthController, 'get_loginform', return_value='form') as form:
            try:
                auth.AuthController().login(current_username=username, current_password=password,
                                            remember_me=remember, from_page=from_page)
            except cherrypy.HTTPRedirect as redirect:
                return redirect, form
        return None, form

    def test_good_login(self):
        self.set_owner()
        redirect, _ = self.login('owner', 'correct horse', remember='1')
        self.assertIsNotNone(redirect)
        self.assertTrue(redirect.urls[0].endswith('/books'))
        cookie = cherrypy.response.cookie[sessions.SESSION_COOKIE]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['max-age'], sessions.PERSISTENT_SECONDS)
        db = DBConnection()
        try:
            self.assertEqual(sessions.lookup_session(db, cookie.value), (auth.owner_id(), True))
            self.assertEqual(db.match('SELECT Login_Count from users')['Login_Count'], 1)
        finally:
            db.close()

    def test_session_cookie_without_remember_me(self):
        self.set_owner()
        self.login('owner', 'correct horse')
        self.assertEqual(cherrypy.response.cookie[sessions.SESSION_COOKIE]['max-age'], '')

    def test_bad_login(self):
        self.set_owner()
        redirect, form = self.login('owner', 'wrong')
        self.assertIsNone(redirect)
        self.assertIn('Incorrect', form.call_args.args[1])
        self.assertNotIn(sessions.SESSION_COOKIE, cherrypy.response.cookie)

    def test_login_before_setup_goes_to_setup(self):
        redirect, _ = self.login('', '')
        self.assertTrue(redirect.urls[0].endswith('/auth/setup'))

    def test_login_page_not_used_for_basic(self):
        self.set_owner()
        self.cfg['AUTH_TYPE'] = 'BASIC'
        redirect, _ = self.login('owner', 'correct horse')
        self.assertTrue(redirect.urls[0].endswith('/books'))
        self.assertNotIn(sessions.SESSION_COOKIE, cherrypy.response.cookie)

    def test_too_many_failures(self):
        self.set_owner()
        for _ in range(auth.MAX_FAILED_LOGINS):
            self.login('owner', 'wrong')
        redirect, form = self.login('owner', 'correct horse')
        self.assertIsNone(redirect, 'Blocked even with the right password')
        self.assertIn('Too many', form.call_args.args[1])

    def test_get_shows_form(self):
        self.set_owner()
        self.use_request(method='GET')
        with mock.patch.object(auth.AuthController, 'get_loginform', return_value='form'):
            self.assertEqual(auth.AuthController().login(current_username='owner',
                                                         current_password='correct horse'), 'form')

    def test_safe_from_page(self):
        self.assertEqual(auth.safe_from_page('/books'), '/books')
        self.assertEqual(auth.safe_from_page('/author_page?authorid=1'), '/author_page?authorid=1')
        for bad in ['https://evil.example/', '//evil.example/', '/\\evil.example', '', 'books',
                    '/mark_books_ajax?action=Delete', '/shutdown', '/logout', '/auth/setup']:
            self.assertEqual(auth.safe_from_page(bad), '/home', bad)
        self.cfg['HTTP_ROOT'] = '/ll'
        self.assertEqual(auth.safe_from_page('/ll/books'), '/ll/books')
        self.assertEqual(auth.safe_from_page('/books'), '/ll/books')
        self.assertEqual(auth.safe_from_page('//evil.example'), '/ll/home')
        self.assertEqual(auth.safe_from_page('/ll/restart'), '/ll/home')

    def test_cross_site_login_refused(self):
        self.set_owner()
        self.use_request(method='POST', headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'},
                         path='/auth/login')
        with self.assertRaises(cherrypy.HTTPError) as cm:
            auth.AuthController().login(current_username='owner', current_password='correct horse')
        self.assertEqual(cm.exception.status, 403)
        self.assertNotIn(sessions.SESSION_COOKIE, cherrypy.response.cookie)


class MigrationTest(AuthDBTestCase):
    """ The v101 upgrade, run against users tables like older versions left behind """

    def setUp(self):
        super().setUp()
        self.action('DELETE from users')
        self.action('DROP TABLE sessions')
        self.cfg.save_config_and_backup_old.reset_mock()

    def add_user(self, userid, username, perms, last_login, password='x'):
        self.action('INSERT into users (UserID, UserName, Name, Password, Perms, Last_Login, Login_Count) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)', (userid, username, username, password, perms, last_login, 1))
        self.action('INSERT into readinglists (UserID, BookID, Status) VALUES (?, ?, ?)', (userid, 'b' + userid, 1))

    def migrate(self):
        db = DBConnection()
        try:
            dbupgrade.update_schema(db, mock.Mock())
        finally:
            db.close()
        return [dict(u) for u in self.query('SELECT * from users')]

    def test_most_recent_admin_becomes_owner(self):
        self.cfg['USER_ACCOUNTS'] = True
        self.add_user('alice00001', 'alice', 65535, '100')
        self.add_user('bob0000001', 'bob', 65535, '200', password='bobhash')
        self.add_user('carol00001', 'carol', lazylibrarian.perm_friend, '300')
        users = self.migrate()
        self.assertEqual([u['UserName'] for u in users], ['bob'])
        self.assertEqual(users[0]['Password'], 'bobhash', 'Existing hash is kept, upgraded at next login')
        self.assertEqual(auth.owner_id(), 'bob0000001')
        lists = self.query('SELECT UserID from readinglists')
        self.assertEqual([r['UserID'] for r in lists], ['bob0000001'])
        self.assertFalse(self.cfg['USER_ACCOUNTS'])
        self.cfg.save_config_and_backup_old.assert_called_once()

    def test_config_login_moves_to_owner(self):
        self.cfg.update(HTTP_USER='dave', HTTP_PASS='secret pass')
        self.add_user('admin00001', 'admin', 65535, '')
        users = self.migrate()
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['UserID'], 'admin00001', 'Keeps the reading lists of the old admin entry')
        self.assertEqual(users[0]['UserName'], 'dave')
        self.assertTrue(passwords.verify_password('secret pass', users[0]['Password']))
        self.assertEqual(self.cfg['HTTP_PASS'], '', 'Plain text password removed from the config')
        self.cfg.save_config_and_backup_old.assert_called_once()

    def test_config_login_prefers_matching_user(self):
        self.cfg.update(HTTP_USER='dave', HTTP_PASS='secret pass')
        self.add_user('admin00001', 'admin', 65535, '500')
        self.add_user('dave000001', 'dave', 65535, '100')
        users = self.migrate()
        self.assertEqual([u['UserID'] for u in users], ['dave000001'])

    def test_no_login_configured(self):
        self.add_user('admin00001', 'admin', 65535, '', password=passwords.hash_password('admin'))
        users = self.migrate()
        self.assertEqual(len(users), 1)
        self.assertEqual((users[0]['UserName'], users[0]['Password']), ('', ''),
                         'The never used default admin/admin login must not start working')
        self.cfg.save_config_and_backup_old.assert_not_called()

    def test_empty_users_table(self):
        self.cfg['USER_ACCOUNTS'] = True
        users = self.migrate()
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['Perms'], lazylibrarian.perm_admin)

    def test_runs_once(self):
        self.add_user('admin00001', 'admin', 65535, '')
        self.migrate()
        self.add_user('extra00001', 'extra', 65535, '999')
        users = self.migrate()
        self.assertEqual(len(users), 2, 'Second run does nothing, the sessions table exists')


class SetupTest(AuthDBTestCase):

    def setup(self, ip='192.168.1.20', method='POST', **kwargs):
        form = {'auth_method': 'FORM', 'auth_required': 'ENABLED', 'username': 'reader',
                'password': 'correcthorse', 'password2': 'correcthorse', 'from_page': '/books'}
        form.update(kwargs)
        self.use_request(ip=ip, method=method)
        self.cfg.save_config_and_backup_old.reset_mock()
        with mock.patch.object(auth.AuthController, 'render', return_value='page') as render:
            try:
                auth.AuthController().setup(**form)
            except cherrypy.HTTPRedirect as redirect:
                return redirect, render
        return None, render

    @staticmethod
    def owner():
        db = DBConnection()
        try:
            return auth.get_owner(db)
        finally:
            db.close()

    def test_forms_setup(self):
        redirect, _ = self.setup(auth_required='DISABLED_LOCAL')
        self.assertTrue(redirect.urls[0].endswith('/books'))
        owner = self.owner()
        self.assertEqual(owner['UserName'], 'reader')
        self.assertTrue(passwords.verify_password('correcthorse', owner['Password']))
        self.assertEqual((self.cfg['AUTH_TYPE'], self.cfg['AUTH_REQUIRED']), ('FORM', 'DISABLED_LOCAL'))
        self.cfg.save_config_and_backup_old.assert_called_once()
        token = cherrypy.response.cookie[sessions.SESSION_COOKIE].value
        db = DBConnection()
        try:
            self.assertIsNotNone(sessions.lookup_session(db, token), 'Logged in straight after setup')
        finally:
            db.close()

    def test_basic_setup_has_no_session(self):
        redirect, _ = self.setup(auth_method='BASIC')
        self.assertIsNotNone(redirect)
        self.assertEqual(self.cfg['AUTH_TYPE'], 'BASIC')
        self.assertNotIn(sessions.SESSION_COOKIE, cherrypy.response.cookie)

    def test_get_shows_form(self):
        redirect, render = self.setup(method='GET')
        self.assertIsNone(redirect)
        self.assertFalse(render.call_args.kwargs['remote'])
        self.assertFalse(auth.credentials_set(self.owner()))

    def test_bad_input(self):
        for changes, expect in [({'password2': 'different1'}, 'do not match'),
                                ({'password': 'short', 'password2': 'short'}, '8 characters'),
                                ({'password': 'has space', 'password2': 'has space'}, '8 characters'),
                                ({'username': ' '}, 'username'), ({'username': 'a:b'}, 'username'),
                                ({'auth_method': 'EXTERNAL'}, 'method'), ({'auth_required': 'NEVER'}, 'method')]:
            redirect, render = self.setup(**changes)
            self.assertIsNone(redirect, changes)
            self.assertIn(expect, render.call_args.kwargs['msg'], changes)
            self.assertFalse(auth.credentials_set(self.owner()), changes)
            self.cfg.save_config_and_backup_old.assert_not_called()

    def test_remote_address_cannot_set_up(self):
        redirect, render = self.setup(ip='8.8.8.8')
        self.assertIsNone(redirect)
        self.assertTrue(render.call_args.kwargs['remote'])
        self.assertFalse(auth.credentials_set(self.owner()))

    def test_whitelisted_remote_address_can_set_up(self):
        self.cfg['WHITELIST'] = '8.8.8.8'
        redirect, _ = self.setup(ip='8.8.8.8')
        self.assertIsNotNone(redirect)
        self.assertTrue(auth.credentials_set(self.owner()))

    def test_cross_site_setup_refused(self):
        self.use_request(ip='192.168.1.20', method='POST', path='/auth/setup',
                         headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'})
        with self.assertRaises(cherrypy.HTTPError) as cm:
            auth.AuthController().setup(username='intruder', password='takeover1', password2='takeover1')
        self.assertEqual(cm.exception.status, 403)
        self.assertFalse(auth.credentials_set(self.owner()), 'A page on another site must not claim the install')

    def test_setup_only_once(self):
        self.setup()
        redirect, _ = self.setup(username='intruder', password='takeover1', password2='takeover1')
        self.assertTrue(redirect.urls[0].endswith('/auth/login'))
        self.assertEqual(self.owner()['UserName'], 'reader')


class CrossSiteTest(AuthDBTestCase):

    def check(self, path='/mark_books_ajax', method='GET', **headers):
        """ Run the cross-site check, return None if allowed, else the redirect or error raised """
        self.use_request(method=method, path=path, headers=headers)
        try:
            auth.check_request_origin()
        except (cherrypy.HTTPRedirect, cherrypy.HTTPError) as err:
            return err
        return None

    def test_same_origin_and_typed_addresses(self):
        for site in ['same-origin', 'none']:
            self.assertIsNone(self.check(**{'Sec-Fetch-Site': site, 'Sec-Fetch-Mode': 'cors'}), site)
            self.assertIsNone(self.check(method='POST', **{'Sec-Fetch-Site': site}), site)

    def test_no_browser_headers_allowed(self):
        # curl, scripts, OPDS readers and very old browsers
        self.assertIsNone(self.check())
        self.assertIsNone(self.check(method='POST'))

    def test_cross_site_background_requests_refused(self):
        for site in ['cross-site', 'same-site']:
            for mode in ['cors', 'no-cors']:
                err = self.check(**{'Sec-Fetch-Site': site, 'Sec-Fetch-Mode': mode})
                self.assertIsInstance(err, cherrypy.HTTPError, (site, mode))
                self.assertEqual(err.status, 403)
            err = self.check(path='/books', **{'Sec-Fetch-Site': site, 'Sec-Fetch-Mode': 'no-cors'})
            self.assertIsInstance(err, cherrypy.HTTPError, 'Even a safe page, when it is not a page load')

    def test_cross_site_form_post_refused(self):
        err = self.check(path='/books', method='POST', **{'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'})
        self.assertIsInstance(err, cherrypy.HTTPError)
        self.assertEqual(err.status, 403)

    def test_links_from_other_sites(self):
        nav = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'}
        for path in ['/', '/home', '/books', '/author_page?authorid=1', '/config']:
            self.assertIsNone(self.check(path=path, **nav), path)
        for path in ['/mark_books_ajax?action=Delete', '/shutdown', '/logout', '/config_update']:
            err = self.check(path=path, **nav)
            self.assertIsInstance(err, cherrypy.HTTPRedirect, path)
            self.assertTrue(err.urls[0].endswith('/home'), path)

    def test_older_browsers_use_origin_or_referer(self):
        self.assertIsNone(self.check(Origin='http://ll.example'))
        self.assertIsNone(self.check(Referer='http://ll.example/books'))
        self.assertIsNone(self.check(Referer='https://LL.Example/books'), 'Scheme and case do not matter')
        self.assertIsNone(self.check(Host='books.lan:5299', Referer='http://books.lan:5299/home'))
        self.assertIsNone(self.check(**{'X-Forwarded-Host': 'books.example.com', 'Origin': 'https://books.example.com'}))
        for headers in [{'Origin': 'https://evil.example'}, {'Referer': 'https://evil.example/page'},
                        {'Origin': 'null'}, {'Origin': 'http://ll.example.evil.example'}]:
            err = self.check(**headers)
            self.assertIsInstance(err, cherrypy.HTTPError, headers)
        # a link click, the Accept header shows it's a page load
        err = self.check(Referer='https://evil.example/', Accept='text/html,application/xhtml+xml')
        self.assertIsInstance(err, cherrypy.HTTPRedirect)
        self.assertIsNone(self.check(path='/books', Referer='https://evil.example/', Accept='text/html'))

    def test_check_auth_refuses_before_any_login_bypass(self):
        self.set_owner()
        self.cfg['WHITELIST'] = '203.0.113.5'
        self.cfg['AUTH_REQUIRED'] = 'DISABLED_LOCAL'
        self.use_request(headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors'})
        with self.assertRaises(cherrypy.HTTPError) as cm:
            auth.check_auth()
        self.assertEqual(cm.exception.status, 403)


class ConfigFixupTest(LLTestCaseWithConfigandDIRS):

    def test_proxy_auth_becomes_external(self):
        cfg = LLConfigHandler(defaults=BASE_DEFAULTS)
        self.assertEqual(cfg.fixup_auth_settings(), 0)
        cfg.set_bool('PROXY_AUTH', True)
        self.assertEqual(cfg.fixup_auth_settings(), 1)
        self.assertEqual(cfg.get_str('AUTH_TYPE'), 'EXTERNAL')
        self.assertFalse(cfg.get_bool('PROXY_AUTH'))

    def test_unknown_values_reset(self):
        cfg = LLConfigHandler(defaults=BASE_DEFAULTS)
        cfg.set_str('AUTH_TYPE', 'NONE')
        cfg.set_str('AUTH_REQUIRED', 'SOMETIMES')
        self.assertEqual(cfg.fixup_auth_settings(), 2)
        self.assertEqual((cfg.get_str('AUTH_TYPE'), cfg.get_str('AUTH_REQUIRED')), ('FORM', 'ENABLED'))
