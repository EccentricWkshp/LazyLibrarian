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

""" Serving, opening and emailing book, audiobook, magazine and comic files and images """

import logging
import os
from urllib.parse import quote

import cherrypy
from cherrypy.lib.static import serve_file

from lazylibrarian import i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.common import mime_type
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import path_isfile
from lazylibrarian.formatter import get_list, plural
from lazylibrarian.services import NotFoundError, delivery, users
from lazylibrarian.web.common import BasePages, serve_template


class FilePages(BasePages):
    """ Serving, opening and emailing book, audiobook, magazine and comic files and images """

    @cherrypy.expose
    @require_auth()
    def serve_comic(self, feedid=None):
        logging.getLogger(__name__).debug(f"Serve Comic [{feedid}]")
        return self.serve_item(feedid, "comic")

    @cherrypy.expose
    @require_auth()
    def serve_img(self, feedid=None):
        logging.getLogger(__name__).debug(f"Serve Image [{feedid}]")
        return self.serve_item(feedid, "img")

    @cherrypy.expose
    @require_auth()
    def serve_book(self, feedid=None):
        logging.getLogger(__name__).debug(f"Serve Book [{feedid}]")
        return self.serve_item(feedid, "book")

    @cherrypy.expose
    @require_auth()
    def serve_audio(self, feedid=None):
        logging.getLogger(__name__).debug(f"Serve Audio [{feedid}]")
        return self.serve_item(feedid, "audio")

    @cherrypy.expose
    @require_auth()
    def serve_issue(self, feedid=None):
        logging.getLogger(__name__).debug(f"Serve Issue [{feedid}]")
        return self.serve_item(feedid, "issue")

    @cherrypy.expose
    @require_auth()
    def serve_item(self, feedid, ftype):
        found = delivery.feed_file(feedid, ftype)
        if not found:
            return None
        return self.send_file(found[0], name=found[1])

    @cherrypy.expose
    @require_auth()
    def send_book(self, bookid=None, library=None, redirect=None, booktype=None):
        return self.open_book(bookid=bookid, library=library, redirect=redirect, booktype=booktype, email=True)

    @cherrypy.expose
    @require_auth()
    def open_book(self, bookid=None, library=None, redirect=None, booktype=None, email=False):
        logger = logging.getLogger(__name__)
        logging.getLogger('special.admin').debug(f"{bookid} {library} {redirect} {booktype} {email}")
        self.label_thread('OPEN_BOOK')
        # the owner can always download, lazylibrarian.perm_admin includes perm_download
        try:
            found = delivery.book_to_open(bookid, library, booktype, users.preferred_type(owner_id()))
        except NotFoundError:
            raise cherrypy.HTTPRedirect("audio" if library == 'AudioBook' else "books") from None
        action = found['action']
        if action == 'send':
            logger.debug(f"{'Emailing' if email else 'Opening'} {found['library']} {found['path']}")
            name = found['title'] if found.get('ebook') and email else found['name']
            return self.send_file(found['path'], name=name, email=email)
        if action == 'parts':
            msg = i18n.gettext("Please select which part to email") if email else \
                i18n.gettext("Please select which part to download")
            partlist = ''
            for itm in range(1, found['count'] + 1):
                if partlist:
                    partlist += ' '
                partlist += f"{itm} zip"
                if found['whole']:
                    partlist += ' whole'
            return serve_template(templatename="choosetype.html", title=found['title'].replace('&', '&amp;').replace(
                "'", ""), pop_message=msg, pop_types=partlist, bookid=bookid,
                valid=get_list(partlist.replace(' ', ',')), email=email)
        if action == 'formats':
            typestr = ' '.join(found['formats'])
            if found['unavailable']:
                msg = f"{found['title']}<br> " + i18n.gettext("Not available as %(type)s, only %(types)s") % {
                    'type': found['unavailable'], 'types': typestr}
                title = i18n.gettext("Not Available")
            else:
                msg = i18n.gettext("Please select format to email") if email else \
                    i18n.gettext("Please select format to download")
                title = i18n.gettext("Choose Type")
            return serve_template(templatename="choosetype.html", title=title, pop_message=msg, pop_types=typestr,
                                  bookid=bookid, valid=get_list(CONFIG['EBOOK_TYPE']), email=email)
        raise cherrypy.HTTPRedirect("audio" if found['library'] == 'AudioBook' else "books")

    @cherrypy.expose
    @require_auth()
    def open_comic(self, comicid=None, issueid=None):
        logger = logging.getLogger(__name__)
        try:
            found = delivery.comic_to_open(comicid, issueid)
        except NotFoundError as e:
            logger.warning(str(e))
            raise cherrypy.HTTPRedirect("comics") from None
        if found['action'] == 'send':
            logger.debug(f"Opening file {found['path']}")
            return self.send_file(found['path'], name=found['name'])
        if found['action'] == 'missing':
            logger.warning(f"No issue {found['issueid']} for comic {found['title']}")
            raise cherrypy.HTTPError(404, f"Comic Issue {found['issueid']} not found for {found['title']}")
        # multiple issues, show a list
        logger.debug(f"{found['comicid']} has {found['count']} {plural(found['count'], 'issue')}")
        raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={found['comicid']}")

    @cherrypy.expose
    @require_auth()
    def send_mag(self, bookid=None):
        return self.open_mag(bookid=bookid, email=True)

    @cherrypy.expose
    @require_auth()
    def open_mag(self, bookid=None, email=False):
        logger = logging.getLogger(__name__)
        try:
            found = delivery.magazine_to_open(bookid)
        except NotFoundError as e:
            logger.warning(f"Unknown magazine title: {bookid}")
            raise cherrypy.HTTPError(404, str(e)) from None
        if found['action'] == 'send':
            logger.debug(f"{'Emailing' if email else 'Opening'} file {found['path']}")
            return self.send_file(found['path'], name=found['name'], email=email)
        if found['action'] == 'missing':
            if found['issuedate'] is None:
                logger.warning(f"No issues found for magazine {found['title']}")
            else:
                logger.warning(f"No issue {found['issuedate']} for magazine {found['title']}")
            raise cherrypy.HTTPRedirect("magazines")
        # multiple issues, show a list
        logger.debug(f"{found['title']} has {found['count']} {plural(found['count'], 'issue')}")
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(found['title'])}")

    @staticmethod
    def send_file(myfile, name=None, email=False):
        userid = owner_id()
        if userid and email:
            msg = ''
            sent, not_sent = delivery.email_file(userid, myfile, name)
            filename = os.path.basename(myfile)
            if sent:
                msg = i18n.gettext("Emailed file %(file)s to %(addresses)s") % {
                    'file': filename, 'addresses': ','.join(sent)} + ' '
            if not_sent:
                msg += i18n.gettext("Failed to email file %(file)s to %(addresses)s") % {
                    'file': filename, 'addresses': ','.join(not_sent)}
            return serve_template(templatename="choosetype.html", title=i18n.gettext('Send file'),
                                  pop_message=msg, pop_types='', bookid='', valid='', email=email)
        if not name:
            name = os.path.basename(myfile)
        if path_isfile(myfile):
            if userid:
                delivery.record_sent(userid, 'Open', name)
            return serve_file(myfile, mime_type(myfile), "attachment", name=name)
        logging.getLogger(__name__).error(f"No file [{myfile}]")
        return None

