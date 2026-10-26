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

""" The web interface, put together from the page classes in lazylibrarian/web """

import logging

import cherrypy

from lazylibrarian.auth import AuthController, require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.web.authors import AuthorPages
from lazylibrarian.web.books import BookPages
from lazylibrarian.web.comics import ComicPages
from lazylibrarian.web.common import BasePages
from lazylibrarian.web.connection_tests import ConnectionTestPages
from lazylibrarian.web.files import FilePages
from lazylibrarian.web.history import HistoryPages
from lazylibrarian.web.magazines import MagazinePages
from lazylibrarian.web.series import SeriesPages
from lazylibrarian.web.settings import SettingsPages
from lazylibrarian.web.system import SystemPages
from lazylibrarian.web.users import UserPages
from lazylibrarian.web.wall import WallPages


class WebInterface(UserPages, SeriesPages, SettingsPages, ConnectionTestPages, AuthorPages,
                   BookPages, FilePages, WallPages, ComicPages, MagazinePages, HistoryPages,
                   SystemPages, BasePages):
    """ The web interface CherryPy serves, each page class in lazylibrarian/web adds its URLs """
    _cp_config = {'tools.ui_language.on': True}

    auth = AuthController()

    @cherrypy.expose
    @require_auth()
    def index(self):
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    def login(self):
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    def home(self):
        logger = logging.getLogger(__name__)
        home = CONFIG.get_str('HOMEPAGE')
        logger.debug(f"Homepage [{home}]")
        if home == 'eBooks':
            raise cherrypy.HTTPRedirect("books")
        if home == 'Series':
            raise cherrypy.HTTPRedirect("series")
        if home == 'AudioBooks':
            raise cherrypy.HTTPRedirect("audio")
        if home == 'Magazines':
            raise cherrypy.HTTPRedirect("magazines")
        if home == 'Comics':
            raise cherrypy.HTTPRedirect("comics")
        raise cherrypy.HTTPRedirect("authors")
