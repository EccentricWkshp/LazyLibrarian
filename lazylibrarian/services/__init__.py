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

""" What the web interface and the API do, without any web framework.

    Services take plain arguments and return plain data: dicts keyed by the database column
    names, lists of them, or a Page. They never touch cherrypy.request or cherrypy.response,
    render templates or build HTML, so the CherryPy pages and the FastAPI routes can share them.
    A service that can't do what it was asked raises one of the errors below, and the caller
    turns that into whatever its client expects.
"""


class ServiceError(Exception):
    """ Base for the errors a service reports to its caller """


class NotFoundError(ServiceError):
    """ The record asked for doesn't exist """


class InvalidRequestError(ServiceError):
    """ The arguments can't be acted on, the message says why """
