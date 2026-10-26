#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/users.py

from unittest import mock

import lazylibrarian
from lazylibrarian.auth import reset_owner_cache
from lazylibrarian.passwords import verify_password
from lazylibrarian.services import InvalidRequestError, NotFoundError, users
from unittests.unittesthelpers import LLTestCaseWithDB


class UserServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.sql("UPDATE users SET UserID='u1', UserName='alice', Name='Alice', Password='', Email='', SendTo='', "
                 "BookType='epub', Theme=NULL, hc_token='', Perms=65535, Prefs=0")
        reset_owner_cache()
        self.addCleanup(reset_owner_cache)

    def user(self):
        return self.sql('SELECT * FROM users')[0]

    def test_send_to(self):
        self.assertEqual(users.send_to('u1'), '')
        self.sql("UPDATE users SET SendTo='k@kindle.com'")
        self.assertEqual(users.send_to('u1'), 'k@kindle.com')
        self.assertEqual(users.send_to(None), '')

    def test_get_profile(self):
        self.sql("INSERT INTO authors (AuthorID,AuthorName) VALUES ('A1','Anne')")
        self.sql("INSERT INTO subscribers (UserID,Type,WantID) VALUES ('u1','author','A1'),('u1','author','gone'),"
                 "('u1','comic','CV2')")
        profile = users.get_profile('u1')
        self.assertEqual(profile['user']['Theme'], '')
        self.assertEqual([s['Name'] for s in profile['subscriptions']], ['Anne', '', ''])
        with self.assertRaises(NotFoundError):
            users.get_profile('nobody')

    def test_update_profile(self):
        changed = users.update_profile('u1', {'fullname': 'Alice B', 'email': 'a@b.com', 'booktype': 'mobi',
                                              'theme': 'Default', 'sendto': 'not an email'})
        self.assertEqual(changed, ['name', 'email', 'Theme', 'BookType'])
        user = self.user()
        self.assertEqual((user['Name'], user['Email'], user['BookType'], user['Theme'], user['SendTo']),
                         ('Alice B', 'a@b.com', 'mobi', '', ''))
        self.assertEqual(users.update_profile('u1', {'fullname': 'Al<ice', 'theme': 'nosuch'}), [])

    def test_update_password(self):
        with self.assertRaises(InvalidRequestError) as cm:
            users.update_profile('u1', {'password': 'abcdefgh1', 'password2': 'other'})
        self.assertEqual(str(cm.exception), users.PASSWORDS_DIFFER)
        with self.assertRaises(InvalidRequestError) as cm:
            users.update_profile('u1', {'password': 'short'})
        self.assertEqual(str(cm.exception), users.PASSWORD_TOO_WEAK)
        self.assertEqual(users.update_profile('u1', {'password': 'abcdefgh1', 'password2': 'abcdefgh1'},
                                              keep_token='tok'), ['password'])
        self.assertTrue(verify_password('abcdefgh1', self.user()['Password']))
        self.assertEqual(users.update_profile('u1', {'password': 'abcdefgh1'}), [], 'Already that password')

    def test_update_username_and_ui_lang(self):
        self.assertEqual(users.update_profile('u1', {'username': 'bob', 'ui_lang': 'auto'}), ['username', 'UI_Lang'])
        self.assertEqual((self.user()['UserName'], self.user()['ui_lang']), ('bob', 'auto'))
        self.assertEqual(users.update_profile('u1', {'username': 'b:ob', 'ui_lang': 'xx_YY'}), [])
        with self.assertRaises(NotFoundError):
            users.update_profile('nobody', {})

    def test_valid_theme(self):
        with mock.patch.object(lazylibrarian, 'BOOKSTRAP_THEMELIST', ['darkly']):
            self.assertTrue(users.valid_theme(''))
            self.assertTrue(users.valid_theme('legacy'))
            self.assertTrue(users.valid_theme('bookstrap_darkly'))
            self.assertFalse(users.valid_theme('bookstrap_nosuch'))

    def test_save_prefs(self):
        users.save_prefs('u1', 12)
        self.assertEqual(self.user()['Prefs'], 12)

    def test_feeds(self):
        self.sql("INSERT INTO subscribers (UserID,Type,WantID) VALUES ('u1','feed','Old')")
        self.assertEqual(users.set_feeds('u1', {'Old': False, 'New': True, 'Gone': False}), 2)
        self.assertEqual(self.sql("SELECT WantID FROM subscribers WHERE Type='feed'"), [{'WantID': 'New'}])
        providers = [{'DISPNAME': 'New', 'HOST': 'goodreads.com/review/list_rss/1'},
                     {'DISPNAME': 'Plain', 'HOST': 'example.com/rss'}]
        with mock.patch.object(users.CONFIG, 'providers', return_value=providers), \
                mock.patch.object(users, 'wishlist_type', side_effect=lambda host: 'goodreads' if 'goodreads' in host
                                  else ''):
            self.assertEqual(users.feed_choices('u1'), [{'name': 'New', 'subscribed': True}])
