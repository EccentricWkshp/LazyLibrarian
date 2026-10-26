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

""" Testing the connections the settings page sets up: providers, sync accounts, notifiers, download
    clients and tools. Each test first stores the settings it was given, and saves that section of
    the config file if the test passes """

import logging
import os
import subprocess

from deluge_client import DelugeRPCClient

import lazylibrarian
from lazylibrarian import (
    deluge,
    grsync,
    hc,
    notifiers,
    nzbget,
    qbittorrent,
    rtorrent,
    sabnzbd,
    synology,
    transmission,
    utorrent,
)
from lazylibrarian.calibre import calibre_test
from lazylibrarian.common import run_script
from lazylibrarian.config2 import CONFIG, wishlist_type
from lazylibrarian.configdefs import CATEGORY_SUFFIXES
from lazylibrarian.dlcategories import category_setting, download_category
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import check_int, make_unicode, now
from lazylibrarian.providers import test_provider as provider_test
from lazylibrarian.services import InvalidRequestError, ServiceError
from lazylibrarian.services.users import plain_text

TEXT = ('<', '>', '=')


def category_fields(field: str, setting: str) -> dict:
    """ A client's category settings, one per media type, as the test buttons send them:
    field for eBooks, then field_audio, field_mag and field_comic """
    return {f"{field}{suffix.lower()}": (f"{setting}{suffix}", 'text') for suffix in CATEGORY_SUFFIXES.values()}


# the settings each test can be given, by name, in the order they're checked:
# (setting, kind) where kind is text (checked for TEXT), int, checked_int (checked, then a number) or
# the value that means True for a switch
FIELDS = {
    'goodreads': {'gr_api': ('GR_API', 'text'), 'gr_secret': ('GR_SECRET', 'text'),
                  'gr_oauth_token': ('GR_OAUTH_TOKEN', 'text'), 'gr_oauth_secret': ('GR_OAUTH_SECRET', 'text')},
    'pushbullet': {'token': ('PUSHBULLET_TOKEN', 'loose'), 'device': ('PUSHBULLET_DEVICEID', 'loose')},
    'pushover': {'apitoken': ('PUSHOVER_APITOKEN', 'text'), 'keys': ('PUSHOVER_KEYS', 'text'),
                 'priority': ('PUSHOVER_PRIORITY', 'pushover_priority'), 'device': ('PUSHOVER_DEVICE', 'text')},
    'telegram': {'token': ('TELEGRAM_TOKEN', 'text'), 'userid': ('TELEGRAM_USERID', 'text')},
    'prowl': {'apikey': ('PROWL_APIKEY', 'text'), 'priority': ('PROWL_PRIORITY', 'checked_int')},
    'slack': {'token': ('SLACK_TOKEN', 'text'), 'url': ('SLACK_URL', 'text')},
    'custom': {'script': ('CUSTOM_SCRIPT', 'text')},
    'email': {'tls': ('EMAIL_TLS', 'True'), 'ssl': ('EMAIL_SSL', 'True'),
              'sendfile': ('EMAIL_SENDFILE_ONDOWNLOAD', 'True'), 'emailfrom': ('EMAIL_FROM', 'text'),
              'emailto': ('EMAIL_TO', 'text'), 'server': ('EMAIL_SMTP_SERVER', 'text'),
              'user': ('EMAIL_SMTP_USER', 'text'), 'port': ('EMAIL_SMTP_PORT', 'checked_int')},
    'deluge': {'host': ('DELUGE_HOST', 'text'), 'base': ('DELUGE_BASE', 'text'), 'cert': ('DELUGE_CERT', 'text'),
               'port': ('DELUGE_PORT', 'int'), **category_fields('label', 'DELUGE_LABEL'),
               'user': ('DELUGE_USER', 'text')},
    'sabnzbd': {'host': ('SAB_HOST', 'text'), 'port': ('SAB_PORT', 'int'), 'user': ('SAB_USER', 'text'),
                'api': ('SAB_API', 'text'), **category_fields('cat', 'SAB_CAT'), 'subdir': ('SAB_SUBDIR', 'text')},
    'nzbget': {'host': ('NZBGET_HOST', 'text'), 'port': ('NZBGET_PORT', 'int'), 'user': ('NZBGET_USER', 'text'),
               **category_fields('cat', 'NZBGET_CATEGORY'), 'pri': ('NZBGET_PRIORITY', 'int')},
    'transmission': {'host': ('TRANSMISSION_HOST', 'text'), 'base': ('TRANSMISSION_BASE', 'text'),
                     'port': ('TRANSMISSION_PORT', 'int'), 'user': ('TRANSMISSION_USER', 'text')},
    'qbittorrent': {'host': ('QBITTORRENT_HOST', 'text'), 'port': ('QBITTORRENT_PORT', 'int'),
                    'base': ('QBITTORRENT_BASE', 'text'), 'user': ('QBITTORRENT_USER', 'text'),
                    **category_fields('label', 'QBITTORRENT_LABEL'), 'ignore_ssl': ('QBITTORRENT_IGNORE_SSL', '1')},
    'utorrent': {'host': ('UTORRENT_HOST', 'text'), 'port': ('UTORRENT_PORT', 'int'), 'base': ('UTORRENT_BASE', 'text'),
                 'user': ('UTORRENT_USER', 'text'), **category_fields('label', 'UTORRENT_LABEL')},
    'rtorrent': {'host': ('RTORRENT_HOST', 'text'), 'dir': ('RTORRENT_DIR', 'text'), 'user': ('RTORRENT_USER', 'text'),
                 **category_fields('label', 'RTORRENT_LABEL')},
    'synology': {'host': ('SYNOLOGY_HOST', 'text'), 'port': ('SYNOLOGY_PORT', 'int'), 'user': ('SYNOLOGY_USER', 'text'),
                 'dir': ('SYNOLOGY_DIR', 'text')},
}

# the notifiers' modules, config sections and what counts as a successful test
NOTIFIERS = {
    'pushbullet': ('pushbullet_notifier', 'PushBullet', bool),
    'pushover': ('pushover_notifier', 'Pushover', bool),
    'telegram': ('telegram_notifier', 'Telegram', bool),
    'prowl': ('prowl_notifier', 'Prowl', bool),
    'slack': ('slack_notifier', 'Slack', lambda result: result == "ok"),
    'custom': ('custom_notifier', 'Custom', bool),
    'email': ('email_notifier', 'Email', bool),
}

# the download clients' modules and config sections
CLIENTS = {'sabnzbd': (sabnzbd, 'sab_nzbd'), 'nzbget': (nzbget, 'NZBGet'), 'transmission': (transmission, 'TRANSMISSION'),
           'qbittorrent': (qbittorrent, 'QBITTORRENT'), 'utorrent': (utorrent, 'UTORRENT'),
           'rtorrent': (rtorrent, 'RTORRENT'), 'synology': (synology, 'SYNOLOGY')}

# the tools that can be tested, by name: (setting, the name to show)
TOOLS = {'ffmpeg': ('FFMPEG', 'ffmpeg'), 'ebook_convert': ('EBOOK_CONVERT', 'ebook-convert'),
         'calibredb': ('IMP_CALIBREDB', 'calibredb'), 'preprocessor': ('EXT_PREPROCESS', 'preprocessor')}


def apply_settings(test: str, values: dict) -> list[str]:
    """ Store the settings a test was given. Returns the names of the ones left alone as not valid """
    bad = []
    for field, (setting, kind) in FIELDS[test].items():
        if field not in values:
            continue
        value = values[field]
        if kind == 'int':
            CONFIG.set_int(setting, check_int(value, 0))
        elif kind == 'pushover_priority':
            priority = check_int(value, 0, positive=False)
            CONFIG.set_int(setting, priority if -2 <= priority <= 1 else 0)
        elif kind in ('True', '1'):
            CONFIG.set_bool(setting, value == kind)
        elif not plain_text(value, ('<', '>') if kind == 'loose' else TEXT):
            bad.append(field)
        elif kind == 'checked_int':
            CONFIG.set_int(setting, check_int(value, 0))
        else:
            CONFIG.set_str(setting, value)
    return bad


def test_provider(name: str, host: str = '', api: str = '') -> dict:
    """ Search a provider to see if it works. Returns bad (the arguments that aren't valid), result
        (False if it failed, True or what it found if it worked) and name, the provider's name to show """
    bad = [param for param, value, tokens in (('name', name, TEXT), ('host', host, ('<', '>')),
                                               ('api', api, ('<', '>')))
           if not plain_text(value, tokens)]
    if bad:
        return {'bad': bad, 'result': False, 'name': name}
    result, shown = provider_test(name, host=host, api=api)
    if result is not False:
        if result is not True:
            wishtype = wishlist_type(host)
            if wishtype:
                shown = f'Wishlist {wishtype} {shown}'
        CONFIG.save_config_and_backup_old(section=name)
    return {'bad': [], 'result': result, 'name': shown}


def test_hardcover_auth(userid=None, token=None) -> str:
    """ Check a Hardcover account works, returns what Hardcover said ("Pass: whoami=id" if it worked) """
    res = hc.test_auth(userid=userid, token=token)
    return f"Pass: whoami={res}" if str(res).isnumeric() else res


def test_goodreads_auth(values: dict) -> dict:
    """ Check the Goodreads authorisation works. Returns bad (the settings that aren't valid) and result,
        what Goodreads said, starting Pass: if it worked """
    bad = apply_settings('goodreads', values)
    if bad:
        return {'bad': bad, 'result': ''}
    result = grsync.test_auth()
    if result.startswith('Pass:'):
        CONFIG.save_config_and_backup_old(section='API')
    return {'bad': [], 'result': result}


def test_notifier(name: str, values: dict) -> dict:
    """ Send a test notification. Returns bad (the settings that aren't valid), ok and result, what the
        notifier said """
    module, section, worked = NOTIFIERS[name]
    bad = apply_settings(name, values)
    if bad:
        return {'bad': bad, 'ok': False, 'result': ''}
    result = getattr(notifiers, module).test_notify()
    ok = worked(result)
    if ok:
        CONFIG.save_config_and_backup_old(section=section)
    return {'bad': [], 'ok': ok, 'result': result}


def test_client(name: str, values: dict) -> dict:
    """ Check a download client can be reached. Returns bad (the settings that aren't valid), ok and
        message, what the client said """
    module, section = CLIENTS[name]
    bad = apply_settings(name, values)
    if bad:
        return {'bad': bad, 'ok': False, 'message': ''}
    message, ok = module.check_link()
    if ok:
        CONFIG.save_config_and_backup_old(section=section)
    return {'bad': [], 'ok': ok, 'message': message}


def test_deluge(values: dict) -> dict:
    """ Check Deluge can be reached: its web interface without a username, the daemon with one, which
        also checks the labels, one per media type (made lower case, and added if missing). Returns bad
        (the settings that aren't valid), and either error (the exception from the daemon), webui (False
        and the web interface's message if that failed) or daemon (True) with labels (whether the daemon
        has any) and checked: a dict for each label with label, added and error (what adding it said if
        that went wrong) """
    dlcommslogger = logging.getLogger('special.dlcomms')
    bad = apply_settings('deluge', values)
    if bad:
        return {'bad': bad}
    outcome = {'bad': [], 'daemon': False, 'labels': True, 'checked': []}
    try:
        if not CONFIG['DELUGE_USER']:
            # no username, talk to the webui
            msg, ok = deluge.check_link()
            if not ok:
                return {**outcome, 'webui': msg}
        else:
            # if there's a username, talk to the daemon directly, without a cert and with no http:// in the host
            CONFIG.set_str('DELUGE_CERT', '')
            CONFIG.set_str('DELUGE_HOST', CONFIG['DELUGE_HOST'].replace('https://', '').replace('http://', ''))
            client = DelugeRPCClient(CONFIG['DELUGE_HOST'], check_int(CONFIG['DELUGE_PORT'], 0), CONFIG['DELUGE_USER'],
                                     CONFIG['DELUGE_PASS'])
            client.connect()
            outcome['daemon'] = True
            if any(download_category('DELUGE', library) for library in CATEGORY_SUFFIXES):
                labels = client.call('label.get_labels')
                if labels:
                    dlcommslogger.debug(f"Valid labels: {str(labels)}")
                else:
                    outcome['labels'] = False
                known = [make_unicode(s) for s in labels or []]
                for library in CATEGORY_SUFFIXES:
                    # deluge lower cases labels
                    mylabel = download_category('DELUGE', library).lower()
                    if mylabel != download_category('DELUGE', library):
                        CONFIG.set_str(category_setting('DELUGE', library), mylabel)
                    if not mylabel or any(found['label'] == mylabel for found in outcome['checked']):
                        continue
                    found = {'label': mylabel, 'added': False, 'error': ''}
                    if mylabel not in known:
                        res = client.call('label.add', mylabel)
                        if res:
                            found['error'] = str(res)
                        else:
                            found['added'] = True
                            known.append(mylabel)
                    outcome['checked'].append(found)
        # success, save settings
        CONFIG.save_config_and_backup_old(section='DELUGE')
        return {**outcome, 'webui': msg if not CONFIG['DELUGE_USER'] else ''}
    except Exception as e:
        return {**outcome, 'error': e}


def set_tool(tool: str, program: str):
    """ Use this program for a tool, if one is given. InvalidRequestError if it isn't valid """
    if program:
        setting, name = TOOLS[tool]
        if not plain_text(program, TEXT):
            raise InvalidRequestError(name)
        CONFIG.set_str(setting, program)


def test_ffmpeg(program: str = '') -> str:
    """ Which version ffmpeg is, from running it. ServiceError says why it didn't run """
    set_tool('ffmpeg', program)
    ffmpeg = CONFIG['FFMPEG']
    try:
        if logging.getLogger('special.postprocess').isEnabledFor(logging.DEBUG):
            ffmpeg_env = os.environ.copy()
            ffmpeg_env["FFREPORT"] = DIRS.get_logfile(f"ffmpeg-test-{now().replace(':', '-').replace(' ', '-')}.log")
            params = [ffmpeg, "-version", "-report"]
        else:
            params = [ffmpeg, "-version"]
            ffmpeg_env = None
        if os.name != 'nt':
            res = subprocess.check_output(params, preexec_fn=lambda: os.nice(10), stderr=subprocess.STDOUT,
                                          env=ffmpeg_env)
        else:
            res = subprocess.check_output(params, stderr=subprocess.STDOUT, env=ffmpeg_env)
        lazylibrarian.FFMPEGVER = make_unicode(res).strip().split("Copyright")[0].split()[-1]
        return lazylibrarian.FFMPEGVER
    except Exception as e:
        lazylibrarian.FFMPEGVER = None
        raise ServiceError(f'{type(e).__name__} {str(e)}') from e


def test_ebook_convert(program: str = '') -> str:
    """ Which version Calibre's ebook-convert is. ServiceError says why it didn't run """
    set_tool('ebook_convert', program)
    try:
        res = subprocess.check_output([CONFIG['EBOOK_CONVERT'], "--version"], stderr=subprocess.STDOUT)
        return make_unicode(res).strip().split("(")[1].split(")")[0]
    except Exception as e:
        raise ServiceError(f'{type(e).__name__} {str(e)}') from e


def test_calibredb(program: str = '') -> str:
    """ What calibredb said when tried """
    set_tool('calibredb', program)
    return calibre_test()


def test_preprocessor(program: str = '') -> tuple | None:
    """ Run the preprocessor in test mode, returns (return code, output, errors), None if there isn't one """
    set_tool('preprocessor', program)
    if not len(CONFIG['EXT_PREPROCESS']):
        return None
    return run_script([CONFIG['EXT_PREPROCESS'], 'test', ''])
