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

""" Settings: what the settings page shows and saving it, in parts that work on their own too (the owner
    login, genres, month names, seasons, config values, magazine filters and logging), the info source
    switches, Goodreads authorisation and API keys """

import json
import logging
import os
import secrets
import time
from urllib.parse import unquote_plus

import lazylibrarian
from lazylibrarian import database, grsync, notifiers
from lazylibrarian.auth import (
    AUTH_BASIC,
    AUTH_EXTERNAL,
    AUTH_FORM,
    REQUIRED_DISABLED_LOCAL,
    REQUIRED_ENABLED,
    get_owner,
    set_owner_credentials,
)
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.booklanguages import (
    anna_search_languages,
    country_picker,
    language_picker,
    magazine_language_picker,
    zlib_search_languages,
)
from lazylibrarian.bookrename import name_vars
from lazylibrarian.common import is_valid_email, pwd_check, validate_monthtable
from lazylibrarian.config2 import CONFIG
from lazylibrarian.configdefs import ARRAY_DEFS, configitem_from_default
from lazylibrarian.configtypes import (
    ConfigBool,
    ConfigCSV,
    ConfigEmail,
    ConfigFloat,
    ConfigFolder,
    ConfigInt,
    ConfigPerm,
    ConfigScheduler,
    ConfigStr,
    ConfigURL,
)
from lazylibrarian.csvfile import dump_table, restore_table
from lazylibrarian.dbupgrade import check_db
from lazylibrarian.filesystem import DIRS, listdir, path_isdir, syspath
from lazylibrarian.formatter import (
    DISPLAY_DATE_FORMATS,
    ISSUE_DATE_FORMATS,
    check_int,
    date_format,
    date_format_picker,
    get_list,
    make_unicode,
    plural,
    unaccented,
)
from lazylibrarian.logconfig import LOGCONFIG
from lazylibrarian.providers import get_capabilities
from lazylibrarian.providers import test_provider as provider_test
from lazylibrarian.scheduling import check_running_jobs
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    ServiceError,
    connections,
    remotepaths,
)
from lazylibrarian.services.users import plain_text

# the info sources switched on and off, by their setting, and the name BOOK_API uses for each
SOURCE_SWITCHES = {'OL_API': 'OpenLibrary', 'DNB_API': 'DNB', 'BN_API': 'BN', 'DBK_API': 'DBK', 'RAN_API': 'RanobeDB',
                   'HC_API': 'HardCover'}
# the info sources that need an api key
SOURCE_KEYS = {'GR_API': 'GoodReads', 'GB_API': 'GoogleBooks'}

# the messages saving the settings can give, worded as the translations know them
INVALID_ADMIN_EMAIL = 'Contact email looks invalid, please check'
USERNAME_CHANGED = 'Username changed'
INVALID_USERNAME = 'Invalid username'
PASSWORDS_DIFFER = 'Passwords do not match, password not changed'
PASSWORD_TOO_WEAK = "Password must be at least 8 characters long\nand not contain spaces"
PASSWORD_CHANGED = 'Password changed'
EXTERNAL_NEEDS_HEADER = 'External authentication needs the proxy user header, authentication method not changed'


def export_magazine_filters() -> str:
    """ Save the magazines and their filters to a file in the data folder """
    count = dump_table('magazines', DIRS.DATADIR)
    return f"{count} {plural(count, 'magazine')} exported"


def import_magazine_filters() -> str:
    """ Load the magazines and their filters from the file in the data folder """
    count = restore_table('magazines', DIRS.DATADIR)
    return f"{count} {plural(count, 'magazine')} imported"


def owner_summary() -> dict:
    """ Owner account fields the settings page shows, never the password hash """
    db = database.DBConnection()
    try:
        owner = get_owner(db) or {}
    finally:
        db.close()
    return {'username': owner.get('UserName') or '', 'userid': owner.get('UserID') or ''}


def page_data(browser_languages: list) -> dict:
    """ What the settings page needs besides the settings themselves: the choices for its lists,
        the magazine and comic filters, month names and seasons, the name variables and the owner.
        browser_languages put the browser's languages first in the book language choices """
    logger = logging.getLogger(__name__)
    http_look_dir = os.path.join(DIRS.PROG_DIR, 'data' + os.path.sep + 'interfaces')
    db = database.DBConnection()
    try:
        comics = db.select('SELECT * from comics ORDER by Title COLLATE NOCASE')
        magazines = db.select('SELECT * from magazines ORDER by Title COLLATE NOCASE')
    finally:
        db.close()
    comics_list = [{'Title': mag['Title'], 'Genre': mag['Genre'] or ""} for mag in comics]
    mags_list = [{'Title': mag['Title'], 'Reject': mag['Reject'] or "", 'Regex': mag['Regex'] or "",
                  'Genre': mag['Genre'] or "", 'DateType': mag['DateType'] or "",
                  'CoverPage': check_int(mag['CoverPage'], 1), 'Language': mag['Language'] or CONFIG['PREF_MAGLANG']}
                 for mag in magazines]
    BLOCKHANDLER.check_day()

    months = {}
    try:
        for cnt, itm in enumerate(lazylibrarian.MONTHNAMES[0]):
            months[cnt] = ', '.join(itm)
    except Exception as e:
        logger.error(f"Unable to load monthnames: {e}")
        logger.error(f"{lazylibrarian.MONTHNAMES}")
    seasons = {}
    try:
        for itm, value in lazylibrarian.SEASONS.items():
            seasons[value] = f"{seasons[value]}, {itm}" if value in seasons else itm
    except Exception as e:
        logger.error(f"Unable to load seasons: {e}")
        logger.error(f"{lazylibrarian.SEASONS}")

    return {
        "remote_path_mappings": remotepaths.mappings(),
        "client_hosts": remotepaths.client_hosts(),
        "http_look_list": [name for name in listdir(http_look_dir) if path_isdir(os.path.join(http_look_dir, name))],
        "apprise_list": lazylibrarian.notifiers.apprise_notify.AppriseNotifier.notify_types(),
        "status_list": ['Skipped', 'Wanted', 'Have', 'Ignored'],
        "magazines_list": mags_list,
        "comics_list": comics_list,
        "namevars": {itm: value.replace(' ', '&nbsp;') for itm, value in name_vars('test').items()},
        "seasons": seasons,
        "months": months,
        "book_languages": language_picker(CONFIG['IMP_PREFLANG'], browser_languages),
        "gb_countries": country_picker(CONFIG['GB_COUNTRY']),
        "mag_languages": magazine_language_picker(CONFIG['PREF_MAGLANG']),
        "author_date_formats": date_format_picker(CONFIG['AUTHOR_DATE_FORMAT'], DISPLAY_DATE_FORMATS,
                                                  CONFIG['DATE_LANG']),
        "date_formats": date_format_picker(CONFIG['DATE_FORMAT'], DISPLAY_DATE_FORMATS, CONFIG['DATE_LANG']),
        "iss_formats": date_format_picker(CONFIG['ISS_FORMAT'], ISSUE_DATE_FORMATS, CONFIG['DATE_LANG']),
        "anna_auto": anna_search_languages('', CONFIG['IMP_PREFLANG']),
        "zlib_auto": zlib_search_languages('', CONFIG['IMP_PREFLANG']),
        "updated": time.ctime(CONFIG.get_int('GIT_UPDATED')),
        "owner": owner_summary(),
    }


def update_owner_login(username: str = '', password: str = '', password2: str = '', keep_token=None) -> list[str]:
    """ Change the owner's username and/or password (keep_token stays logged in, every other session is
        logged out). Returns what happened, worded as the translations know it """
    messages = []
    db = database.DBConnection()
    try:
        owner = get_owner(db) or {}
        if username and username != owner.get('UserName'):
            if plain_text(username, ['<', '>', '=', ':']):
                set_owner_credentials(db, username=username)
                messages.append(USERNAME_CHANGED)
            else:
                messages.append(INVALID_USERNAME)
        if password or password2:
            if password != password2:
                messages.append(PASSWORDS_DIFFER)
            elif not pwd_check(password):
                messages.append(PASSWORD_TOO_WEAK)
            else:
                set_owner_credentials(db, password=password, keep_token=keep_token)
                messages.append(PASSWORD_CHANGED)
    finally:
        db.close()
    return messages


def check_auth_settings(values: dict) -> list[str]:
    """ Take out authentication settings that can't be used, so the current ones stay.
        Returns why, worded as the translations know it """
    messages = []
    if values.get('auth_type') not in (None, AUTH_FORM, AUTH_BASIC, AUTH_EXTERNAL):
        values.pop('auth_type')
    if values.get('auth_required') not in (None, REQUIRED_ENABLED, REQUIRED_DISABLED_LOCAL):
        values.pop('auth_required')
    if values.get('auth_type') == AUTH_EXTERNAL and not values.get('proxy_auth_user', '').strip():
        values.pop('auth_type')
        messages.append(EXTERNAL_NEEDS_HEADER)
    return messages


def update_genres(limit: int, users: int, excludes: list, exclude_parts: list, replacements: dict) -> str:
    """ Change the genre settings and write genres.json, applying them to the database if anything
        changed. Returns what changed """
    logger = logging.getLogger(__name__)
    genres = lazylibrarian.GRGENRES
    changes = ''
    if genres.get('genreLimit', 10) != limit:
        genres['genreLimit'] = limit
        changes += 'limit '
    if genres.get('genreUsers', 10) != users:
        genres['genreUsers'] = users
        changes += 'users '
    if sorted(genres.get('genreExclude', [])) != sorted(excludes):
        genres['genreExclude'] = sorted(excludes)
        changes += 'excludes '
    if sorted(genres.get('genreExcludeParts', [])) != sorted(exclude_parts):
        genres['genreExcludeParts'] = sorted(exclude_parts)
        changes += 'parts '
    old = genres.get('genreReplace', {})
    if len(old) != len(replacements):
        changes += 'dict-length '
        genres['genreReplace'] = replacements
    elif any(old.get(k) != v for k, v in replacements.items()):
        changes += 'shared-values '
        genres['genreReplace'] = replacements
    if changes:
        logger.debug(f"Genre changes: {changes}")
        logger.debug("Writing out new genres.json")
        newdict = {key: genres[key] for key in ('genreLimit', 'genreUsers', 'genreExclude', 'genreExcludeParts',
                                                'genreReplace')}
        with open(syspath(os.path.join(DIRS.DATADIR, 'genres.json')), 'w') as f:
            json.dump(newdict, f, indent=4)
        logger.debug("Applying genre changes")
        check_db()
    return changes


def update_month_names(months: list) -> bool:
    """ Change the month names, a list of names for each month (the first is the language), and write
        monthnames.json. Returns whether they changed """
    logger = logging.getLogger(__name__)
    if months == lazylibrarian.MONTHNAMES[0]:
        return False
    logger.debug("MONTHNAMES has changed")
    if not validate_monthtable(months):
        logger.debug("New MONTHNAMES is not valid, ignoring")
        return False
    with open(os.path.join(DIRS.DATADIR, 'monthnames.json'), 'w', encoding='utf-8') as f:
        json.dump(months, f, ensure_ascii=False)
    # Create a second copy of the monthnames without accents and lowercased to speed up matching
    cleantable = [[unaccented(itm).lower().strip('.') for itm in lyne] for lyne in months]
    lazylibrarian.MONTHNAMES = [months, cleantable]
    return True


def update_seasons(seasons: dict) -> bool:
    """ Change the season names, by name with their month number, and write seasons.json.
        Returns whether they changed """
    if seasons == lazylibrarian.SEASONS:
        return False
    logging.getLogger(__name__).debug("SEASONS has changed")
    lazylibrarian.SEASONS = seasons.copy()
    with open(os.path.join(DIRS.DATADIR, 'seasons.json'), 'w', encoding='utf-8') as f:
        json.dump(lazylibrarian.SEASONS, f, ensure_ascii=False)
    return True


def clean_setting(key: str, value: str) -> str:
    """ A setting with the characters it can't contain taken out """
    key = key.lower()
    if not value:
        return value
    if key in ['bok_host', 'fallback_proxy', 'proxy_host']:
        tokens = ['<', '>', '"', "'", '+', '(', ')']
    elif key in ['user_agent', 'fmt_series'] or key.endswith(('_folder', '_file')):
        tokens = ['<', '&', '>', '=', '"', "'", '+']
    elif '_pass' in key:
        tokens = []  # passwords can contain any char as they are not displayed
    else:
        tokens = ['<', '&', '>', '=', '"', "'", '+', '(', ')']
    if plain_text(value, tokens):
        return value
    newvalue = unquote_plus(value)
    for token in tokens:
        newvalue = newvalue.replace(token, '')
    logging.getLogger(__name__).warning(f"Invalid Token: Key {key.upper()} changed to {newvalue}")
    return newvalue


def update_settings(values: dict, clear_unsent_switches: bool = True):
    """ Change the settings given (by lower case name). With clear_unsent_switches, the switches the
        settings page showed but didn't send are switched off, as an unticked box isn't sent """
    for key, itm in CONFIG.config.items():
        if key.lower() in values:
            CONFIG.set_from_ui(key, clean_setting(key, values[key.lower()]))
        elif clear_unsent_switches and isinstance(itm, ConfigBool) and itm.get_read_count() > 0:
            itm.set_from_ui(False)  # Set other items to False that we've seen (i.e. are shown)
    CONFIG.ensure_valid_homepage()


def update_magazine_filters(filters: dict) -> int:
    """ Change magazine filters: by title, a dict of any of Reject, Regex, Genre, DateType, CoverPage and
        Language. A magazine whose date type changes between dates and issue numbers forgets its latest
        issue, so issues named the new way are found. Returns how many magazines changed """
    logger = logging.getLogger(__name__)
    count = 0
    db = database.DBConnection()
    try:
        for mag in db.select('SELECT * from magazines'):
            title = mag['Title']
            new = filters.get(title)
            if new is None:
                continue
            new_value_dict = {}
            for field in ('Reject', 'Regex', 'Genre', 'DateType', 'Language'):
                if new.get(field) != mag[field]:
                    new_value_dict[field] = new.get(field)
            new_datetype = new.get('DateType')
            if 'DateType' in new_value_dict and (('I' in new_datetype and '-' in mag['IssueDate']) or
                                                 (new_datetype and 'I' not in new_datetype and mag['IssueDate']
                                                  and mag['IssueDate'].isdigit())):
                new_value_dict['IssueDate'] = ''
                logger.debug(f"Reset IssueDate for {mag['Title']} as datestyle changed to {new_datetype}")
            new_coverpage = check_int(new.get('CoverPage'), 1)
            if new_coverpage != check_int(mag['CoverPage'], 1):
                new_value_dict['CoverPage'] = new_coverpage
            if new_value_dict:
                count += 1
                db.upsert("magazines", new_value_dict, {'Title': title})
    finally:
        db.close()
    if count:
        logger.info(f"Magazine {count} filters updated")
    return count


def update_logging(level: int, specials: list):
    """ Set the log level and the special debug logs that are on """
    specialcsv = ','.join(specials)
    LOGCONFIG.enable_only_these_special_debuglogs(specialcsv)
    CONFIG.set_csv('LOGSPECIALDEBUG', specialcsv)
    # Store this in CONFIG so it's persisted. OnChange triggers event to activate.
    CONFIG.set_int('LOGLEVEL', level)


def save_config():
    """ Write the config file, keeping a backup of the old one, and restart the jobs whose settings changed """
    CONFIG.save_config_and_backup_old(restart_jobs=True)
    if not lazylibrarian.STOPTHREADS:
        check_running_jobs()


def log_level_from_form(form: dict) -> int:
    """ The log level the settings page chose, Quiet, Normal or Debug, or a level number from older pages """
    levels = {'Quiet': logging.CRITICAL, 'Normal': logging.INFO, 'Debug': logging.DEBUG}
    logtype = form.get('log_type', '')
    return levels[logtype] if logtype in levels else int(form.get('loglevel', logging.INFO))


def save_form(form: dict, keep_token=None) -> list[str]:
    """ Save the settings page's form, its field names are config.html's. Returns any messages for the
        user, worded as the translations know them """
    messages = []
    if form.get('admin_email') and not is_valid_email(form['admin_email']):
        messages.append(INVALID_ADMIN_EMAIL)
    # the owner login is stored hashed in the users table, not in the config file
    messages += update_owner_login(form.pop('owner_username', '').strip(), form.pop('owner_password', ''),
                                   form.pop('owner_password2', ''), keep_token=keep_token)
    # unknown values would leave update_settings to store them, keep the current ones
    messages += check_auth_settings(form)
    messages += update_remote_path_mappings(form)

    replacements = {}
    for itm in form:
        if itm.startswith('genrereplace['):
            value = make_unicode(form.get(itm, ''))
            if value:
                replacements[make_unicode(itm.split('[')[1].split(']')[0])] = value
    if form.get('genrenew') and form.get('genreold'):
        replacements[make_unicode(form['genreold'])] = make_unicode(form['genrenew'])
    update_genres(check_int(form.get('genrelimit', 0), 0), check_int(form.get('genreusers', 0), 0),
                  get_list(form.get('genreexclude', ''), ','), get_list(form.get('genreexcludeparts', ''), ','),
                  replacements)

    update_month_names([get_list(form[f"month_{n}"], ',') for n in range(13) if form.get(f"month_{n}")])
    seasons = {}
    for key in form:
        if key.startswith('season_'):
            for itm in get_list(form[key]):
                seasons[itm] = check_int(key.split('_')[1], 0)
    update_seasons(seasons)

    update_settings(form)

    filters = {}
    db = database.DBConnection()
    try:
        titles = [m['Title'] for m in db.select('SELECT Title from magazines')]
    finally:
        db.close()
    for title in titles:
        filters[title] = {'Reject': form.get(f'reject_list[{title}]'), 'Regex': form.get(f'regex[{title}]'),
                          'Genre': form.get(f'genre_list[{title}]'), 'DateType': form.get(f'datetype[{title}]'),
                          'CoverPage': form.get(f"coverpage[{title}]"), 'Language': form.get(f'language[{title}]')}
    update_magazine_filters(filters)

    CONFIG.update_providers_from_ui(form)
    specials = [LOGCONFIG.get_short_special_logger_name(logger.name) for logger in LOGCONFIG.get_special_logger_list()
                if f'log_{LOGCONFIG.get_short_special_logger_name(logger.name)}' in form]
    update_logging(log_level_from_form(form), specials)
    save_config()
    return messages


def update_remote_path_mappings(form: dict) -> list[str]:
    """ The settings page's remote path mappings: rpm_host_<id>, rpm_remote_<id> and rpm_local_<id> for
        each, rpm_delete_<id> to remove one, and the same ending in new to add one. Returns any problems,
        worded for the user """
    messages = []
    for mapping in remotepaths.mappings():
        key = mapping['Id']
        if form.get(f'rpm_delete_{key}'):
            remotepaths.delete_mapping(key)
            continue
        values = (form.get(f'rpm_host_{key}', mapping['Host']), form.get(f'rpm_remote_{key}', mapping['RemotePath']),
                  form.get(f'rpm_local_{key}', mapping['LocalPath']))
        if values != (mapping['Host'], mapping['RemotePath'], mapping['LocalPath']):
            try:
                remotepaths.update_mapping(key, *values)
            except InvalidRequestError as e:
                messages.append(str(e))
    new = (form.get('rpm_host_new', ''), form.get('rpm_remote_new', ''), form.get('rpm_local_new', ''))
    if new[1].strip() or new[2].strip():
        try:
            remotepaths.add_mapping(*new)
        except InvalidRequestError as e:
            messages.append(str(e))
    return messages


def set_source(setting: str, value) -> str:
    """ Switch an info source on or off (OL_API, DNB_API, ...) or set its api key (GR_API, GB_API). One
        switched on or given a key becomes BOOK_API, the source searched first. OpenLibrary is switched
        back on if nothing else is left. Returns the value """
    if setting in SOURCE_SWITCHES:
        CONFIG.set_bool(setting, bool(value))
        if value:
            CONFIG.set_str('BOOK_API', SOURCE_SWITCHES[setting])
    elif setting in SOURCE_KEYS:
        if value == MASK:  # a key sent back as it's shown, masked, is kept
            return value
        if not plain_text(value, ['<', '>', '=']):
            raise InvalidRequestError(f"Invalid {setting}")
        CONFIG.set_str(setting, value)
        if value:
            CONFIG.set_str('BOOK_API', SOURCE_KEYS[setting])
    else:
        raise InvalidRequestError(f'Unknown info source setting {setting}')
    if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
            and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
            and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
            and not CONFIG.get_bool('RAN_API')):
        # ensure at least one option is available
        CONFIG.set_bool('OL_API', True)
        CONFIG.set_str('BOOK_API', 'OpenLibrary')
    return value


def set_book_api(source: str) -> str:
    """ Choose the info source searched first """
    CONFIG.set_str('BOOK_API', source)
    return source


def goodreads_auth_start(api_key: str | None = None, secret: str | None = None) -> str:
    """ Start authorising LazyLibrarian with Goodreads, with this api key and secret if given.
        Returns what to tell the user, the link to approve it at """
    for setting, value in (('GR_API', api_key), ('GR_SECRET', secret)):
        if value is not None and value != MASK:
            if not plain_text(value, ['<', '>', '=']):
                raise InvalidRequestError(f"Invalid {setting}")
            CONFIG.set_str(setting, value)
    return grsync.GrAuth().goodreads_oauth1()


def goodreads_auth_finish() -> str:
    """ Finish authorising with Goodreads, switching Goodreads sync on if it worked """
    res = grsync.GrAuth().goodreads_oauth2()
    if "Authorisation complete" in res:
        CONFIG.set_bool('GR_SYNC', True)
    return res


def new_api_key(read_only: bool = False) -> str:
    """ Make a new key for the API, or for read only use of it """
    api_key = secrets.token_hex(16)
    CONFIG.set_str('API_RO_KEY' if read_only else 'API_KEY', api_key)
    logging.getLogger(__name__).info("New API generated")
    return api_key


def set_settings_tab(tab) -> None:
    """ Remember which settings tab was open """
    CONFIG.set_from_ui('CONFIG_TAB_NUM', check_int(tab, 1))


# --- the settings by name, for the new Settings pages

# a secret is never sent back, saving it masked keeps it
MASK = '********'
# the owner's login isn't a setting, it's in the users table
OWNER_FIELDS = ('OWNER_USERNAME', 'OWNER_PASSWORD', 'OWNER_PASSWORD2')
# names that look secret and aren't: switches and a file
NOT_SECRET = ('OL_API', 'DNB_API', 'BN_API', 'DBK_API', 'RAN_API', 'HC_API', 'BOOK_API', 'HTTPS_KEY')
KINDS = ((ConfigScheduler, 'interval'), (ConfigBool, 'bool'), (ConfigPerm, 'perm'), (ConfigFloat, 'float'),
         (ConfigInt, 'int'), (ConfigEmail, 'email'), (ConfigURL, 'url'), (ConfigFolder, 'folder'),
         (ConfigCSV, 'csv'), (ConfigStr, 'str'))
# settings kept outside the config file, in genres.json, monthnames.json and seasons.json, by names of
# their own: (the genres.json name, the kind). A genre replacement is a line of old = new
GENRE_SETTINGS = {'GENRE_LIMIT': ('genreLimit', 'int'), 'GENRE_USERS': ('genreUsers', 'int'),
                  'GENRE_EXCLUDE': ('genreExclude', 'csv'), 'GENRE_EXCLUDE_PARTS': ('genreExcludeParts', 'csv'),
                  'GENRE_REPLACE': ('genreReplace', 'str')}
# MONTH_0 is the languages the month names are in, MONTH_1 to MONTH_12 each month's name in them
MONTH_SETTINGS = tuple(f'MONTH_{n}' for n in range(13))
# the season names in each month, SEASON_1 to SEASON_12
SEASON_SETTINGS = tuple(f'SEASON_{n}' for n in range(1, 13))
# the owner's addresses Send to Device emails to, in the users table
SEND_TO = 'OWNER_SENDTO'
OTHER_SETTINGS = (*GENRE_SETTINGS, *MONTH_SETTINGS, *SEASON_SETTINGS, SEND_TO)
INFO_SOURCES_CHANGED = 'The info source searched first was off, {} is searched first now'
# the special debug logs, by their logger's name
SPECIAL_LOGS = {'matching': 'Name matching', 'searching': 'Search results', 'dlcomms': 'Download clients',
                'dbcomms': 'Database', 'postprocess': 'Importing', 'fuzz': 'Fuzzy matching',
                'serverside': 'Server-side pages', 'fileperms': 'File permissions', 'grsync': 'Reading list sync',
                'cache': 'Caching', 'libsync': 'Library scans', 'admin': 'Admin', 'cherrypy': 'The old web server',
                'requests': 'Web requests', 'configread': 'Settings read', 'configwrite': 'Settings written',
                'iterateproviders': 'Each indexer searched'}


def _kind(item) -> str:
    return next((kind for cls, kind in KINDS if isinstance(item, cls)), 'str')


def _value(item, secret: bool) -> dict:
    """ A setting's kind, value and default, masked if it's a secret. An interval's unit is the unit its
    value is in """
    kind = _kind(item)
    if kind == 'bool':
        value = item.get_bool()
        default = bool(item.get_default())
    elif kind in ('int', 'interval'):
        value, default = item.get_int(), item.get_default()
    elif kind == 'float':
        value, default = item.get_float(), item.get_default()
    else:
        value, default = item.get_str(), str(item.get_default())
        if secret and value:
            value = MASK
    return {'key': item.key, 'kind': kind, 'value': value, 'default': default,
            'unit': item.unit.value if kind == 'interval' else ''}


def _other_value(key: str) -> dict:
    """ A setting kept outside the config file """
    if key in GENRE_SETTINGS:
        name, kind = GENRE_SETTINGS[key]
        value = lazylibrarian.GRGENRES.get(name)
        if kind == 'int':
            value = check_int(value, 10)
        elif kind == 'csv':
            value = ', '.join(value or [])
        else:
            value = '\n'.join(f'{old} = {new}' for old, new in (value or {}).items())
    elif key in MONTH_SETTINGS:
        kind = 'csv'
        months = lazylibrarian.MONTHNAMES[0] if lazylibrarian.MONTHNAMES else []
        number = int(key.split('_')[1])
        value = ', '.join(months[number]) if number < len(months) else ''
    elif key == SEND_TO:
        kind = 'csv'
        db = database.DBConnection()
        try:
            owner = get_owner(db)
        finally:
            db.close()
        value = owner['SendTo'] or '' if owner else ''
    else:
        kind = 'csv'
        number = int(key.split('_')[1])
        value = ', '.join(name for name, month in dict(lazylibrarian.SEASONS or {}).items() if month == number)
    return {'key': key, 'kind': kind, 'value': value, 'default': '', 'unit': ''}


def _save_other_settings(values: dict) -> list[str]:
    """ Save the settings kept outside the config file, taking them out of values. Returns what wasn't
    saved, and why """
    messages = []
    sent = {key: str(values.pop(key) or '') for key in OTHER_SETTINGS if key in values}
    if any(key in sent for key in GENRE_SETTINGS):
        genres = {key: str(sent.get(key, _other_value(key)['value'])) for key in GENRE_SETTINGS}
        replacements = {}
        for line in genres['GENRE_REPLACE'].splitlines():
            old, sep, new = line.partition('=')
            if sep and old.strip() and new.strip():
                replacements[old.strip()] = new.strip()
            elif line.strip():
                messages.append(f"{line.strip()} wasn't added, a replacement is a genre = the genre it becomes")
        update_genres(check_int(genres['GENRE_LIMIT'], 0), check_int(genres['GENRE_USERS'], 0),
                      get_list(genres['GENRE_EXCLUDE'], ','), get_list(genres['GENRE_EXCLUDE_PARTS'], ','),
                      replacements)
    if any(key in sent for key in MONTH_SETTINGS):
        table = [get_list(sent.get(key, _other_value(key)['value']), ',') for key in MONTH_SETTINGS]
        if (not lazylibrarian.MONTHNAMES or table != lazylibrarian.MONTHNAMES[0]) and not update_month_names(table):
            messages.append("The month names weren't changed, every month needs a name in each language")
    if any(key in sent for key in SEASON_SETTINGS):
        seasons = {}
        for key in SEASON_SETTINGS:
            for name in get_list(sent.get(key, _other_value(key)['value']), ','):
                seasons[name] = int(key.split('_')[1])
        update_seasons(seasons)
    if SEND_TO in sent:
        addresses = get_list(sent[SEND_TO], ',')
        wrong = [address for address in addresses if not is_valid_email(address)]
        if wrong:
            messages.append(f"The send to addresses weren't changed, {', '.join(wrong)} isn't an email address")
        else:
            db = database.DBConnection()
            try:
                owner = get_owner(db)
                if owner:
                    db.action('UPDATE users SET SendTo=? WHERE UserID=?', (','.join(addresses), owner['UserID']))
            finally:
                db.close()
    return messages


def is_secret(key: str) -> bool:
    """ A password, key or token, by its name """
    key = key.upper()
    if key in NOT_SECRET:
        return False
    return any(word in key for word in ('PASS', 'TOKEN', 'SECRET')) or key.endswith(('_KEY', 'APIKEY', 'DEVKEY', '_API'))


def _item(key: str):
    item = CONFIG.config.get(key.upper())
    if item is None:
        raise NotFoundError(f'There is no setting {key}')
    return item


def config_values(keys: list[str]) -> list[dict]:
    """ Settings by name: each one's kind, value and default, a secret masked. An interval's unit is
    the unit its value is in """
    found = []
    for key in keys:
        if key.upper() in OWNER_FIELDS:
            owner = owner_summary()
            found.append({'key': key.upper(), 'kind': 'password' if 'PASSWORD' in key.upper() else 'str',
                          'value': owner['username'] if key.upper() == 'OWNER_USERNAME' else '',
                          'default': '', 'unit': ''})
            continue
        if key.upper() in OTHER_SETTINGS:
            found.append(_other_value(key.upper()))
            continue
        item = _item(key)
        found.append(_value(item, is_secret(item.key)))
    return found


def config_choices() -> dict:
    """ The choices of the settings that have a list to choose from """
    def formats(picker: dict) -> list[dict]:
        found = [{'value': entry['format'], 'example': entry['example']} for entry in picker['formats']]
        if picker['other']:
            found.append({'value': picker['other']['format'], 'example': picker['other']['example']})
        return found

    from lazylibrarian import i18n  # noqa: PLC0415, it needs the translations set up
    return {'themes': list(getattr(lazylibrarian, 'BOOKSTRAP_THEMELIST', []) or []),
            'ui_languages': [{'value': 'auto', 'label': 'Automatic (browser language)'}] +
                            [{'value': lang, 'label': f"{i18n.language_name(lang)} ({lang})"}
                             for lang in i18n.available_languages()],
            'author_date_formats': formats(date_format_picker(CONFIG['AUTHOR_DATE_FORMAT'], DISPLAY_DATE_FORMATS,
                                                              CONFIG['DATE_LANG'])),
            'date_formats': formats(date_format_picker(CONFIG['DATE_FORMAT'], DISPLAY_DATE_FORMATS,
                                                       CONFIG['DATE_LANG'])),
            'issue_date_formats': formats(date_format_picker(CONFIG['ISS_FORMAT'], ISSUE_DATE_FORMATS,
                                                             CONFIG['DATE_LANG'])),
            'book_statuses': ['Skipped', 'Wanted', 'Have', 'Ignored'],
            'owner': owner_summary()['username'],
            # a language's value is its codes, every one of them is a preferred language
            'book_languages': [{'value': lang['codes'], 'label': lang['label']}
                               for lang in language_picker(CONFIG['IMP_PREFLANG'], [])['languages']],
            'countries': [{'value': '', 'label': 'Any'}] +
                         [{'value': code, 'label': code} for code in country_picker(CONFIG['GB_COUNTRY'])['countries']],
            'magazine_languages': [{'value': lang['code'], 'label': lang['label']}
                                   for lang in magazine_language_picker(CONFIG['PREF_MAGLANG'])['languages']],
            'date_languages': list(dict.fromkeys(lazylibrarian.MONTHNAMES[0][0])) if lazylibrarian.MONTHNAMES else [],
            'special_logs': sorted(({'value': name, 'label': SPECIAL_LOGS.get(name, name)} for name in
                                    (LOGCONFIG.get_short_special_logger_name(logger.name)
                                     for logger in LOGCONFIG.get_special_logger_list())),
                                   key=lambda log: log['label'])}


def date_formats() -> dict:
    """ The date formats the pages use, and each month's name and short name in DATE_LANG, as the
    old pages' date_format gives them """
    lang = CONFIG['DATE_LANG']
    months = [[date_format(f'2026-{month:02d}-15', name, datelang=lang) for name in ('$B', '$b')]
              for month in range(1, 13)]
    return {'date_format': CONFIG['DATE_FORMAT'], 'author_date_format': CONFIG['AUTHOR_DATE_FORMAT'],
            'issue_date_format': CONFIG['ISS_FORMAT'], 'months': months}


def save_values(values: dict, keep_token=None) -> list[str]:
    """ Change settings by name and save them, as the old settings page does: the owner's login,
    authentication settings that can be used, a contact email that looks like one. A secret sent
    back masked is kept. Returns what to tell the user; a value that can't be used isn't saved """
    values = {key.upper(): value for key, value in values.items()}
    for key in values:
        if key not in OWNER_FIELDS and key not in OTHER_SETTINGS:
            _item(key)
    messages = _set_values(values, keep_token)
    if 'LOGSPECIALDEBUG' in values:
        LOGCONFIG.enable_only_these_special_debuglogs(CONFIG['LOGSPECIALDEBUG'])
    if CONFIG.fixup_info_sources():
        messages.append(INFO_SOURCES_CHANGED.format(CONFIG['BOOK_API']))
    CONFIG.ensure_valid_homepage()
    save_config()
    return messages


def _set_values(values: dict, keep_token=None) -> list[str]:
    """ Change settings by their upper case name, without saving them. Returns what wasn't changed """
    messages = _save_other_settings(values)
    messages += update_owner_login(str(values.pop('OWNER_USERNAME', '') or '').strip(),
                                  str(values.pop('OWNER_PASSWORD', '') or ''),
                                  str(values.pop('OWNER_PASSWORD2', '') or ''), keep_token=keep_token)
    auth = {key.lower(): str(values[key]) for key in ('AUTH_TYPE', 'AUTH_REQUIRED', 'PROXY_AUTH_USER')
            if key in values}
    if 'auth_type' in auth and 'proxy_auth_user' not in auth:
        auth['proxy_auth_user'] = CONFIG['PROXY_AUTH_USER']
    messages += check_auth_settings(auth)
    for key in ('AUTH_TYPE', 'AUTH_REQUIRED'):
        if key in values and key.lower() not in auth:
            values.pop(key)
    if values.get('ADMIN_EMAIL') and not is_valid_email(str(values['ADMIN_EMAIL'])):
        messages.append(INVALID_ADMIN_EMAIL)
        values.pop('ADMIN_EMAIL')
    for key, value in values.items():
        problem = _set_item(_item(key), value, is_secret(key), clean_setting(key, str(value if value is not None else '')))
        if problem:
            messages.append(problem)
    return messages


def _set_item(item, value, secret: bool, text: str) -> str:
    """ Change a setting to value, or to text for one that's not a switch or a number. A secret sent
    back masked is kept. Returns why it wasn't changed, if it wasn't """
    kind = _kind(item)
    if secret and value == MASK:
        return ''
    if kind == 'bool':
        item.set_from_ui(bool(value))
        return ''
    if kind in ('int', 'interval', 'float'):
        try:
            float(value) if kind == 'float' else int(value)
        except (TypeError, ValueError):
            return f"{item.key} wasn't changed, {value} isn't a number"
    item.set_from_ui(text)
    return ''


def reset_values(keys: list[str]):
    """ Put settings back to their defaults and save them, as for a download client or notifier removed """
    for key in keys:
        _item(key).reset_to_default()
    save_config()


# --- the settings kept as lists: indexers, and Apprise notifiers

ARRAYS = ('NEWZNAB', 'TORZNAB', 'RSS', 'IRC', 'GEN', 'APPRISE')
# what an item of a list has that isn't shown or changed: NAME is the item's section, newznab_0
HIDDEN = ('NAME', 'CONNECTION', 'LASTUSED')
# the address an item has to have, and the characters it can't have (newznab and torznab addresses
# can have parameters)
ADDRESS_TOKENS = ('<', '>', '"', "'", '+', '(', ')')


def _array(name: str):
    array = CONFIG.get_array(name.upper()) if name.upper() in ARRAYS else None
    if array is None:
        raise NotFoundError(f'There is no list of settings {name}')
    return array


def _array_item(array, index: int) -> dict:
    config = array[index]
    return {'index': index, 'name': config['NAME'].lower(),
            'values': [_value(item, key == 'API') for key, item in config.items() if key not in HIDDEN]}


def array_schema(name: str) -> list[dict]:
    """ A new item's settings, as their defaults """
    _array(name)
    return [_value(configitem_from_default(item), False) for item in ARRAY_DEFS[name.upper()][2]
            if item.key.upper() not in HIDDEN]


def array_items(name: str) -> list[dict]:
    """ A list's items that are set up, each with its index, its name (newznab_0) and its settings, an
    api key masked """
    array = _array(name)
    return [_array_item(array, index) for index in range(len(array)) if array.is_in_use(index)]


def _set_array_values(name: str, config, values: dict) -> list[str]:
    """ Change an item's settings, without saving them. Returns what wasn't changed """
    messages = []
    primary = ARRAY_DEFS[name.upper()][0]
    for key, value in values.items():
        key = key.upper()
        item = config.get_item(key)
        if item is None or key in HIDDEN:
            raise InvalidRequestError(f'{name} has no setting {key}')
        text = str(value if value is not None else '')
        if key == primary:
            text = unquote_plus(text).strip()
            if any(token in text for token in ADDRESS_TOKENS):
                messages.append(f"{key} wasn't changed, it can't have any of {' '.join(ADDRESS_TOKENS)}")
                continue
        problem = _set_item(item, value, key == 'API', text)
        if problem:
            messages.append(problem)
    return messages


def save_array_item(name: str, values: dict, index: int | None = None) -> dict:
    """ Add an item to a list, or change one, and save it. A newznab or torznab one asks for what it can
    search unless that's locked. Returns the item, and messages: what wasn't changed """
    name = name.upper()
    array = _array(name)
    primary = ARRAY_DEFS[name][0]
    values = {key.upper(): value for key, value in values.items()}
    if index is None:
        array.ensure_empty_end_item()
        index = len(array) - 1
    elif not array.has_index(index) or not array.is_in_use(index):
        raise NotFoundError(f'{name} has no item {index}')
    config = array[index]
    if not str(values.get(primary, config[primary]) or '').strip():
        raise InvalidRequestError(f'{name} needs a {primary}')
    is_indexer = name in ('NEWZNAB', 'TORZNAB')
    old_address = (config['HOST'], config['API']) if is_indexer else ()
    messages = _set_array_values(name, config, values)
    if (is_indexer and not config.get_bool('MANUAL')
            and (old_address != (config['HOST'], config['API']) or not config['UPDATED'])):
        get_capabilities(config, force=True)
    save_config()
    # saving numbers the items again, from 0
    index = next(found for found in range(len(array)) if array[found] is config)
    return {**_array_item(array, index), 'messages': messages}


def delete_array_item(name: str, index: int):
    """ Take an item out of a list, and save it """
    array = _array(name)
    if not array.has_index(index) or not array.is_in_use(index):
        raise NotFoundError(f'{name} has no item {index}')
    array[index][ARRAY_DEFS[name.upper()][0]] = ''
    save_config()


# --- testing a connection with the settings the page has

# the indexers that aren't lists, tested by their name
PROVIDER_TESTS = ('TPB', 'LIME', 'TDL', 'ABB', 'BOK', 'SLSK', 'ANNA', 'WEBSHARE')
TESTS = (*(client.upper() for client in connections.CLIENTS), 'DELUGE',
         *(notifier.upper() for notifier in connections.NOTIFIERS), *PROVIDER_TESTS,
         'FFMPEG', 'EBOOK_CONVERT', 'CALIBREDB', 'PREPROCESSOR', 'GOODREADS', 'GOOGLEBOOKS')


def _provider_result(result, shown: str) -> tuple[bool, str]:
    ok = result is not False and result is not None
    return ok, f"{shown} works" if ok else f"{shown} didn't work, see the log"


def _run_test(test: str, array: str = '', index: int | None = None) -> tuple[bool, str]:
    """ Run a test with the settings as they are. Returns whether it worked, and what it said """
    if array:
        config = _array(array)[index]
        return _provider_result(*provider_test(f'{array.lower()}_{index}',
                                               host=config['URL'] if array.upper() == 'APPRISE' else ''))
    if test.lower() in connections.CLIENTS:
        message, ok = connections.CLIENTS[test.lower()][0].check_link()
        return bool(ok), str(message)
    if test == 'DELUGE':
        outcome = connections.test_deluge({})
        if outcome.get('error'):
            return False, str(outcome['error'])
        if outcome.get('webui'):
            return 'success' in str(outcome['webui']).lower(), str(outcome['webui'])
        added = [found['label'] for found in outcome.get('checked', []) if found['added']]
        return True, 'Connected to the Deluge daemon' + (f", labels added: {', '.join(added)}" if added else '')
    if test.lower() in connections.NOTIFIERS:
        module, _section, worked = connections.NOTIFIERS[test.lower()]
        result = getattr(notifiers, module).test_notify()
        ok = bool(worked(result))
        return ok, str(result) if isinstance(result, str) and result else ('Sent' if ok else "It wasn't sent")
    if test in PROVIDER_TESTS:
        return _provider_result(*provider_test(test))
    if test == 'FFMPEG':
        return True, f'ffmpeg {connections.test_ffmpeg()}'
    if test == 'EBOOK_CONVERT':
        return True, f'ebook-convert {connections.test_ebook_convert()}'
    if test == 'CALIBREDB':
        result = str(connections.test_calibredb())
        return 'failed' not in result.lower(), result
    if test == 'PREPROCESSOR':
        result = connections.test_preprocessor()
        if result is None:
            return False, 'There is no preprocessor'
        returncode, out, err = result
        return not returncode, str(out or err or '').strip()
    if test == 'GOOGLEBOOKS':
        return connections.test_googlebooks()
    result = grsync.test_auth()
    return result.startswith('Pass:'), result


def run_test(test: str, values: dict, array: str = '', index: int | None = None) -> dict:
    """ Test a connection with the settings the page has: settings by name, or a list's item by its
    index, a new one without. If it works they're kept and saved, as the old settings page did, and
    a new item is added; if not, the settings are put back. Returns ok, message and the item's index """
    test = test.upper()
    if not array and test not in TESTS:
        raise InvalidRequestError(f'There is no test {test}')
    values = {key.upper(): value for key, value in values.items()}
    if array:
        items = _array(array)
        if index is None:
            items.ensure_empty_end_item()
            index = len(items) - 1
        elif not items.has_index(index) or not items.is_in_use(index):
            raise NotFoundError(f'{array} has no item {index}')
        config = items[index]
        settings = list(config.items())
    else:
        for key in values:
            if key not in OWNER_FIELDS and key not in OTHER_SETTINGS:
                _item(key)
        settings = [(key, _item(key)) for key in values if key not in OTHER_SETTINGS and key not in OWNER_FIELDS]
    before = {key: item.value for key, item in settings}
    messages = _set_array_values(array, config, values) if array else _set_values(dict(values))
    try:
        ok, message = _run_test(test, array, index)
    except ServiceError as e:
        ok, message = False, str(e)
    except Exception as e:
        logging.getLogger(__name__).error(f'Testing {array or test}: {type(e).__name__} {e}')
        ok, message = False, f'{type(e).__name__} {e}'
    if ok:
        save_config()
        if array:
            index = next(found for found in range(len(items)) if items[found] is config)
    else:
        for key, item in settings:
            item.value = before[key]
    return {'ok': ok, 'message': '\n'.join([message, *messages]).strip(), 'index': index if array else None}
