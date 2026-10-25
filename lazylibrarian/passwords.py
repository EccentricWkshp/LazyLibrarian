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
#   Salted password hashing. Hashes are stored as
#   pbkdf2_sha256$<iterations>$<salt>$<hash> (salt and hash base64 encoded),
#   the same layout django uses. Older databases hold unsalted md5 hex digests,
#   these still verify but need_rehash() reports them so callers can upgrade
#   the stored hash once they know the password.

import base64
import hashlib
import hmac
import re
import secrets

ALGORITHM = 'pbkdf2_sha256'
# OWASP 2023 recommendation for PBKDF2-HMAC-SHA256
ITERATIONS = 600_000
SALT_BYTES = 16

_MD5_HEX = re.compile('^[0-9a-f]{32}$')


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def hash_password(password: str, iterations: int = 0) -> str:
    """ Return a salted hash of password, suitable for storing """
    iterations = iterations or ITERATIONS
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _pbkdf2(password, salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def is_legacy_hash(stored: str) -> bool:
    """ True if stored is an old unsalted md5 hex digest """
    return bool(stored) and bool(_MD5_HEX.match(stored))


def verify_password(password: str, stored: str) -> bool:
    """ Check password against a stored hash, in constant time """
    if not password or not stored:
        return False
    if is_legacy_hash(stored):
        legacy = hashlib.md5(password.encode('utf-8')).hexdigest()
        return hmac.compare_digest(legacy, stored)
    try:
        algorithm, iterations, salt, digest = stored.split('$')
        if algorithm != ALGORITHM:
            return False
        expected = base64.b64decode(digest)
        actual = _pbkdf2(password, base64.b64decode(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def need_rehash(stored: str) -> bool:
    """ True if stored should be replaced with a fresh hash after a successful verify """
    if is_legacy_hash(stored):
        return True
    try:
        algorithm, iterations, _, _ = stored.split('$')
        return algorithm != ALGORITHM or int(iterations) < ITERATIONS
    except (ValueError, AttributeError):
        return True
