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
from lazylibrarian import i18n
from lazylibrarian.auth import end_session, owner_id, require_auth, session_token
from lazylibrarian.common import pwd_generator
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, get_list
from lazylibrarian.services import InvalidRequestError, NotFoundError, users
from lazylibrarian.web.common import BasePages, clear_our_cookies, serve_template


class UserPages(BasePages):
    """ The owner's profile, subscriptions, feeds, help and logout """

    @cherrypy.expose
    @require_auth()
    def profile(self):
        try:
            found = users.get_profile(owner_id())
        except NotFoundError:
            return serve_template(templatename="index.html", title=i18n.gettext('Authors'), redirect='authors')
        subscriptions = '\n'.join(f"{s['Type']} {s['WantID']} {'(' + s['Name'] + ')' if s['Name'] else ''}"
                                  for s in found['subscriptions'])
        themelist = ['Default'] + ['bookstrap_' + itm for itm in lazylibrarian.BOOKSTRAP_THEMELIST]
        return serve_template(templatename="profile.html", title=i18n.gettext('User Profile'), user=found['user'],
                              subs=subscriptions, typelist=get_list(CONFIG['EBOOK_TYPE']), themelist=themelist)

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
            users.save_prefs(owner_id(), check_int(cookie['ll_prefs'].value, 0))
        end_session()
        clear_our_cookies()
        if cherrypy.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return "OK"
        root = CONFIG['HTTP_ROOT'].rstrip('/') if CONFIG['HTTP_ROOT'] else ''
        raise cherrypy.HTTPRedirect(f"{root}/auth/login")

    @cherrypy.expose
    @require_auth()
    def user_update(self, **kwargs):
        userid = owner_id()
        try:
            changes = users.update_profile(userid, kwargs, keep_token=session_token()) if userid else []
        except InvalidRequestError as e:
            return i18n.gettext(str(e))
        except NotFoundError:
            changes = []
        if changes:
            return i18n.gettext('Updated user details: %(fields)s') % {'fields': ' '.join(changes)}
        return i18n.gettext("No changes made")

    @cherrypy.expose
    @require_auth()
    def update_feeds(self, **kwargs):
        if 'value' in kwargs and kwargs['value'] == '':
            # cancel or [x] pressed
            return i18n.gettext('No changes made')
        kwargs.pop('user', None)
        selected = get_list(kwargs.pop('value[]', ''))
        feeds = {}
        for itm in kwargs:
            if '[text]' in itm:
                feedname = kwargs[itm]
                feednum = kwargs.get(itm.replace('[text]', '[value]'), '')
                if feedname and feednum:
                    feeds[feedname] = feednum in selected
        cnt = users.set_feeds(owner_id(), feeds)
        return i18n.ngettext('Changed %(count)s feed', 'Changed %(count)s feeds', cnt) % {'count': cnt}

    @cherrypy.expose
    @require_auth()
    def user_feeds(self, **kwargs):
        userid = owner_id()
        if not userid:
            return json.dumps({'feeds': '', 'value': ''})
        choices = users.feed_choices(userid)
        feedlist = [{'text': feed['name'], 'value': str(cnt)} for cnt, feed in enumerate(choices, start=1)]
        value = [str(cnt) for cnt, feed in enumerate(choices, start=1) if feed['subscribed']]
        res = json.dumps({'feeds': feedlist, 'value': value})
        logging.getLogger(__name__).debug(res)
        return res

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
