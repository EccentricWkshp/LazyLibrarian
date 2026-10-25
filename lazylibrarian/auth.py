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
#
# Purpose:
#   Authentication for the web interface. LazyLibrarian has a single owner account,
#   like Sonarr and Radarr, and the same settings:
#     AUTH_TYPE      FORM (login page), BASIC (browser popup) or EXTERNAL (a reverse
#                    proxy logs in and passes the owner username in PROXY_AUTH_USER)
#     AUTH_REQUIRED  ENABLED, or DISABLED_LOCAL to let local addresses in without a login
#   Until a username and password are set up, every page goes to the setup page. That only
#   works from a local or whitelisted address, so nobody can claim an exposed new install.
#   Otherwise a request is let in by (first match wins):
#     - a whitelisted client ip
#     - a local client ip, if AUTH_REQUIRED is DISABLED_LOCAL
#     - EXTERNAL: the proxy header naming the owner
#     - FORM/BASIC: a login session cookie, or an HTTP Basic Authorization header
#   Endpoints opt in with @require_auth(), paths like /api and /opds are switched
#   off in webStart.py as they have their own authentication.

import base64
import binascii
import hashlib
import hmac
import ipaddress
import logging
import threading
import time
from html import escape
from urllib.parse import quote

import cherrypy

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.common import pwd_check, pwd_generator
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import get_list
from lazylibrarian.passwords import hash_password, need_rehash, verify_password
from lazylibrarian.sessions import (
    PERSISTENT_SECONDS,
    SESSION_COOKIE,
    create_session,
    delete_session,
    delete_user_sessions,
    lookup_session,
)

AUTH_FORM = 'FORM'
AUTH_BASIC = 'BASIC'
AUTH_EXTERNAL = 'EXTERNAL'
REQUIRED_ENABLED = 'ENABLED'
REQUIRED_DISABLED_LOCAL = 'DISABLED_LOCAL'

# the same ranges Sonarr treats as local: loopback, private, link local and unique local
LOCAL_NETWORKS = [ipaddress.ip_network(net) for net in (
    '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16',
    '::1/128', 'fc00::/7', 'fe80::/10')]

# failed logins allowed from one address within FAILED_LOGIN_WINDOW seconds
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW = 15 * 60
# verifying a password is deliberately slow, so remember good Basic auth headers for a while
BASIC_CACHE_SECONDS = 5 * 60

_lock = threading.Lock()
_setup_lock = threading.Lock()
_owner_id = ''
_failed_logins = []  # (remote ip, time)
_basic_cache = {}  # sha256 of the Authorization header: expiry time


# Owner account ###################################################################

def owner_id() -> str:
    """ UserID of the owner account. Per-user data (reading lists etc.) belongs to the owner """
    global _owner_id
    if not _owner_id:
        db = database.DBConnection()
        try:
            res = db.match('SELECT UserID from users ORDER BY rowid LIMIT 1')
        finally:
            db.close()
        if res:
            _owner_id = res['UserID']
    return _owner_id


def reset_owner_cache():
    global _owner_id
    _owner_id = ''


class UserRow(dict):
    """ A users row as a dict. Like sqlite3.Row the keys don't care about case,
    which matters as columns added by upgrades are lower case (ui_lang, prefs...) """

    def __init__(self, row):
        super().__init__((key.lower(), row[key]) for key in row.keys())

    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def __contains__(self, key):
        return super().__contains__(key.lower())

    def get(self, key, default=None):
        return super().get(key.lower(), default)


def get_owner(db) -> UserRow | None:
    res = db.match('SELECT * from users ORDER BY rowid LIMIT 1')
    return UserRow(res) if res else None


def ensure_owner(db) -> str:
    """ Make sure the owner row exists, return its UserID. A new owner has no credentials """
    res = db.match('SELECT UserID from users ORDER BY rowid LIMIT 1')
    if res:
        return res['UserID']
    userid = pwd_generator()
    db.action('INSERT into users (UserID, UserName, Name, Password, Perms) VALUES (?, ?, ?, ?, ?)',
              (userid, '', '', '', lazylibrarian.perm_admin))
    reset_owner_cache()
    return userid


def credentials_set(owner: dict | None) -> bool:
    return bool(owner and owner['UserName'] and owner['Password'])


def check_user_password(db, username, password):
    """Return the users row for username if password matches, else None.
    Old style hashes are replaced with a fresh one on success."""
    res = db.match('SELECT * from users where UserName=?', (username,))
    if not res or not verify_password(password, res['Password']):
        return None
    if need_rehash(res['Password']):
        db.action('UPDATE users SET Password=? WHERE UserID=?', (hash_password(password), res['UserID']))
        logging.getLogger(__name__).debug(f"Upgraded password hash for {username}")
    return res


def set_owner_credentials(db, username: str = '', password: str = '', keep_token: str = ''):
    """ Change the owner username and/or password. A new password logs out every other session """
    userid = ensure_owner(db)
    if username:
        db.action('UPDATE users SET UserName=? WHERE UserID=?', (username, userid))
    if password:
        db.action('UPDATE users SET Password=? WHERE UserID=?', (hash_password(password), userid))
        delete_user_sessions(db, userid, keep_token=keep_token)
    with _lock:
        _basic_cache.clear()


# Client address and whitelist ####################################################

def get_remote_ip():
    """Return the client IP used for whitelist checks.

    Only trust X-Forwarded-For when PROXY_LOCAL is configured, which
    means the admin has declared that a reverse proxy sits in front
    of LazyLibrarian.  Without that setting, use the TCP peer address
    so a remote client cannot spoof a local IP via a forged header."""
    if CONFIG.get_str('PROXY_LOCAL'):
        remote_ip = cherrypy.request.headers.get('X-Host')  # lighttpd
        if not remote_ip:
            remote_ip = cherrypy.request.headers.get('X-Forwarded-For')  # apache2 / nginx
        if remote_ip:
            remote_ip = remote_ip.split(',')[0].strip()
            return remote_ip
    return cherrypy.request.remote.ip


def is_whitelisted_ip(remote_ip):
    """True if remote_ip matches an entry in the WHITELIST config.
    Entries may be exact IPs or CIDR ranges (e.g. 10.46.0.0/16), unlike
    the older prefix-matching hack this replaces which only understood
    a single hardcoded /24-shaped string format."""
    whitelist = get_list(CONFIG.get_csv('WHITELIST'))
    if not whitelist or not remote_ip:
        return False
    try:
        addr = ipaddress.ip_address(remote_ip)
    except ValueError:
        return False
    for entry in whitelist:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if '/' in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def is_local_address(remote_ip) -> bool:
    """ True for loopback and private network addresses.
    Behind a reverse proxy every request comes from the proxy, which is usually local,
    so PROXY_LOCAL must be set for this to see the real client address """
    try:
        addr = ipaddress.ip_address(remote_ip)
    except (ValueError, TypeError):
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in net for net in LOCAL_NETWORKS)


def setup_allowed(remote_ip) -> bool:
    """ First-run setup claims the install, so only allow it from the local network """
    return is_local_address(remote_ip) or is_whitelisted_ip(remote_ip)


def auth_type() -> str:
    value = CONFIG.get_str('AUTH_TYPE')
    return value if value in (AUTH_FORM, AUTH_BASIC, AUTH_EXTERNAL) else AUTH_FORM


def local_bypass() -> bool:
    return CONFIG.get_str('AUTH_REQUIRED') == REQUIRED_DISABLED_LOCAL


# Failed login throttling #########################################################

def login_blocked(remote_ip) -> bool:
    limit = time.time() - FAILED_LOGIN_WINDOW
    with _lock:
        _failed_logins[:] = [x for x in _failed_logins if x[1] > limit]
        return sum(1 for x in _failed_logins if x[0] == remote_ip) >= MAX_FAILED_LOGINS


def record_failed_login(remote_ip):
    with _lock:
        _failed_logins.append((remote_ip, time.time()))


def clear_failed_logins(remote_ip):
    with _lock:
        _failed_logins[:] = [x for x in _failed_logins if x[0] != remote_ip]


# Cookies #########################################################################

def cookie_path() -> str:
    return CONFIG['HTTP_ROOT'].rstrip('/') or '/'


def session_token() -> str:
    cookie = cherrypy.request.cookie
    if SESSION_COOKIE in cookie:
        return cookie[SESSION_COOKIE].value
    return ''


def set_session_cookie(token: str, persistent: bool):
    cookie = cherrypy.response.cookie
    cookie[SESSION_COOKIE] = token
    cookie[SESSION_COOKIE]['path'] = cookie_path()
    cookie[SESSION_COOKIE]['httponly'] = True
    cookie[SESSION_COOKIE]['samesite'] = 'Lax'
    if cherrypy.request.base.startswith('https'):
        cookie[SESSION_COOKIE]['secure'] = True
    if persistent:
        cookie[SESSION_COOKIE]['max-age'] = PERSISTENT_SECONDS


def clear_session_cookie():
    cookie = cherrypy.response.cookie
    cookie[SESSION_COOKIE] = ''
    cookie[SESSION_COOKIE]['path'] = cookie_path()
    cookie[SESSION_COOKIE]['max-age'] = 0
    cookie[SESSION_COOKIE]['expires'] = 0


def set_owner_cookies(owner: dict):
    """ Display preferences the pages read client side, not used for authentication """
    cookie = cherrypy.response.cookie
    cookie['ll_prefs'] = owner['Prefs'] or 0
    cookie['ll_prefs']['path'] = '/'
    if owner['UI_Lang']:
        cookie['ll_uilang'] = owner['UI_Lang']
        cookie['ll_uilang']['path'] = '/'


# Request authentication ##########################################################

def _check_basic_header(db, owner, header: str) -> bool:
    if not header.startswith('Basic '):
        return False
    key = hashlib.sha256(header.encode('utf-8')).hexdigest()
    now = time.time()
    with _lock:
        if _basic_cache.get(key, 0) > now:
            return True
    try:
        username, password = base64.b64decode(header[6:]).decode('utf-8').split(':', 1)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    if username != owner['UserName'] or not check_user_password(db, username, password):
        return False
    with _lock:
        _basic_cache[key] = now + BASIC_CACHE_SECONDS
    return True


def _check_proxy_header(owner) -> bool:
    header = CONFIG.get_str('PROXY_AUTH_USER')
    proxy_user = cherrypy.request.headers.get(header, '') if header else ''
    return bool(proxy_user) and hmac.compare_digest(proxy_user.encode('utf-8'), owner['UserName'].encode('utf-8'))


def authenticate_request() -> str:
    """ Return how this request is authenticated, or '' if it isn't.
    Sets cherrypy.request.login to the owner username when it is, and
    cherrypy.request.ll_setup when first-run setup hasn't been done """
    request = cherrypy.request
    remote_ip = get_remote_ip()
    db = database.DBConnection()
    try:
        owner = get_owner(db)
        request.ll_setup = not credentials_set(owner)
        method = ''
        if request.ll_setup:
            pass
        elif is_whitelisted_ip(remote_ip):
            method = 'whitelist'
        elif local_bypass() and is_local_address(remote_ip):
            method = 'local'
        elif auth_type() == AUTH_EXTERNAL:
            if _check_proxy_header(owner):
                method = 'external'
        else:
            found = lookup_session(db, session_token())
            if found and found[0] == owner['UserID']:
                method = 'session'
            elif _check_basic_header(db, owner, request.headers.get('Authorization', '')):
                method = 'basic'
    finally:
        db.close()
    request.ll_auth = method
    request.login = owner['UserName'] if method else None
    return method


def safe_from_page(from_page: str) -> str:
    """ Only redirect back to a page on this server """
    root = CONFIG['HTTP_ROOT'].rstrip('/')
    if not from_page or not from_page.startswith('/') or from_page.startswith('//') or '\\' in from_page:
        return f"{root}/home"
    if root and not from_page.startswith(f"{root}/"):
        from_page = f"{root}{from_page}"
    return from_page


def check_auth(*args, **kwargs):
    """A tool that looks in config for 'auth.require'. If found, and it
    is not None, the request must be authenticated"""
    request = cherrypy.request
    if request.config.get('auth.require', None) is None:
        return
    if authenticate_request():
        return
    page_load = request.method == 'GET' and request.headers.get('X-Requested-With') != 'XMLHttpRequest'
    root = CONFIG['HTTP_ROOT'].rstrip('/')
    get_params = quote(request.request_line.split()[1])
    if request.ll_setup:
        if not page_load:
            raise cherrypy.HTTPError(401, 'Authentication has not been set up')
        raise cherrypy.HTTPRedirect(f"{root}/auth/setup?from_page={get_params}")
    if auth_type() == AUTH_BASIC:
        cherrypy.response.headers['WWW-Authenticate'] = 'Basic realm="LazyLibrarian", charset="UTF-8"'
        raise cherrypy.HTTPError(401)
    if auth_type() == AUTH_EXTERNAL:
        raise cherrypy.HTTPError(401, f"Login is handled by your reverse proxy, which did not send "
                                      f"the {CONFIG.get_str('PROXY_AUTH_USER')} header")
    if not page_load:
        raise cherrypy.HTTPError(401)
    raise cherrypy.HTTPRedirect(f"{root}/auth/login?from_page={get_params}")


cherrypy.tools.auth = cherrypy.Tool('before_handler', check_auth)


def require_auth(*conditions):
    """A decorator that appends conditions to the auth.require config
    variable."""

    # noinspection PyProtectedMember
    def decorate(f):
        if not hasattr(f, '_cp_config'):
            f._cp_config = {}
        if 'auth.require' not in f._cp_config:
            f._cp_config['auth.require'] = []
        f._cp_config['auth.require'].extend(conditions)
        return f
    return decorate


# Controller to provide login and logout actions

def _setup_needed() -> bool:
    db = database.DBConnection()
    try:
        return not credentials_set(get_owner(db))
    finally:
        db.close()


class AuthController:

    @staticmethod
    def render(templatename, title, **kwargs):
        """ The login and setup pages, they stand alone without the rest of the interface """
        from lazylibrarian.webServe import serve_template
        root = CONFIG['HTTP_ROOT'].rstrip('/')
        return serve_template(templatename=templatename, title=title, img=f"{root}/images/ll.png",
                              css=f"{root}/css/ll-auth.css", **kwargs)

    def get_loginform(self, username, msg='', from_page="/"):
        return self.render("formlogin.html", 'Login', username=escape(username, True), msg=msg,
                           from_page=from_page)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    def login(self, current_username=None, current_password=None, remember_me='', from_page="/", **kwargs):
        logger = logging.getLogger(__name__)
        root = CONFIG['HTTP_ROOT'].rstrip('/')
        if _setup_needed():
            raise cherrypy.HTTPRedirect(f"{root}/auth/setup")
        if auth_type() != AUTH_FORM:
            # basic and external logins happen on the page itself
            raise cherrypy.HTTPRedirect(safe_from_page(from_page))
        if cherrypy.request.method != 'POST' or current_username is None or current_password is None:
            return self.get_loginform("", from_page=from_page)
        remote_ip = get_remote_ip()
        if login_blocked(remote_ip):
            logger.warning(f"Login from [{remote_ip}] blocked after too many failed attempts")
            return self.get_loginform(current_username, i18n.gettext(
                'Too many failed attempts, try again later'), from_page)
        db = database.DBConnection()
        try:
            owner = get_owner(db)
            res = None
            if owner and current_username == owner['UserName']:
                res = check_user_password(db, current_username, current_password)
            if not res:
                record_failed_login(remote_ip)
                logger.warning(f"Failed login for [{current_username}] from [{remote_ip}]")
                return self.get_loginform(current_username, i18n.gettext(
                    'Incorrect username or password'), from_page)
            clear_failed_logins(remote_ip)
            persistent = bool(remember_me)
            token = create_session(db, res['UserID'], persistent, remote_ip,
                                   cherrypy.request.headers.get('User-Agent', ''))
            db.action("UPDATE users SET Last_Login=?,Login_Count=? WHERE UserID=?",
                      (str(int(time.time())), int(res['Login_Count'] or 0) + 1, res['UserID']))
            res = UserRow(res)
        finally:
            db.close()
        set_session_cookie(token, persistent)
        set_owner_cookies(res)
        logger.info(f"{current_username} logged in from [{remote_ip}]")
        raise cherrypy.HTTPRedirect(safe_from_page(from_page))

    # noinspection PyUnusedLocal
    @cherrypy.expose
    def setup(self, auth_method=AUTH_FORM, auth_required=REQUIRED_ENABLED, username='', password='',
              password2='', from_page='/', **kwargs):
        """ First run: choose how to log in and create the owner login, like Sonarr's setup dialog """
        logger = logging.getLogger(__name__)
        root = CONFIG['HTTP_ROOT'].rstrip('/')
        remote_ip = get_remote_ip()
        form = {'auth_method': auth_method, 'auth_required': auth_required, 'username': username,
                'from_page': from_page}
        with _setup_lock:
            if not _setup_needed():
                raise cherrypy.HTTPRedirect(f"{root}/auth/login")
            if not setup_allowed(remote_ip):
                logger.warning(f"Refused authentication setup from [{remote_ip}], not a local address")
                return self.render("authsetup.html", 'Setup', msg='', remote=True, remote_ip=remote_ip, **form)
            if cherrypy.request.method != 'POST':
                return self.render("authsetup.html", 'Setup', msg='', remote=False, **form)

            username = username.strip()
            msg = ''
            if auth_method not in (AUTH_FORM, AUTH_BASIC) or \
                    auth_required not in (REQUIRED_ENABLED, REQUIRED_DISABLED_LOCAL):
                msg = i18n.gettext('Choose an authentication method')
            elif not username or any(c in username for c in '<>=:'):
                msg = i18n.gettext('Enter a username, without any of < > = :')
            elif not pwd_check(password):
                msg = i18n.gettext('Password must be at least 8 characters long and not contain spaces')
            elif password != password2:
                msg = i18n.gettext('Passwords do not match')
            if msg:
                return self.render("authsetup.html", 'Setup', msg=msg, remote=False, **form)

            db = database.DBConnection()
            try:
                set_owner_credentials(db, username=username, password=password)
                owner = get_owner(db)
                token = ''
                if auth_method == AUTH_FORM:
                    token = create_session(db, owner['UserID'], False, remote_ip,
                                           cherrypy.request.headers.get('User-Agent', ''))
            finally:
                db.close()
            CONFIG.set_str('AUTH_TYPE', auth_method)
            CONFIG.set_str('AUTH_REQUIRED', auth_required)
            CONFIG.save_config_and_backup_old()
        logger.info(f"Authentication set up from [{remote_ip}]: {auth_method}, required {auth_required}, "
                    f"user [{username}]")
        if token:
            set_session_cookie(token, False)
            set_owner_cookies(owner)
        raise cherrypy.HTTPRedirect(safe_from_page(from_page))

    @cherrypy.expose
    def logout(self, from_page="/"):
        end_session()
        root = CONFIG['HTTP_ROOT'].rstrip('/')
        raise cherrypy.HTTPRedirect(f"{root}/auth/login")


def end_session():
    """ Forget the session this request logged in with """
    token = session_token()
    if token:
        db = database.DBConnection()
        try:
            delete_session(db, token)
        finally:
            db.close()
    clear_session_cookie()
