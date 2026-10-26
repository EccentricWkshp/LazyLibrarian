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

""" The cover walls """

import cherrypy

from lazylibrarian import i18n
from lazylibrarian.auth import require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import wall
from lazylibrarian.web.common import BasePages, serve_template


def top_title(title: str, items: list, more: bool) -> str:
    """ The wall title, saying it only shows the top ones when there were more """
    return i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': len(items)} if more else title


class WallPages(BasePages):
    """ The cover walls """

    @cherrypy.expose
    @require_auth()
    def mag_wall(self, title=''):
        self.label_thread('MAGWALL')
        title = title.replace('&amp;', '&') if title else title
        issues, more = wall.magazine_wall(title)
        if not issues:
            raise cherrypy.HTTPRedirect("magazines")
        return serve_template(templatename="coverwall.html", title=top_title(title, issues, more), results=issues,
                              redirect="magazines", columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def comic_wall(self, comicid=None):
        self.label_thread('COMICWALL')
        issues, more = wall.comic_wall(comicid)
        if not issues:
            raise cherrypy.HTTPRedirect("comics")
        return serve_template(templatename="coverwall.html", title=top_title('', issues, more), results=issues,
                              redirect="comic", columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def book_wall(self, have='0'):
        self.label_thread('BOOKWALL')
        books, more = wall.book_wall(downloaded=have == '1')
        if not books:
            raise cherrypy.HTTPRedirect("books")
        title = i18n.gettext('Recently Downloaded Books') if have == '1' else i18n.gettext('Recently Added Books')
        return serve_template(templatename="coverwall.html", title=top_title(title, books, more), results=books,
                              redirect="books", have=have, columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def author_wall(self, have='1'):
        self.label_thread('AUTHORWALL')
        authors = wall.author_wall(active=have == '1')
        if not authors:
            raise cherrypy.HTTPRedirect("authors")
        title = i18n.gettext('Active/Wanted Authors') if have == '1' else i18n.gettext('Inactive Authors')
        return serve_template(templatename="coverwall.html", title=title, results=authors, redirect="authors",
                              have=have, columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def audio_wall(self):
        self.label_thread('AUDIOWALL')
        books, more = wall.audio_wall()
        if not books:
            raise cherrypy.HTTPRedirect("audio")
        return serve_template(templatename="coverwall.html", title=top_title(i18n.gettext('Recent AudioBooks'), books, more),
                              results=books, redirect="audio", columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def wall_columns(self, redirect=None, count=None, have='', title=''):
        title = title.split(' (')[0].replace(' ', '+')
        if not have:
            have = '1' if 'Wanted' in title else '0'
        wall.change_columns(count)
        if redirect == 'audio':
            raise cherrypy.HTTPRedirect('audio_wall')
        if redirect == 'books':
            raise cherrypy.HTTPRedirect(f'book_wall?have={have}')
        if redirect == 'magazines':
            if title:
                raise cherrypy.HTTPRedirect(f'mag_wall?title={title}')
            raise cherrypy.HTTPRedirect('mag_wall')
        if redirect == 'comic':
            if title:
                raise cherrypy.HTTPRedirect(f'comic_wall?comicid={title}')
            raise cherrypy.HTTPRedirect('comic_wall')
        if redirect == 'authors':
            raise cherrypy.HTTPRedirect(f'author_wall?have={have}')
        raise cherrypy.HTTPRedirect('home')
