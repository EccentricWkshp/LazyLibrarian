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

import os

import cherrypy

from lazylibrarian import database, i18n
from lazylibrarian.auth import require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, path_isfile, splitext
from lazylibrarian.formatter import check_int
from lazylibrarian.images import createthumb
from lazylibrarian.web.common import BasePages, serve_template


class WallPages(BasePages):
    """ The cover walls """

    @cherrypy.expose
    @require_auth()
    def mag_wall(self, title=''):
        self.label_thread('MAGWALL')
        cmd = "SELECT IssueFile,IssueID,IssueDate,Title,Cover from issues"
        args = None
        if title:
            title = title.replace('&amp;', '&')
            cmd += " WHERE Title=?"
            args = (title,)
        cmd += " order by IssueAcquired DESC"
        db = database.DBConnection()
        try:
            issues = db.select(cmd, args)
        finally:
            db.close()
        if not len(issues):
            raise cherrypy.HTTPRedirect("magazines")
        mod_issues = []
        maxcount = CONFIG.get_int('MAX_WALL')
        for count, issue in enumerate(issues, start=1):
            this_issue = dict(issue)
            if not this_issue.get('Cover') or not this_issue['Cover'].startswith('cache/'):
                this_issue['Cover'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(this_issue['Cover'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    this_issue['Cover'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, this_issue['Cover'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        this_issue['Cover'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            this_issue['Title'] = issue['Title'].replace('&amp;', '&')
            mod_issues.append(this_issue)
            if maxcount and count >= maxcount:
                title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': count}
                break

        return serve_template(
            templatename="coverwall.html", title=title, results=mod_issues, redirect="magazines",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def comic_wall(self, comicid=None):
        self.label_thread('COMICWALL')
        cmd = ("SELECT IssueFile,IssueID,comics.ComicID,Title,Cover from comicissues,comics WHERE "
               "comics.ComicID = comicissues.ComicID")
        args = None
        if comicid:
            cmd += " AND comics.ComicID=?"
            args = (comicid,)
        cmd += " order by IssueAcquired DESC"
        db = database.DBConnection()
        try:
            issues = db.select(cmd, args)
        finally:
            db.close()
        title = ''
        if not len(issues):
            raise cherrypy.HTTPRedirect("comics")
        mod_issues = []
        maxcount = CONFIG.get_int('MAX_WALL')
        for count, issue in enumerate(issues, start=1):
            this_issue = dict(issue)
            if not this_issue.get('Cover') or not this_issue['Cover'].startswith('cache/'):
                this_issue['Cover'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(this_issue['Cover'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    this_issue['Cover'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, this_issue['Cover'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        this_issue['Cover'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            mod_issues.append(this_issue)
            if maxcount and count >= maxcount:
                title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': count}
                break

        return serve_template(
            templatename="coverwall.html", title=title, results=mod_issues, redirect="comic",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def book_wall(self, have='0'):
        self.label_thread('BOOKWALL')
        if have == '1':
            cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status='Open' order by BookLibrary DESC"
            title = i18n.gettext('Recently Downloaded Books')
        else:
            cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status != 'Ignored' order by BookAdded DESC"
            title = i18n.gettext('Recently Added Books')
        db = database.DBConnection()
        try:
            results = db.select(cmd)
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("books")
        maxcount = CONFIG.get_int('MAX_WALL')
        if maxcount and len(results) > maxcount:
            results = results[:maxcount]
            title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': len(results)}
        ret = []
        for result in results:
            itm = dict(result)
            if not itm['BookLink']:
                itm['BookLink'] = ''
            elif itm['BookLink'].startswith('/works/OL'):
                itm['BookLink'] = CONFIG['OL_URL'] + itm['BookLink']

            if not itm.get('BookImg') or not itm['BookImg'].startswith('cache/'):
                itm['BookImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['BookImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['BookImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['BookImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['BookImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="books", have=have,
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def author_wall(self, have='1'):
        self.label_thread('AUTHORWALL')
        cmd = "SELECT Status,AuthorImg,AuthorID,AuthorName,HaveBooks,TotalBooks from authors "
        if have == '1':
            cmd += "where Status='Active' or Status='Wanted' order by AuthorName ASC"
            title = i18n.gettext('Active/Wanted Authors')
        else:
            cmd += "where Status !='Active' and Status != 'Wanted' order by AuthorName ASC"
            title = i18n.gettext('Inactive Authors')
        db = database.DBConnection()
        try:
            results = db.select(cmd)
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("authors")

        ret = []
        for result in results:
            itm = dict(result)
            if not itm.get('AuthorImg') or not itm['AuthorImg'].startswith('cache/'):
                itm['AuthorImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['AuthorImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['AuthorImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['AuthorImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['AuthorImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="authors", have=have,
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def audio_wall(self):
        self.label_thread('AUDIOWALL')
        db = database.DBConnection()
        try:
            results = db.select(
                'SELECT AudioFile,BookImg,BookID,BookName from books '
                'where AudioStatus="Open" order by AudioLibrary DESC')
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("audio")
        title = i18n.gettext('Recent AudioBooks')
        maxcount = CONFIG.get_int('MAX_WALL')
        if maxcount and len(results) > maxcount:
            results = results[:maxcount]
            title = i18n.gettext('%(title)s (Top %(count)s)') % {'title': title, 'count': len(results)}
        ret = []
        for result in results:
            itm = dict(result)
            if not itm.get('BookImg') or not itm['BookImg'].startswith('cache/'):
                itm['BookImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['BookImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['BookImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['BookImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['BookImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="audio",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def wall_columns(self, redirect=None, count=None, have='', title=''):
        title = title.split(' (')[0].replace(' ', '+')
        if not have:
            have = '1' if 'Wanted' in title else '0'
        columns = check_int(CONFIG.get_int('WALL_COLUMNS'), 6)
        if count == 'up' and columns <= 12:
            columns += 1
        elif count == 'down' and columns > 1:
            columns -= 1
        CONFIG.set_int('WALL_COLUMNS', columns)
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
