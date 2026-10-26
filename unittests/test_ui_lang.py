#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the owner account UI language handling in the web interface

import contextlib
from http.cookies import SimpleCookie
from unittest import mock

import cherrypy

from lazylibrarian import webServe
from lazylibrarian.auth import reset_owner_cache
from lazylibrarian.database import DBConnection
from lazylibrarian.dbupgrade import db_upgrade, upgrade_needed
from lazylibrarian.filesystem import DIRS, remove_file
from lazylibrarian.services import users
from lazylibrarian.web import common
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


class FakeRequest:
    def __init__(self, cookies: dict):
        self.cookie = SimpleCookie()
        for key, value in cookies.items():
            self.cookie[key] = value
        self.headers = {}


class FakeResponse:
    def __init__(self):
        self.cookie = SimpleCookie()


class UILangTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        self.addCleanup(setattr, DIRS, 'DBFILENAME', DIRS.DBFILENAME)
        DIRS.DBFILENAME = "test-uilang.db"
        with contextlib.suppress(FileNotFoundError):
            remove_file(DIRS.get_dbfile())
        db_upgrade(upgrade_needed(), restartjobs=False)
        db = DBConnection()
        try:
            # a new database has just the owner account. ui_lang left NULL, as it is for
            # every user that existed before the column was added
            db.action("UPDATE users SET UserID='u1', UserName='alice', Name='Alice', Password='', Email='', "
                      "SendTo='', BookType='epub', Theme='', hc_token='', Perms=65535, Prefs=0, Login_Count=0")
        finally:
            db.close()
        reset_owner_cache()
        self.request = FakeRequest({})
        self.response = FakeResponse()
        patches = [mock.patch.object(cherrypy, 'request', self.request),
                   mock.patch.object(cherrypy, 'response', self.response)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        remove_file(DIRS.get_dbfile())

    @staticmethod
    def user_field(field: str):
        db = DBConnection()
        try:
            return db.match(f'SELECT {field} from users where UserID=?', ('u1',))[field]
        finally:
            db.close()

    @staticmethod
    def profile_save(**changes) -> str:
        # the same fields profile.html sends, which doesn't include ui_lang
        kwargs = {'username': 'alice', 'fullname': 'Alice', 'password': '', 'password2': '',
                  'email': '', 'sendto': '', 'booktype': 'epub', 'theme': '', 'hc_token': ''}
        kwargs.update(changes)
        return webServe.WebInterface().user_update(**kwargs)

    def test_valid_ui_lang(self):
        self.assertTrue(users.valid_ui_lang(''))
        self.assertTrue(users.valid_ui_lang('auto'))
        self.assertFalse(users.valid_ui_lang('None'))
        self.assertFalse(users.valid_ui_lang('xx_YY'))

    def test_profile_save_without_ui_lang(self):
        result = self.profile_save(booktype='mobi', password='newpassword', password2='newpassword')
        self.assertIn('BookType', result)
        self.assertIn('password', result)
        self.assertEqual(self.user_field('BookType'), 'mobi')
        self.assertIsNone(self.user_field('UI_Lang'))

    def test_profile_save_rejects_unknown_ui_lang(self):
        self.assertEqual(self.profile_save(ui_lang='xx_YY'), 'No changes made')
        self.assertIsNone(self.user_field('UI_Lang'))

    def test_profile_save_empty_ui_lang_is_not_a_change(self):
        self.assertEqual(self.profile_save(ui_lang=''), 'No changes made')

    def test_profile_can_set_and_clear_ui_lang(self):
        self.assertIn('UI_Lang', self.profile_save(ui_lang='auto'))
        self.assertEqual(self.user_field('UI_Lang'), 'auto')
        self.assertIn('UI_Lang', self.profile_save(ui_lang=''))
        self.assertEqual(self.user_field('UI_Lang'), '')

    def test_serve_template_sends_owner_ui_lang(self):
        with mock.patch.object(common, 'TemplateLookup') as lookup:
            common.serve_template(templatename='index.html', title='test')
        lookup.return_value.get_template.assert_called_with('index.html')
        self.assertNotIn('ll_uid', self.response.cookie)
        self.assertEqual(self.response.cookie['ll_uilang'].value, '')
