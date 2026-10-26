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
from lazylibrarian import database, grsync
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
from lazylibrarian.configtypes import ConfigBool
from lazylibrarian.csvfile import dump_table, restore_table
from lazylibrarian.dbupgrade import check_db
from lazylibrarian.filesystem import DIRS, listdir, path_isdir, syspath
from lazylibrarian.formatter import (
    DISPLAY_DATE_FORMATS,
    ISSUE_DATE_FORMATS,
    check_int,
    date_format_picker,
    get_list,
    make_unicode,
    plural,
    unaccented,
)
from lazylibrarian.logconfig import LOGCONFIG
from lazylibrarian.scheduling import check_running_jobs
from lazylibrarian.services import InvalidRequestError
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


def set_source(setting: str, value) -> str:
    """ Switch an info source on or off (OL_API, DNB_API, ...) or set its api key (GR_API, GB_API). One
        switched on or given a key becomes BOOK_API, the source searched first. OpenLibrary is switched
        back on if nothing else is left. Returns the value """
    if setting in SOURCE_SWITCHES:
        CONFIG.set_bool(setting, bool(value))
        if value:
            CONFIG.set_str('BOOK_API', SOURCE_SWITCHES[setting])
    elif setting in SOURCE_KEYS:
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
        if value is not None:
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
