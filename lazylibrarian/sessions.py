#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

# Purpose:
#   Server side login sessions. The browser holds a random token, the database
#   only holds its sha256 so a copy of the database can't be used to log in.
#   Sessions slide: each use pushes the expiry out again, but the database row is
#   only rewritten every REFRESH_SECONDS to keep page loads from writing to disk.

import hashlib
import secrets
import time

SESSION_COOKIE = 'll_session'
PERSISTENT_SECONDS = 30 * 24 * 60 * 60  # "remember me"
TRANSIENT_SECONDS = 24 * 60 * 60
REFRESH_SECONDS = 5 * 60


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _lifetime(persistent) -> int:
    return PERSISTENT_SECONDS if persistent else TRANSIENT_SECONDS


def create_session(db, userid: str, persistent: bool, remote_ip: str = '', user_agent: str = '') -> str:
    """ Store a new session for userid and return the token to give to the browser """
    now = int(time.time())
    db.action('DELETE FROM sessions WHERE Expires < ?', (now,))
    token = secrets.token_urlsafe(32)
    db.action('INSERT INTO sessions (TokenHash, UserID, Created, Expires, LastSeen, Persistent, RemoteIP, '
              'UserAgent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
              (_token_hash(token), userid, now, now + _lifetime(persistent), now, int(bool(persistent)),
               remote_ip[:64], user_agent[:200]))
    return token


def lookup_session(db, token: str):
    """ Return (userid, persistent) for a live session token, or None """
    if not token:
        return None
    token_hash = _token_hash(token)
    res = db.match('SELECT UserID, Expires, LastSeen, Persistent FROM sessions WHERE TokenHash=?', (token_hash,))
    if not res:
        return None
    now = int(time.time())
    if res['Expires'] < now:
        db.action('DELETE FROM sessions WHERE TokenHash=?', (token_hash,))
        return None
    if now - res['LastSeen'] > REFRESH_SECONDS:
        db.action('UPDATE sessions SET LastSeen=?, Expires=? WHERE TokenHash=?',
                  (now, now + _lifetime(res['Persistent']), token_hash))
    return res['UserID'], bool(res['Persistent'])


def delete_session(db, token: str):
    if token:
        db.action('DELETE FROM sessions WHERE TokenHash=?', (_token_hash(token),))


def delete_user_sessions(db, userid: str, keep_token: str = ''):
    """ Log userid out everywhere, except the session holding keep_token if given """
    if keep_token:
        db.action('DELETE FROM sessions WHERE UserID=? AND TokenHash!=?', (userid, _token_hash(keep_token)))
    else:
        db.action('DELETE FROM sessions WHERE UserID=?', (userid,))
