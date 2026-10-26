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

""" The owner's profile, subscriptions, feeds, help and logout """

import contextlib
import json
import logging

import cherrypy

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.auth import (
    end_session,
    owner_id,
    require_auth,
    session_token,
    set_owner_credentials,
)
from lazylibrarian.common import is_valid_email, pwd_check, pwd_generator
from lazylibrarian.config2 import CONFIG, wishlist_type
from lazylibrarian.formatter import check_int, get_list
from lazylibrarian.passwords import verify_password
from lazylibrarian.web.common import BasePages, clear_our_cookies, serve_template, valid_ui_lang


class UserPages(BasePages):
    """ The owner's profile, subscriptions, feeds, help and logout """

    @cherrypy.expose
    @require_auth()
    def profile(self):
        title = i18n.gettext('User Profile')
        userid = owner_id()
        if userid:
            db = database.DBConnection()
            try:
                user = db.match('SELECT UserName,UserID,Name,Email,SendTo,BookType,Theme,hc_id,hc_token,'
                                'CalibreRead,CalibreToRead from users where UserID=?', (userid,))
                if user:
                    subs = db.select('SELECT Type,WantID from subscribers WHERE UserID=?', (userid,))
                    subscriptions = ''
                    for itm in subs:
                        if subscriptions:
                            subscriptions += '\n'
                        item_name = ''
                        if itm['Type'] == 'author':
                            res = db.match('SELECT AuthorName from authors WHERE authorid=?', (itm['WantID'],))
                            if res:
                                item_name = f"({res['AuthorName']})"
                        elif itm['Type'] == 'series':
                            res = db.match('SELECT SeriesName from series WHERE seriesid=?', (itm['WantID'],))
                            if res:
                                item_name = f"({res['SeriesName']})"
                        elif itm['Type'] == 'comic':
                            try:
                                comicid, issueid = itm['WantID'].split('_')
                            except ValueError:
                                comicid = ''
                            if comicid:
                                res = db.match('SELECT Title from comics WHERE comicid=?', (comicid,))
                                if res:
                                    item_name = f"({res['Title']})"
                        subscriptions += f'{itm["Type"]} {itm["WantID"]} {item_name}'
                    user = dict(user)
                    if not user['Theme']:
                        user['Theme'] = ''
                    themelist = ['Default']
                    for itm in lazylibrarian.BOOKSTRAP_THEMELIST:
                        themelist.append('bookstrap_' + itm)
                    return serve_template(templatename="profile.html", title=title, user=user, subs=subscriptions,
                                          typelist=get_list(CONFIG['EBOOK_TYPE']), themelist=themelist)
            finally:
                db.close()
        return serve_template(templatename="index.html", title=i18n.gettext('Authors'), redirect='authors')

    @cherrypy.expose
    @require_auth()
    def help(self):
        cookie = cherrypy.request.cookie
        if cookie and 'll_template' in list(cookie.keys()):
            template = cookie['ll_template'].value
            for itm in [['index.html', 'overview'],
                        ['books.html', 'ebooks'],
                        ['series.html', 'series'],
                        ['audio.html', 'audiobooks'],
                        ['magazines.html', 'magazines'],
                        ['managebooks.html', 'manage'],
                        ['history.html', 'history'],
                        ['logs.html', 'logs'],
                        ['config.html', 'config_menus'],
                        ['author.html', 'authors'],
                        ['issues.html', 'magazine_detail'],
                        ]:
                if template == itm[0]:
                    page = itm[1]
                    if template == 'config.html' and 'configTab' in list(cookie.keys()):
                        tab = check_int(cookie['configTab'].value, 1)
                        tabs = ['interface', 'importing', 'downloaders', 'providers', 'processing',
                                'notifications', 'categories', 'filters', 'genres']
                        with contextlib.suppress(IndexError):
                            page = 'config_' + tabs[tab - 1]
                    raise cherrypy.HTTPRedirect("https://lazylibrarian.gitlab.io/" + page)
        raise cherrypy.HTTPRedirect("https://lazylibrarian.gitlab.io/")

    @cherrypy.expose
    @require_auth()
    def logout(self):
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            db = database.DBConnection()
            try:
                db.action('UPDATE users SET prefs=? where UserID=?',
                          (check_int(cookie['ll_prefs'].value, 0), owner_id()))
            finally:
                db.close()
        end_session()
        clear_our_cookies()
        if cherrypy.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return "OK"
        root = CONFIG['HTTP_ROOT'].rstrip('/') if CONFIG['HTTP_ROOT'] else ''
        raise cherrypy.HTTPRedirect(f"{root}/auth/login")

    @cherrypy.expose
    @require_auth()
    def user_update(self, **kwargs):
        if ('password' in kwargs and 'password2' in kwargs and kwargs['password'] and
                kwargs['password'] != kwargs['password2']):
            return i18n.gettext("Passwords do not match")
        if kwargs['password'] and not pwd_check(kwargs['password']):
            return i18n.gettext("Password must be at least 8 characters long\nand not contain spaces")
        logger = logging.getLogger(__name__)
        changes = ''
        userid = owner_id()
        if userid:
            db = database.DBConnection()
            user = db.match('SELECT UserName,Name,Email,Password,BookType,SendTo,Theme,hc_token,ui_lang,'
                            'CalibreRead,CalibreToRead from users where UserID=?', (userid,))
            if user:
                if kwargs['username'] and user['UserName'] != kwargs['username']:
                    if self.validate_param("username", kwargs['username'], ['<', '>', '=', ':'], None):
                        changes += ' username'
                        set_owner_credentials(db, username=kwargs['username'])
                    else:
                        logger.warning("Invalid username")

                if kwargs['fullname'] and user['Name'] != kwargs['fullname']:
                    if self.validate_param("fullname", kwargs['fullname'], ['<', '>', '='], None):
                        changes += ' name'
                        db.action('UPDATE users SET Name=? WHERE UserID=?', (kwargs['fullname'], userid))
                    else:
                        logger.warning("Invalid fullname")

                if kwargs['email'] and user['Email'] != kwargs['email']:
                    if not is_valid_email(kwargs['email']):
                        logger.warning("Invalid email")
                    else:
                        changes += ' email'
                        db.action('UPDATE users SET email=? WHERE UserID=?', (kwargs['email'], userid))

                if user['Theme'] != kwargs['theme']:
                    valid = False
                    theme = kwargs['theme']
                    if theme in ['None', 'Default', '']:
                        theme = ''
                    if not theme:
                        valid = True
                    if theme == 'legacy':
                        valid = True
                    else:
                        parts = theme.split('_', 1)
                        if (parts[0] == 'bookstrap' and len(parts) == 2 and parts[1] in
                                lazylibrarian.BOOKSTRAP_THEMELIST):
                            valid = True
                    if valid:
                        changes += ' Theme'
                        db.action('UPDATE users SET Theme=? WHERE UserID=?', (theme, userid))
                    else:
                        logger.warning(f"Invalid user theme [{theme}]")

                # profile.html doesn't send ui_lang, only the admin users page does
                if 'ui_lang' in kwargs and (user['UI_Lang'] or '') != kwargs['ui_lang']:
                    if valid_ui_lang(kwargs['ui_lang']):
                        changes += ' UI_Lang'
                        db.action('UPDATE users SET UI_Lang=? WHERE UserID=?', (kwargs['ui_lang'], userid))
                    else:
                        logger.warning(f"Invalid UI Language [{kwargs['ui_lang']}]")

                if user['SendTo'] != kwargs['sendto']:
                    if not is_valid_email(kwargs['sendto']):
                        logger.warning("Invalid email")
                    else:
                        changes += ' sendto'
                        db.action('UPDATE users SET sendto=? WHERE UserID=?', (kwargs['sendto'], userid))

                if user['BookType'] != kwargs['booktype']:
                    changes += ' BookType'
                    db.action('UPDATE users SET BookType=? WHERE UserID=?', (kwargs['booktype'], userid))

                if user['hc_token'] != kwargs['hc_token']:
                    if self.validate_param("hardcopy token", kwargs['hc_token'], ['<', '>', '='], None):
                        changes += ' hc_token'
                        db.action('UPDATE users SET hc_token=? WHERE UserID=?', (kwargs['hc_token'], userid))
                    else:
                        logger.warning("Invalid hardcopy token")

                if kwargs['password'] and not verify_password(kwargs['password'], user['password']):
                    changes += ' password'
                    # logs out everywhere else, but not this browser
                    set_owner_credentials(db, password=kwargs['password'], keep_token=session_token())

                for key, column in [('calread', 'CalibreRead'), ('caltoread', 'CalibreToRead')]:
                    if key in kwargs and (user[column] or '') != kwargs[key]:
                        if self.validate_param(column, kwargs[key], ['<', '>', '='], None):
                            changes += f' {column}'
                            db.action(f'UPDATE users SET {column}=? WHERE UserID=?', (kwargs[key], userid))
                        else:
                            logger.warning(f"Invalid {column}")
            db.close()

            if changes:
                return i18n.gettext('Updated user details: %(fields)s') % {'fields': changes.strip()}
        return i18n.gettext("No changes made")

    @cherrypy.expose
    @require_auth()
    def update_feeds(self, **kwargs):
        logger = logging.getLogger(__name__)
        if 'value' in kwargs and kwargs['value'] == '':
            # cancel or [x] pressed
            return i18n.gettext('No changes made')
        kwargs.pop('user', None)
        user = owner_id()
        value = get_list(kwargs.pop('value[]', ''))
        cnt = 0
        db = database.DBConnection()
        for itm in kwargs:
            if '[text]' in itm:
                feedname = kwargs[itm]
                feednum = kwargs.get(itm.replace('[text]', '[value]'), '')
                if feedname and feednum:
                    res = db.match('SELECT * from subscribers WHERE Type=? and UserID=? and WantID=?',
                                   ("feed", user, feedname))
                    if feednum in value:
                        if res:
                            logger.debug(f"{feedname} {user} was already subscribed")
                        else:
                            cnt += 1
                            db.action('INSERT INTO subscribers (Type, UserID, WantID) VALUES (?, ?, ?)',
                                      ("feed", user, feedname))
                            logger.debug(f"Subscribed {user} to {feedname}")
                    else:
                        if res:
                            cnt += 1
                            db.action('DELETE from subscribers WHERE Type=? and UserID=? and WantID=?',
                                      ("feed", user, feedname))
                            logger.debug(f"Unsubscribed {user} to {feedname}")
                        else:
                            logger.debug(f"{feedname} {user} was already unsubscribed")
        db.close()
        return i18n.ngettext('Changed %(count)s feed', 'Changed %(count)s feeds', cnt) % {'count': cnt}

    @cherrypy.expose
    @require_auth()
    def user_feeds(self, **kwargs):
        logger = logging.getLogger(__name__)
        user = owner_id()
        if user:
            feedlist = []
            value = []
            cnt = 0
            db = database.DBConnection()
            try:
                feeds = db.select("SELECT * from subscribers where Type='feed' and UserID=?", (user,))
            finally:
                db.close()
            for provider in CONFIG.providers('RSS'):
                wishtype = wishlist_type(provider['HOST'])
                if wishtype:
                    cnt += 1
                    subscribed = False
                    for itm in feeds:
                        if itm['WantID'] == provider['DISPNAME']:
                            subscribed = True
                            break
                    feedlist.append({'text': provider['DISPNAME'], 'value': str(cnt)})
                    if subscribed:
                        value.append(str(cnt))
            res = json.dumps({'feeds': feedlist, 'value': value})
            logger.debug(res)
            return res
        return json.dumps({'feeds': '', 'value': ''})

    @cherrypy.expose
    @require_auth()
    def generatepwd(self):
        return pwd_generator()

    @cherrypy.expose
    @require_auth()
    def toggle_my_auth(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myauthors
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def toggle_my_series(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myseries
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def toggle_my_feeds(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myfeeds
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def toggle_my_a_feeds(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myafeeds
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("audio")

    @cherrypy.expose
    @require_auth()
    def toggle_my_mags(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_mymags
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def toggle_my_comics(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_mycomics
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("comics")
