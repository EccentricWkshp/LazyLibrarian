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

import cherrypy

from lazylibrarian import i18n
from lazylibrarian.auth import require_auth, session_token
from lazylibrarian.config2 import CONFIG
from lazylibrarian.configtypes import ConfigBool
from lazylibrarian.services import InvalidRequestError, settings
from lazylibrarian.web.common import BasePages, browser_languages, serve_template


class SettingsPages(BasePages):
    """ The settings page, saving it, API keys, info source API changes and Goodreads authorisation """

    @cherrypy.expose
    @require_auth()
    def save_filters(self):
        self.label_thread('WEBSERVER')
        return settings.export_magazine_filters()

    @cherrypy.expose
    @require_auth()
    def load_filters(self):
        self.label_thread('WEBSERVER')
        return settings.import_magazine_filters()

    @cherrypy.expose
    @require_auth()
    def config(self):
        self.label_thread('CONFIG')
        config = settings.page_data(browser_languages())
        for itm in CONFIG.config.values():
            if isinstance(itm, ConfigBool):
                itm.reset_read_count()  # Reset read counts as we use this to determine which settings have changed
        return serve_template(templatename="config.html", title=i18n.gettext("Settings"), config=config)

    @cherrypy.expose
    @require_auth()
    def config_update(self, **kwargs):
        """ Update config based on settings in the UI """
        messages = settings.save_form(kwargs, keep_token=session_token())
        if messages:
            return serve_template(templatename="response.html", prefix="", title=i18n.gettext("Access Control"),
                                  message=''.join(i18n.gettext(msg) + '<br>' for msg in messages), timer=0)
        raise cherrypy.HTTPRedirect("config")

    @staticmethod
    def source_changed(setting, value):
        try:
            return settings.set_source(setting, value)
        except InvalidRequestError as e:
            raise cherrypy.HTTPError(404, str(e)) from None

    @cherrypy.expose
    @require_auth()
    def ol_api_changed(self, **kwargs):
        # ol_api is true/false, not an api key
        return self.source_changed('OL_API', kwargs['status'])

    @cherrypy.expose
    @require_auth()
    def dnb_api_changed(self, **kwargs):
        return self.source_changed('DNB_API', kwargs['status'])

    @cherrypy.expose
    @require_auth()
    def bn_api_changed(self, **kwargs):
        return self.source_changed('BN_API', kwargs['status'])

    @cherrypy.expose
    @require_auth()
    def dbk_api_changed(self, **kwargs):
        return self.source_changed('DBK_API', kwargs['status'])

    @cherrypy.expose
    @require_auth()
    def ran_api_changed(self, **kwargs):
        return self.source_changed('RAN_API', kwargs['status'])

    @cherrypy.expose
    @require_auth()
    def hc_api_changed(self, **kwargs):
        return self.source_changed('HC_API', kwargs['status'])

    @cherrypy.expose
    @require_auth()
    def gr_api_changed(self, **kwargs):
        return self.source_changed('GR_API', kwargs['gr_api'])

    @cherrypy.expose
    @require_auth()
    def gb_api_changed(self, **kwargs):
        return self.source_changed('GB_API', kwargs['gb_api'])

    @cherrypy.expose
    @require_auth()
    def book_api_changed(self, **kwargs):
        return settings.set_book_api(kwargs['book_api'])

    @cherrypy.expose
    @require_auth()
    def grauth_step1(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        try:
            return settings.goodreads_auth_start(kwargs.get('gr_api'), kwargs.get('gr_secret'))
        except InvalidRequestError as e:
            raise cherrypy.HTTPError(404, str(e)) from None

    @cherrypy.expose
    @require_auth()
    def grauth_step2(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        return settings.goodreads_auth_finish()

    @cherrypy.expose
    @require_auth()
    def generate_ro_api(self):
        return self.generate_api(ro=True)

    @cherrypy.expose
    @require_auth()
    def generate_api(self, ro=False):
        return settings.new_api_key(read_only=bool(ro))

    @cherrypy.expose
    @require_auth()
    def set_current_tabs(self, **kwargs):
        if 'config_tab' in kwargs:
            settings.set_settings_tab(kwargs['config_tab'])
