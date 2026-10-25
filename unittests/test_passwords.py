#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test password hashing in passwords.py and the upgrade of old md5 hashes on login

import hashlib
from unittest import mock

from lazylibrarian import auth, passwords
from unittests.unittesthelpers import LLTestCase

# Keep the tests fast, the iteration count is checked separately
FAST = 1000


def md5_hex(txt):
    return hashlib.md5(txt.encode('utf-8')).hexdigest()


class PasswordsTest(LLTestCase):

    def test_hash_round_trip(self):
        stored = passwords.hash_password('correct horse', iterations=FAST)
        self.assertTrue(stored.startswith(f'pbkdf2_sha256${FAST}$'))
        self.assertTrue(passwords.verify_password('correct horse', stored))
        self.assertFalse(passwords.verify_password('wrong horse', stored))

    def test_hash_is_salted(self):
        first = passwords.hash_password('same', iterations=FAST)
        second = passwords.hash_password('same', iterations=FAST)
        self.assertNotEqual(first, second)
        self.assertTrue(passwords.verify_password('same', first))
        self.assertTrue(passwords.verify_password('same', second))

    def test_default_iterations(self):
        self.assertGreaterEqual(passwords.ITERATIONS, 600_000)
        stored = passwords.hash_password('pw')
        self.assertFalse(passwords.need_rehash(stored))

    def test_unicode_password(self):
        stored = passwords.hash_password('Marie Kondō', iterations=FAST)
        self.assertTrue(passwords.verify_password('Marie Kondō', stored))
        self.assertFalse(passwords.verify_password('Marie Kondo', stored))

    def test_legacy_md5(self):
        stored = md5_hex('admin')
        self.assertTrue(passwords.is_legacy_hash(stored))
        self.assertTrue(passwords.verify_password('admin', stored))
        self.assertFalse(passwords.verify_password('Admin', stored))
        self.assertTrue(passwords.need_rehash(stored))

    def test_need_rehash(self):
        self.assertTrue(passwords.need_rehash(passwords.hash_password('pw', iterations=FAST)))
        self.assertTrue(passwords.need_rehash('sha1$1$abc$def'))
        self.assertTrue(passwords.need_rehash('garbage'))
        self.assertTrue(passwords.need_rehash(''))

    def test_bad_input_does_not_verify(self):
        for stored in ['', 'garbage', 'pbkdf2_sha256$x$y$z', 'pbkdf2_sha256$1000$!!$!!', 'sha1$1000$abc$def',
                       'pbkdf2_sha256$1000$abc', None]:
            self.assertFalse(passwords.verify_password('pw', stored), f'Expected {stored} to fail')
        self.assertFalse(passwords.verify_password('', md5_hex('')))
        self.assertFalse(passwords.verify_password(None, md5_hex('pw')))


class CheckUserPasswordTest(LLTestCase):

    def _db(self, stored):
        db = mock.Mock()
        db.match.return_value = {'UserID': 'uid1', 'UserName': 'reader', 'Password': stored}
        return db

    def test_legacy_hash_is_upgraded(self):
        db = self._db(md5_hex('secret'))
        with mock.patch.object(passwords, 'ITERATIONS', FAST):
            res = auth.check_user_password(db, 'reader', 'secret')
        self.assertEqual(res['UserID'], 'uid1')
        db.action.assert_called_once()
        sql, (new_hash, userid) = db.action.call_args.args
        self.assertIn('UPDATE users SET Password', sql)
        self.assertEqual(userid, 'uid1')
        self.assertFalse(passwords.is_legacy_hash(new_hash))
        self.assertTrue(passwords.verify_password('secret', new_hash))

    def test_current_hash_is_left_alone(self):
        with mock.patch.object(passwords, 'ITERATIONS', FAST):
            db = self._db(passwords.hash_password('secret'))
            res = auth.check_user_password(db, 'reader', 'secret')
        self.assertIsNotNone(res)
        db.action.assert_not_called()

    def test_wrong_password(self):
        db = self._db(md5_hex('secret'))
        self.assertIsNone(auth.check_user_password(db, 'reader', 'not it'))
        db.action.assert_not_called()

    def test_unknown_user(self):
        db = mock.Mock()
        db.match.return_value = None
        self.assertIsNone(auth.check_user_password(db, 'nobody', 'secret'))
        db.action.assert_not_called()
