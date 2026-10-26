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

""" The settings page, saving it, API keys, info source API changes and Goodreads authorisation """

import json
import logging
import os
import secrets
import time
from urllib.parse import unquote_plus

import cherrypy

import lazylibrarian
from lazylibrarian import database, grsync, i18n
from lazylibrarian.auth import (
    AUTH_BASIC,
    AUTH_EXTERNAL,
    AUTH_FORM,
    REQUIRED_DISABLED_LOCAL,
    REQUIRED_ENABLED,
    get_owner,
    require_auth,
    session_token,
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
from lazylibrarian.web.common import BasePages, browser_languages, owner_details, serve_template


class SettingsPages(BasePages):
    """ The settings page, saving it, API keys, info source API changes and Goodreads authorisation """

    @cherrypy.expose
    @require_auth()
    def save_filters(self):
        self.label_thread('WEBSERVER')
        savedir = DIRS.DATADIR
        mags = dump_table('magazines', savedir)
        msg = f"{mags} {plural(mags, 'magazine')} exported"
        return msg

    @cherrypy.expose
    @require_auth()
    def load_filters(self):
        self.label_thread('WEBSERVER')
        savedir = DIRS.DATADIR
        mags = restore_table('magazines', savedir)
        msg = f"{mags} {plural(mags, 'magazine')} imported"
        return msg

    @cherrypy.expose
    @require_auth()
    def config(self):
        logger = logging.getLogger(__name__)
        self.label_thread('CONFIG')
        http_look_dir = os.path.join(DIRS.PROG_DIR, 'data' + os.path.sep + 'interfaces')
        http_look_list = [name for name in listdir(http_look_dir)
                          if path_isdir(os.path.join(http_look_dir, name))]
        status_list = ['Skipped', 'Wanted', 'Have', 'Ignored']
        apprise_list = lazylibrarian.notifiers.apprise_notify.AppriseNotifier.notify_types()

        mags_list = []
        comics_list = []
        db = database.DBConnection()
        try:
            comics = db.select(
                'SELECT * from comics ORDER by Title COLLATE NOCASE')
            magazines = db.select(
                'SELECT * from magazines ORDER by Title COLLATE NOCASE')
        finally:
            db.close()
        if comics:
            for mag in comics:
                title = mag['Title']
                genre = mag['Genre']
                if not genre:
                    genre = ""
                comics_list.append({
                    'Title': title,
                    'Genre': genre
                })
        if magazines:
            for mag in magazines:
                title = mag['Title']
                regex = mag['Regex']
                genre = mag['Genre']
                if not genre:
                    genre = ""
                if not regex:
                    regex = ""
                reject = mag['Reject']
                if not reject:
                    reject = ""
                datetype = mag['DateType']
                if not datetype:
                    datetype = ""
                language = mag['Language']
                if not language:
                    language = CONFIG['PREF_MAGLANG']
                coverpage = check_int(mag['CoverPage'], 1)
                mags_list.append({
                    'Title': title,
                    'Reject': reject,
                    'Regex': regex,
                    'Genre': genre,
                    'DateType': datetype,
                    'CoverPage': coverpage,
                    'Language': language
                })

        BLOCKHANDLER.check_day()

        # Don't pass the whole config, no need to pass the
        # lazylibrarian.globals
        months = {}
        try:
            for cnt, itm in enumerate(lazylibrarian.MONTHNAMES[0]):
                months[cnt] = ', '.join(itm)
        except Exception as e:
            logger.error(f"Unable to load monthnames: {e}")
            logger.error(f"{lazylibrarian.MONTHNAMES}")

        seasons = {}
        try:
            for itm in lazylibrarian.SEASONS:
                value = lazylibrarian.SEASONS[itm]
                if value not in seasons:
                    seasons[value] = itm
                else:
                    seasons[value] = f"{seasons[value]}, {itm}"
        except Exception as e:
            logger.error(f"Unable to load seasons: {e}")
            logger.error(f"{lazylibrarian.SEASONS}")

        namevars = name_vars('test')
        testvars = {}
        for itm in namevars:
            testvars[itm] = namevars[itm].replace(' ', '&nbsp;')
        config = {
            "http_look_list": http_look_list,
            "apprise_list": apprise_list,
            "status_list": status_list,
            "magazines_list": mags_list,
            "comics_list": comics_list,
            "namevars": testvars,
            "seasons": seasons,
            "months": months,
            "book_languages": language_picker(CONFIG['IMP_PREFLANG'], browser_languages()),
            "gb_countries": country_picker(CONFIG['GB_COUNTRY']),
            "mag_languages": magazine_language_picker(CONFIG['PREF_MAGLANG']),
            "author_date_formats": date_format_picker(CONFIG['AUTHOR_DATE_FORMAT'], DISPLAY_DATE_FORMATS,
                                                      CONFIG['DATE_LANG']),
            "date_formats": date_format_picker(CONFIG['DATE_FORMAT'], DISPLAY_DATE_FORMATS, CONFIG['DATE_LANG']),
            "iss_formats": date_format_picker(CONFIG['ISS_FORMAT'], ISSUE_DATE_FORMATS, CONFIG['DATE_LANG']),
            "anna_auto": anna_search_languages('', CONFIG['IMP_PREFLANG']),
            "zlib_auto": zlib_search_languages('', CONFIG['IMP_PREFLANG']),
            "updated": time.ctime(CONFIG.get_int('GIT_UPDATED')),
            "owner": owner_details(),
        }
        for itm in CONFIG.config.values():
            if isinstance(itm, ConfigBool):
                itm.reset_read_count()  # Reset read counts as we use this to determine which settings have changed
        return serve_template(templatename="config.html", title=i18n.gettext("Settings"), config=config)

    @cherrypy.expose
    @require_auth()
    def config_update(self, **kwargs):
        """ Update config based on settings in the UI """
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        adminmsg = ''
        if kwargs.get('admin_email') and not is_valid_email(kwargs['admin_email']):
            adminmsg += i18n.gettext('Contact email looks invalid, please check') + '<br>'

        # the owner login is stored hashed in the users table, not in the config file
        owner = get_owner(db) or {}
        new_username = kwargs.pop('owner_username', '').strip()
        new_password = kwargs.pop('owner_password', '')
        new_password2 = kwargs.pop('owner_password2', '')
        if new_username and new_username != owner.get('UserName'):
            if self.validate_param('username', new_username, ['<', '>', '=', ':'], None):
                set_owner_credentials(db, username=new_username)
                adminmsg += i18n.gettext('Username changed') + '<br>'
            else:
                adminmsg += i18n.gettext('Invalid username') + '<br>'
        if new_password or new_password2:
            if new_password != new_password2:
                adminmsg += i18n.gettext('Passwords do not match, password not changed') + '<br>'
            elif not pwd_check(new_password):
                adminmsg += i18n.gettext("Password must be at least 8 characters long\nand not contain spaces") + '<br>'
            else:
                set_owner_credentials(db, password=new_password, keep_token=session_token())
                adminmsg += i18n.gettext('Password changed') + '<br>'
        # unknown values would leave the generic loop below to store them, keep the current ones
        if kwargs.get('auth_type') not in (None, AUTH_FORM, AUTH_BASIC, AUTH_EXTERNAL):
            kwargs.pop('auth_type')
        if kwargs.get('auth_required') not in (None, REQUIRED_ENABLED, REQUIRED_DISABLED_LOCAL):
            kwargs.pop('auth_required')
        if kwargs.get('auth_type') == AUTH_EXTERNAL and not kwargs.get('proxy_auth_user', '').strip():
            kwargs.pop('auth_type')
            adminmsg += i18n.gettext('External authentication needs the proxy user header, '
                                     'authentication method not changed') + '<br>'

        # store any genre changes
        genre_changes = ''
        genrelimit = check_int(kwargs.get('genrelimit', 0), 0)
        if lazylibrarian.GRGENRES.get('genreLimit', 10) != genrelimit:
            lazylibrarian.GRGENRES['genreLimit'] = genrelimit
            genre_changes += 'limit '
        genreusers = check_int(kwargs.get('genreusers', 0), 0)
        if lazylibrarian.GRGENRES.get('genreUsers', 10) != genreusers:
            lazylibrarian.GRGENRES['genreUsers'] = genreusers
            genre_changes += 'users '
        newexcludes = sorted(get_list(kwargs.get('genreexclude', ''), ','))
        if sorted(lazylibrarian.GRGENRES.get('genreExclude', [])) != newexcludes:
            lazylibrarian.GRGENRES['genreExclude'] = newexcludes
            genre_changes += 'excludes '
        newexcludes = sorted(get_list(kwargs.get('genreexcludeparts', ''), ','))
        if sorted(lazylibrarian.GRGENRES.get('genreExcludeParts', [])) != newexcludes:
            lazylibrarian.GRGENRES['genreExcludeParts'] = newexcludes
            genre_changes += 'parts '
        # now the replacements
        genredict = {}
        for itm in kwargs:
            if itm.startswith('genrereplace['):
                mykey = make_unicode(itm.split('[')[1].split(']')[0])
                myval = make_unicode(kwargs.get(itm, ''))
                if myval:
                    genredict[mykey] = myval

        # new genre to add
        if 'genrenew' in kwargs and 'genreold' in kwargs and kwargs['genrenew'] and kwargs['genreold']:
            genredict[make_unicode(kwargs['genreold'])] = make_unicode(kwargs['genrenew'])
            genre_changes += 'new-entry '

        dicts_same = False
        if len(lazylibrarian.GRGENRES.get('genreReplace', {})) != len(genredict):
            genre_changes += 'dict-length '
        else:
            shared_items = {k: lazylibrarian.GRGENRES['genreReplace'][k]
                            for k in lazylibrarian.GRGENRES['genreReplace']
                            if k in genredict and lazylibrarian.GRGENRES['genreReplace'][k] == genredict[k]}
            if len(shared_items) != len(genredict):
                genre_changes += 'shared-values '
            else:
                dicts_same = True

        if not dicts_same:
            lazylibrarian.GRGENRES['genreReplace'] = genredict

        if genre_changes:
            logger.debug(f"Genre changes: {genre_changes}")
            logger.debug("Writing out new genres.json")
            newdict = {
                'genreLimit': lazylibrarian.GRGENRES['genreLimit'],
                'genreUsers': lazylibrarian.GRGENRES['genreUsers'],
                'genreExclude': lazylibrarian.GRGENRES['genreExclude'],
                'genreExcludeParts': lazylibrarian.GRGENRES['genreExcludeParts'],
                'genreReplace': lazylibrarian.GRGENRES['genreReplace'],
            }
            with open(syspath(os.path.join(DIRS.DATADIR, 'genres.json')), 'w') as f:
                json.dump(newdict, f, indent=4)
            logger.debug("Applying genre changes")
            check_db()

        # months lists
        new_months = []
        x = range(13)
        for month_num in x:
            key = f"month_{month_num}"
            month_names = kwargs.get(key, '')
            if month_names:
                new_months.append(get_list(month_names, ','))
        if new_months != lazylibrarian.MONTHNAMES[0]:
            logger.debug("MONTHNAMES has changed")
            if not validate_monthtable(new_months):
                logger.debug("New MONTHNAMES is not valid, ignoring")
            else:
                json_file = os.path.join(DIRS.DATADIR, 'monthnames.json')
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(new_months, f, ensure_ascii=False)

                # Create a second copy of the monthnames without accents and lowercased to speed up matching
                cleantable = []
                for lyne in new_months:
                    cleanlyne = []
                    for itm in lyne:
                        cleanlyne.append(unaccented(itm).lower().strip('.'))
                    cleantable.append(cleanlyne)

                lazylibrarian.MONTHNAMES = [new_months, cleantable]

        # now the season dictionary
        new_seasons = {}
        for key in kwargs:
            if key.startswith('season_'):
                season_names = kwargs[key]
                season_value = check_int(key.split('_')[1], 0)
                for itm in get_list(season_names):
                    new_seasons[itm] = season_value
        if new_seasons != lazylibrarian.SEASONS:
            logger.debug("SEASONS has changed")
            lazylibrarian.SEASONS = new_seasons.copy()
            json_file = os.path.join(DIRS.DATADIR, 'seasons.json')
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(lazylibrarian.SEASONS, f, ensure_ascii=False)

        # now the config file entries
        for key, itm in CONFIG.config.items():
            if key.lower() in kwargs:
                value = kwargs[key.lower()]
                # validate entries here...
                if value:
                    if key.lower() in ['bok_host', 'fallback_proxy', 'proxy_host']:
                        tokens = ['<', '>', '"', "'", '+', '(', ')']
                    elif (key.lower() in ['user_agent', 'fmt_series'] or key.lower().endswith('_folder')
                          or key.lower().endswith('_file')):
                        tokens = ['<', '&', '>', '=', '"', "'", '+']
                    elif '_pass' in key.lower():
                        tokens = []  # passwords can contain any char as they are not displayed
                    else:
                        tokens = ['<', '&', '>', '=', '"', "'", '+', '(', ')']
                    if not self.validate_param(key.lower(), value, tokens, None):
                        newvalue = unquote_plus(value)
                        for token in tokens:
                            if token in newvalue:
                                newvalue = newvalue.replace(token, '')
                        value = newvalue
                        logger.warning(f"Invalid Token: Key {key} changed to {value}")
                CONFIG.set_from_ui(key, value)
            else:
                if isinstance(itm, ConfigBool) and itm.get_read_count() > 0:
                    itm.set_from_ui(False)  # Set other items to False that we've seen (i.e. are shown)
        CONFIG.ensure_valid_homepage()

        magazines = db.select('SELECT * from magazines')
        if magazines:
            count = 0
            for mag in magazines:
                title = mag['Title']
                reject = mag['Reject']
                regex = mag['Regex']
                genres = mag['Genre']
                datetype = mag['DateType']
                coverpage = check_int(mag['CoverPage'], 1)
                language = mag['Language']
                # seems kwargs parameters from cherrypy are sometimes passed as latin-1,
                # can't see how to configure it, so we need to correct it on accented magazine names
                # eg "Elle Quebec" where we might have e-acute stored as unicode
                # e-acute is \xe9 in latin-1  but  \xc3\xa9 in utf-8
                # otherwise the comparison fails, but sometimes accented characters won't
                # fit latin-1 but fit utf-8 how can we tell ???
                if not isinstance(title, str):
                    try:
                        title = title.encode('latin-1')
                    except UnicodeEncodeError:
                        try:
                            title = title.encode('utf-8')
                        except UnicodeEncodeError:
                            logger.warning(f'Unable to convert title [{repr(title)}]')
                            title = unaccented(title, only_ascii=False)

                new_value_dict = {}
                new_reject = kwargs.get(f'reject_list[{title}]')
                if new_reject != reject:
                    new_value_dict['Reject'] = new_reject
                new_regex = kwargs.get(f'regex[{title}]')
                if new_regex != regex:
                    new_value_dict['Regex'] = new_regex
                new_genres = kwargs.get(f'genre_list[{title}]')
                if new_genres != genres:
                    new_value_dict['Genre'] = new_genres
                new_datetype = kwargs.get(f'datetype[{title}]')
                if new_datetype != datetype:
                    new_value_dict['DateType'] = new_datetype
                    # if changed from issuenum to date or vice-versa,
                    # check was a date (contains '-') and now expect IssueNum
                    # check was issuenum (all digit) and now expect date
                    # reset latest-issue to force scanning for new style issue names
                    if (('I' in new_datetype and '-' in mag['IssueDate']) or
                        (new_datetype and 'I' not in new_datetype and mag['IssueDate'] and mag['IssueDate'].isdigit())):
                            new_value_dict['IssueDate'] = ''
                            logger.debug(f"Reset IssueDate for {mag['Title']} as datestyle changed to {new_datetype}")
                new_coverpage = check_int(kwargs.get(f"coverpage[{title}]"), 1)
                if new_coverpage != coverpage:
                    new_value_dict['CoverPage'] = new_coverpage
                new_language = kwargs.get(f'language[{title}]')
                if new_language != language:
                    new_value_dict['Language'] = new_language
                if new_value_dict:
                    count += 1
                    db.upsert("magazines", new_value_dict, {'Title': title})
            if count:
                logger.info(f"Magazine {count} filters updated")
        db.close()

        CONFIG.update_providers_from_ui(kwargs)

        # Convert legacy log settings
        logtype = kwargs.get('log_type', '')
        if logtype == 'Quiet':
            newloglevel = logging.CRITICAL
        elif logtype == 'Normal':
            newloglevel = logging.INFO
        elif logtype == 'Debug':
            newloglevel = logging.DEBUG
        else:  # legacy interface, no log_type
            newloglevel = int(kwargs.get('loglevel', logging.INFO))

        # Enable/disable special loggers based on UI
        specials = []
        for logger in LOGCONFIG.get_special_logger_list():
            shortname = LOGCONFIG.get_short_special_logger_name(logger.name)
            uiname = f'log_{shortname}'
            if uiname in kwargs:
                specials.append(shortname)
        specialcsv = ','.join(specials)
        LOGCONFIG.enable_only_these_special_debuglogs(specialcsv)
        CONFIG.set_csv('LOGSPECIALDEBUG', specialcsv)

        # Store this in CONFIG so it's persisted. OnChange triggers event to activate.
        CONFIG.set_int('LOGLEVEL', newloglevel)
        CONFIG.save_config_and_backup_old(restart_jobs=True)
        if not lazylibrarian.STOPTHREADS:
            check_running_jobs()

        if adminmsg:
            return serve_template(templatename="response.html", prefix="",
                                  title=i18n.gettext("Access Control"), message=adminmsg, timer=0)

        raise cherrypy.HTTPRedirect("config")

    @cherrypy.expose
    @require_auth()
    def ol_api_changed(self, **kwargs):
        # ol_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        else:
            CONFIG.set_bool('OL_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def dnb_api_changed(self, **kwargs):
        # dnb_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('DNB_API', True)
            CONFIG.set_str('BOOK_API', 'DNB')
        else:
            CONFIG.set_bool('DNB_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def bn_api_changed(self, **kwargs):
        # bn_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('BN_API', True)
            CONFIG.set_str('BOOK_API', 'BN')
        else:
            CONFIG.set_bool('BN_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def dbk_api_changed(self, **kwargs):
        # dbk_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('DBK_API', True)
            CONFIG.set_str('BOOK_API', 'DBK')
        else:
            CONFIG.set_bool('DBK_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def ran_api_changed(self, **kwargs):
        # ran_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('RAN_API', True)
            CONFIG.set_str('BOOK_API', 'RanobeDB')
        else:
            CONFIG.set_bool('RAN_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def hc_api_changed(self, **kwargs):
        # hc_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('HC_API', True)
            CONFIG.set_str('BOOK_API', 'HardCover')
        else:
            CONFIG.set_bool('HC_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def gr_api_changed(self, **kwargs):
        self.validate_param("goodreads api", kwargs['gr_api'], ['<', '>', '='], 404)
        CONFIG.set_str('GR_API', kwargs['gr_api'])
        if kwargs['gr_api']:
            CONFIG.set_str('BOOK_API', 'GoodReads')
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['gr_api']

    @cherrypy.expose
    @require_auth()
    def gb_api_changed(self, **kwargs):
        self.validate_param("googlebooks api", kwargs['gb_api'], ['<', '>', '='], 404)
        CONFIG.set_str('GB_API', kwargs['gb_api'])
        if kwargs['gb_api']:
            CONFIG.set_str('BOOK_API', 'GoogleBooks')
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')
                and not CONFIG.get_bool('BN_API') and not CONFIG.get_bool('DBK_API')
                and not CONFIG.get_bool('RAN_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
            CONFIG.set_str('BOOK_API', 'OpenLibrary')
        return kwargs['gb_api']

    @cherrypy.expose
    @require_auth()
    def book_api_changed(self, **kwargs):
        CONFIG.set_str('BOOK_API', kwargs['book_api'])
        return kwargs['book_api']

    @cherrypy.expose
    @require_auth()
    def grauth_step1(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'gr_api' in kwargs:
            self.validate_param("goodreads api", kwargs['gr_api'], ['<', '>', '='], 404)
            CONFIG.set_str('GR_API', kwargs['gr_api'])
        if 'gr_secret' in kwargs:
            self.validate_param("goodreads secret", kwargs['gr_secret'], ['<', '>', '='], 404)
            CONFIG.set_str('GR_SECRET', kwargs['gr_secret'])
        ga = grsync.GrAuth()
        res = ga.goodreads_oauth1()
        return res

    @cherrypy.expose
    @require_auth()
    def grauth_step2(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        ga = grsync.GrAuth()
        res = ga.goodreads_oauth2()
        if "Authorisation complete" in res:
            CONFIG.set_bool('GR_SYNC', True)
        return res

    @cherrypy.expose
    @require_auth()
    def generate_ro_api(self):
        return self.generate_api(ro=True)

    @cherrypy.expose
    @require_auth()
    def generate_api(self, ro=False):
        logger = logging.getLogger(__name__)
        api_key = secrets.token_hex(16)
        if ro:
            CONFIG.set_str('API_RO_KEY', api_key)
        else:
            CONFIG.set_str('API_KEY', api_key)
        logger.info("New API generated")
        return api_key

    @cherrypy.expose
    @require_auth()
    def set_current_tabs(self, **kwargs):
        if 'config_tab' in kwargs:
            CONFIG.set_from_ui('CONFIG_TAB_NUM', check_int(kwargs['config_tab'], 1))
