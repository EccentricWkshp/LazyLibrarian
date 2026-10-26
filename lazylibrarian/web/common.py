#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

""" Helpers shared by the web interface page classes """

import logging
import os
import re
import unicodedata
from shutil import rmtree
from urllib.parse import unquote, unquote_plus

import cherrypy
from mako import exceptions
from mako.lookup import TemplateLookup

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.auth import get_owner
from lazylibrarian.calibre import calibredb, get_calibre_id
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, path_isdir, remove_file, splitext, syspath
from lazylibrarian.formatter import check_int, thread_name
from lazylibrarian.processcontrol import get_info_on_caller

# the author page shown last, so its book list only goes back to page one for a new author
lastauthor = ''


def fold(s):
    s = unicodedata.normalize('NFKD', str(s))
    return ''.join(c for c in s if not unicodedata.combining(c)).casefold()


def clear_mako_cache(userid=0):
    logger = logging.getLogger(__name__)
    if userid:
        logger.warning(f"Clearing mako cache {userid}")
        makocache = os.path.join(DIRS.CACHEDIR, 'mako', str(userid))
    else:
        logger.warning("Clearing mako cache")
        makocache = os.path.join(DIRS.CACHEDIR, 'mako')
    try:
        rmtree(makocache, ignore_errors=True)
        # noinspection PyArgumentList
        os.makedirs(makocache, exist_ok=True)
    except Exception as e:
        logger.error(f"Error clearing mako cache: {str(e)}")


def owner_details() -> dict:
    """ Owner account fields the config page shows, never the password hash """
    db = database.DBConnection()
    try:
        owner = get_owner(db) or {}
    finally:
        db.close()
    return {'username': owner.get('UserName') or '', 'userid': owner.get('UserID') or ''}


def clear_our_cookies():
    cookie = cherrypy.response.cookie
    cookie['ll_uid'] = ''
    cookie['ll_uid']['path'] = '/'
    cookie['ll_uid']['expires'] = 0
    cookie['ll_uid']['max-age'] = 0
    cookie['ll_prefs'] = '0'
    cookie['ll_prefs']['path'] = '/'
    cookie['ll_prefs']['expires'] = 0
    cookie['ll_prefs']['max-age'] = 0
    cookie['ll_uilang'] = ''


def valid_ui_lang(value: str) -> bool:
    """ Empty (use the global setting), auto, or a language we have a translation for """
    return value in ('', i18n.AUTO) or value in i18n.available_languages()


def set_request_language():
    """ Set the UI language for the current request: the user's own setting (cookie),
        then UI_LANGUAGE from the config, which may be 'auto' to follow the browser """
    uilang = ''
    cookie = cherrypy.request.cookie
    if cookie and 'll_uilang' in list(cookie.keys()):
        uilang = cookie['ll_uilang'].value
    if not uilang:
        uilang = CONFIG.get_str('UI_LANGUAGE')
    browserlang = ''
    if cookie and i18n.BROWSER_COOKIE in list(cookie.keys()):
        browserlang = unquote(cookie[i18n.BROWSER_COOKIE].value)
    lang = i18n.resolve_language(uilang, cherrypy.request.headers.get('Accept-Language', ''), browserlang)
    i18n.set_language(lang)
    cherrypy.request.ui_lang_auto = uilang.strip().lower() in ('', i18n.AUTO)
    return lang


def browser_languages() -> list:
    """ Languages the browser asks for, from navigator.languages (browser cookie) and Accept-Language """
    browserlang = ''
    cookie = cherrypy.request.cookie
    if cookie and i18n.BROWSER_COOKIE in list(cookie.keys()):
        browserlang = unquote(cookie[i18n.BROWSER_COOKIE].value)
    return (i18n.parse_accept_language(browserlang)
            + i18n.parse_accept_language(cherrypy.request.headers.get('Accept-Language', '')))


# set the language before every request handler runs, so i18n.gettext() works in python code too
cherrypy.tools.ui_language = cherrypy.Tool('before_handler', set_request_language)


def template_i18n():
    """ Set the UI language for this request and return the translation helpers for templates """
    lang = set_request_language()
    return {'_': i18n.gettext, '_js': i18n.gettext_js, '_jsn': i18n.ngettext_js, 'js': i18n.js_string,
            'ngettext': i18n.ngettext, 'pgettext': i18n.pgettext, 'js_plural': i18n.plural_expression,
            'status_label': i18n.status_label, 'status_labels': i18n.status_labels, 'ui_lang': lang,
            'ui_lang_auto': getattr(cherrypy.request, 'ui_lang_auto', False),
            'ui_langs': i18n.available_languages(), 'ui_lang_cookie': i18n.BROWSER_COOKIE}


def mark_summary(headline, passed, failed):
    """ Translated result summary for the mark_*_ajax handlers, headline is already translated """
    total = passed + failed
    if not total:
        return f"{headline} {i18n.gettext('No items were processed.')}"
    if failed:
        detail = i18n.ngettext('%(passed)s successful, %(failed)s failed out of %(total)s total item.',
                               '%(passed)s successful, %(failed)s failed out of %(total)s total items.', total)
    else:
        detail = i18n.ngettext('%(passed)s successful out of %(total)s total item.',
                               '%(passed)s successful out of %(total)s total items.', total)
    return f"{headline} {detail % {'passed': passed, 'failed': failed, 'total': total}}"


def serve_template(templatename, **kwargs):
    thread_name("WEBSERVER")
    logger = logging.getLogger(__name__)
    adminlogger = logging.getLogger('special.admin')
    i18n_vars = template_i18n()
    kwargs.update(i18n_vars)
    interface_dir = os.path.join(str(DIRS.PROG_DIR), 'data', 'interfaces')
    template_dir = os.path.join(str(interface_dir), CONFIG['HTTP_LOOK'])
    if not path_isdir(template_dir):
        logger.error(f"Unable to locate template [{template_dir}], reverting to bookstrap")
        CONFIG.set_str('HTTP_LOOK', 'bookstrap')
        template_dir = os.path.join(str(interface_dir), CONFIG['HTTP_LOOK'])

    if templatename in ['logs.html', 'history.html']:
        # don't cache these so we can change refresh rate
        module_directory = None
    else:
        module_directory = os.path.join(DIRS.CACHEDIR, 'mako')
    _hplookup = TemplateLookup(directories=[template_dir], input_encoding='utf-8',
                               module_directory=module_directory)
    # noinspection PyBroadException
    try:
        style = CONFIG['BOOKSTRAP_THEME']
        userprefs = 0
        usertheme = ''
        if lazylibrarian.UPDATE_MSG:
            template = _hplookup.get_template("dbupdate.html")
            return template.render(perm=0, message=i18n.gettext("Database upgrade in progress, please wait..."),
                                   title=i18n.gettext("Database Upgrade"), timer=5, style=style, **i18n_vars)

        db = database.DBConnection()
        try:
            owner = get_owner(db) or {}
        finally:
            db.close()
        perm = lazylibrarian.perm_admin
        userid = owner.get('UserID', '')
        usertheme = owner.get('Theme') or ''
        cherrypy.response.cookie['ll_uilang'] = owner.get('UI_Lang') or ''
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        else:
            userprefs = check_int(owner.get('Prefs'), 0)
        adminlogger.debug(f"User: {owner.get('UserName')} Prefs: {userprefs} Theme: {usertheme} "
                          f"Template: {templatename}")

        theme = usertheme.split('_', 1)[0]
        if theme and theme != CONFIG['HTTP_LOOK']:
            template_dir = os.path.join(str(interface_dir), theme)
            if not path_isdir(template_dir):
                logger.error(f"Unable to locate template [{template_dir}], reverting to bookstrap")
                CONFIG.set_str('HTTP_LOOK', 'bookstrap')
                template_dir = os.path.join(str(interface_dir), CONFIG['HTTP_LOOK'])

            module_directory = os.path.join(DIRS.CACHEDIR, 'mako', str(userid))
            _hplookup = TemplateLookup(directories=[template_dir], input_encoding='utf-8',
                                       module_directory=module_directory)
        try:
            template = _hplookup.get_template(templatename)
        except (AttributeError, KeyError):
            clear_mako_cache(userid)
            template = _hplookup.get_template(templatename)

        theme = usertheme.split('_', 1)
        if len(theme) > 1:
            style = theme[1]

        if templatename in ("formlogin.html", "authsetup.html"):
            cherrypy.response.cookie['ll_template'] = ''
            return template.render(perm=0, style=style, **kwargs)

        # keep template name for help context
        cherrypy.response.cookie['ll_template'] = templatename
        showlogout = getattr(cherrypy.request, 'll_auth', '') == 'session'
        return template.render(perm=perm, pref=userprefs, style=style, showlogout=showlogout, **kwargs)

    except Exception:
        return exceptions.html_error_template().render()


# Per-format variants of Have/Skipped/Ignored, mapped to (status, libraries)
FORMAT_STATUS_ACTIONS = {
    'HaveEbook': ('Have', 'eBook'),
    'HaveAudio': ('Have', 'AudioBook'),
    'HaveBoth': ('Have', 'eBook+AudioBook'),
    'SkipEbook': ('Skipped', 'eBook'),
    'SkipAudio': ('Skipped', 'AudioBook'),
    'SkipBoth': ('Skipped', 'eBook+AudioBook'),
    'IgnoreEbook': ('Ignored', 'eBook'),
    'IgnoreAudio': ('Ignored', 'AudioBook'),
    'IgnoreBoth': ('Ignored', 'eBook+AudioBook'),
}


def status_mark_targets(action: str, library: str) -> tuple[str, str] | None:
    """Return (status, libraries) for a Have/Skipped/Ignored mark, or None for any other action.

    The plain actions follow the page's library; the per-format ones name their own.
    """
    if action in FORMAT_STATUS_ACTIONS:
        return FORMAT_STATUS_ACTIONS[action]
    if action in ('Have', 'Skipped', 'Ignored'):
        return action, library or ''
    return None


class BasePages:
    """ Methods the page classes share through self """

    @staticmethod
    def validate_param(keyword, value, tokens, errorpage):
        if not value:
            return True
        unquoted = unquote_plus(value)
        for token in tokens:
            if token in unquoted:
                logger = logging.getLogger(__name__)
                msg = f"Invalid {keyword}: contains {token}"
                logger.warning(msg)
                if errorpage:
                    raise cherrypy.HTTPError({errorpage}, msg)
                return False
        return True

    @staticmethod
    def label_thread(name=None):
        if name:
            thread_name(name)
        else:
            threadname = thread_name()
            if "Thread" in threadname:
                thread_name("WEBSERVER")

    @staticmethod
    def natural_sort(lst, key=lambda s: s, reverse=False):
        """
        Sort the list into natural alphanumeric order.
        """

        def convert(text):
            return int(text) if text and text.isdigit() else text

        def get_alphanum_key_func(skey):
            return lambda s: [convert(c) for c in re.split('([0-9]+)', skey(s))]

        sort_key = get_alphanum_key_func(key)
        lst.sort(key=sort_key, reverse=reverse)

    @staticmethod
    def delete_from_calibre(data):
        logger = logging.getLogger(__name__)
        calibre_id = get_calibre_id(data)
        if calibre_id:
            res, err, rc = calibredb('remove', [calibre_id])
            logger.debug(f"Delete result: {res} [{err}] {rc}")

    def delete_issue(self, issuefile):
        logger = logging.getLogger(__name__)
        try:
            # delete the magazine file and any cover image / opf
            remove_file(issuefile)
            fname, extn = splitext(issuefile)
            for extn in ['.opf', '.jpg']:
                remove_file(fname + extn)
            # if the directory is now empty, delete that too
            if CONFIG.get_bool('MAG_DELFOLDER'):
                parent_dir = syspath(os.path.dirname(issuefile))
                files = os.listdir(parent_dir)
                if not files or (len(files) == 1 and files[0] == '.ll_ignore'):
                    logger.debug(f'Directory {parent_dir} deleted as empty')
                    rmtree(parent_dir)
                else:
                    logger.warning(f'Directory {parent_dir} not deleted as not empty')
                    logger.debug(f"{files}")
            return True
        except Exception as e:
            logger.warning(f'delete issue failed on {issuefile}, {type(e).__name__} {str(e)}')
            return False

    @staticmethod
    def valid_source(source=None):
        if str(source).lower() in ['books', 'audio', 'magazines', 'comics', 'author', 'manage', 'series', 'members']:
            return True
        logger = logging.getLogger(__name__)
        program, method, lineno = get_info_on_caller(depth=1)
        if lineno > 0:
            reason = f"{program}:{method}:{lineno}"
        else:
            reason = 'Unknown reason'
        logger.warning(f'Invalid source:{reason}: [{source}]')
        return False
