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
import re
import time
from urllib.parse import quote, unquote

import cherrypy
from cherrypy.lib.static import serve_file

import lazylibrarian
from lazylibrarian import database, i18n, notifiers
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.bookrename import name_vars
from lazylibrarian.cache import ImageType, cache_img
from lazylibrarian.common import mime_type, zip_audio
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, listdir, path_isfile, splitext, syspath
from lazylibrarian.formatter import check_int, get_list, plural
from lazylibrarian.images import createthumb
from lazylibrarian.web.common import BasePages, serve_template


class FilePages(BasePages):
    """ Serving, opening and emailing book, audiobook, magazine and comic files and images """

    @cherrypy.expose
    @require_auth()
    def serve_comic(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Comic [{feedid}]")
        return self.serve_item(feedid, "comic")

    @cherrypy.expose
    @require_auth()
    def serve_img(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Image [{feedid}]")
        return self.serve_item(feedid, "img")

    @cherrypy.expose
    @require_auth()
    def serve_book(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Book [{feedid}]")
        return self.serve_item(feedid, "book")

    @cherrypy.expose
    @require_auth()
    def serve_audio(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Audio [{feedid}]")
        return self.serve_item(feedid, "audio")

    @cherrypy.expose
    @require_auth()
    def serve_issue(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Issue [{feedid}]")
        return self.serve_item(feedid, "issue")

    @cherrypy.expose
    @require_auth()
    def serve_item(self, feedid, ftype):
        logger = logging.getLogger(__name__)
        userid = feedid[:10]
        itemid = feedid[10:]
        itemid = itemid.split('.')[0]  # discard any extension
        if len(userid) != 10:
            logger.debug(f"Invalid userID [{userid}]")
            return None

        target = ''

        size = re.search(r'_w\d+$', itemid)
        if size:
            size = check_int(size.group()[2:], 0)
            itemid = itemid[:-5]
        else:
            size = 0

        db = database.DBConnection()
        res = db.match('SELECT UserName,Perms,BookType from users where UserID=?', (userid,))
        if res:
            perm = check_int(res['Perms'], 0)
            preftype = res['BookType']
        else:
            logger.debug(f"Invalid userID [{userid}]")
            return None

        if not perm & lazylibrarian.perm_download:
            logger.debug(f"Insufficient permissions for userID [{userid}]")
            return None

        if ftype == 'img':
            if itemid:
                res = db.match('SELECT BookName,BookImg from books WHERE BookID=?', (itemid,))
                if res:
                    logger.debug(f"Itemid {itemid} matches ebook")
                    bookimg = res['BookImg']
                    if bookimg and bookimg.startswith('http'):
                        # external URL (set by e.g. googlebooks import) - cache it,
                        # point the row at the cached file and serve that, instead
                        # of silently falling through to the app logo
                        link, ok, _ = cache_img(ImageType.BOOK, itemid, bookimg)
                        if ok:
                            db.action("UPDATE books SET BookImg=? WHERE BookID=?",
                                      (link, itemid))
                            logger.info(f"Cached external cover for {itemid} from {bookimg}")
                            bookimg = link
                    if size:
                        target = createthumb(os.path.join(DIRS.DATADIR, bookimg), size, False)
                    if not target:
                        target = os.path.join(DIRS.DATADIR, bookimg)
                    if path_isfile(target):
                        return self.send_file(target, name=res['BookName'] + splitext(bookimg)[1])
                else:
                    res = db.match('SELECT Title,Cover from issues WHERE IssueID=?', (itemid,))
                    if res:
                        logger.debug(f"Itemid {itemid} matches issue")
                        if size:
                            target = createthumb(os.path.join(DIRS.DATADIR, res['Cover']), size, False)
                        if not target:
                            target = os.path.join(DIRS.DATADIR, res['Cover'])
                        if path_isfile(target):
                            return self.send_file(target, name=res['Title'] + splitext(res['Cover'])[1])
                    else:
                        try:
                            comicid, issueid = itemid.split('_')
                            cmd = ("SELECT Title,Cover from comics,comicissues WHERE "
                                   "comics.ComicID=comicissues.ComicID and comics.ComicID=? and IssueID=?")
                            res = db.match(cmd, (comicid, issueid))
                        except (IndexError, ValueError):
                            res = None
                        if res:
                            logger.debug(f"Itemid {itemid} matches comicid")
                            if size:
                                target = createthumb(os.path.join(DIRS.DATADIR, res['Cover']), size, False)
                            if not target:
                                target = os.path.join(DIRS.DATADIR, res['Cover'])
                            if path_isfile(target):
                                return self.send_file(target, name=res['Title'] + splitext(res['Cover'])[1])

            logger.debug(f"Itemid {itemid} no match")
            target = os.path.join(DIRS.PROG_DIR, 'data', 'images', 'll192.png')
            if path_isfile(target):
                return self.send_file(target, name='lazylibrarian.png')

        elif ftype == 'comic':
            try:
                comicid, issueid = itemid.split('_')
                cmd = ("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                       "and comics.ComicID=? and IssueID=?")
                res = db.match(cmd, (comicid, issueid))
            except (IndexError, ValueError):
                res = None
                issueid = 0

            if res:
                target = res['IssueFile']
                if target and path_isfile(target):
                    logger.debug(f'Opening {ftype} {target}')
                    return self.send_file(target, name=f"{res['Title']} {issueid}{splitext(target)[1]}")

        elif ftype == 'audio':
            res = db.match('SELECT AudioFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                cnt = 0
                myfile = res['AudioFile']
                # count the audiobook parts
                if myfile and path_isfile(myfile):
                    parentdir = os.path.dirname(myfile)
                    for _, _, filenames in os.walk(parentdir):
                        for filename in filenames:
                            if CONFIG.is_valid_booktype(filename, 'audiobook'):
                                cnt += 1

                if cnt > 1 and not CONFIG.get_bool('RSS_PODCAST'):
                    target = zip_audio(os.path.dirname(myfile), res['BookName'], itemid)
                    if target and path_isfile(target):
                        logger.debug(f'Opening {ftype} {target}')
                        return self.send_file(target, name=res['BookName'] + '.zip')

                if myfile and path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile)

        elif ftype == 'book':
            res = db.match('SELECT BookFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                myfile = res['BookFile']
                fname, extn = splitext(myfile)
                types = []
                for itm in get_list(CONFIG['EBOOK_TYPE']):
                    target = fname + '.' + itm
                    if path_isfile(target):
                        types.append(itm)

                # serve user preferred type if available, or system preferred type
                if preftype and preftype in types:
                    extn = preftype
                else:
                    extn = types[0]
                myfile = fname + '.' + extn
                if path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile)

        elif ftype == 'issue':
            res = db.match('SELECT Title,IssueFile from issues WHERE IssueID=?', (itemid,))
            if res:
                myfile = res['IssueFile']
                if myfile and path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile, name=f"{res['Title']} {itemid}{splitext(myfile)[1]}")
        db.close()
        logger.warning(f"No file found for {ftype} {itemid}")
        return None

    @cherrypy.expose
    @require_auth()
    def send_book(self, bookid=None, library=None, redirect=None, booktype=None):
        return self.open_book(bookid=bookid, library=library, redirect=redirect, booktype=booktype, email=True)

    @cherrypy.expose
    @require_auth()
    def open_book(self, bookid=None, library=None, redirect=None, booktype=None, email=False):
        logger = logging.getLogger(__name__)
        adminlogger = logging.getLogger('special.admin')
        adminlogger.debug(f"{bookid} {library} {redirect} {booktype} {email}")
        self.label_thread('OPEN_BOOK')
        # we need to check the user priveleges and see if they can download the book
        db = database.DBConnection()
        perm = lazylibrarian.perm_admin
        preftype = ''
        res = db.match('SELECT BookType from users where UserID=?', (owner_id(),))
        if res:
            preftype = res['BookType'] or ''

        if booktype is not None:
            preftype = booktype

        apisources = []
        for i in lazylibrarian.INFOSOURCES.keys():
            # source, authorid, bookid
            infosource = lazylibrarian.INFOSOURCES[i]
            apisources.append([infosource, infosource['author_key'], infosource['book_key']])

        bookid_key = 'BookID'
        for itm in apisources:
            if CONFIG['BOOK_API'] == itm[0]:
                bookid_key = itm[2]
                break

        cmd = (f"SELECT BookFile,AudioFile,AuthorName,BookName from books,authors WHERE books.{bookid_key}=? or "
               "BookID=? and books.AuthorID = authors.AuthorID")
        bookdata = db.match(cmd, (bookid, bookid))
        db.close()
        if not bookdata:
            logger.warning(f'Missing bookid: {bookid}')
        else:
            if perm & lazylibrarian.perm_download:
                author_name = bookdata["AuthorName"]
                book_name = bookdata["BookName"]
                if library == 'AudioBook':
                    bookfile = bookdata["AudioFile"]
                    if bookfile and path_isfile(bookfile):
                        parentdir = os.path.dirname(bookfile)
                        namevars = name_vars(bookid)
                        singlename = namevars['AudioSingleFile']
                        singlefile = ''
                        # noinspection PyBroadException
                        try:
                            for fname in listdir(parentdir):
                                if CONFIG.is_valid_booktype(fname, booktype='audio'):
                                    bname, extn = splitext(fname)
                                    if bname == singlename:
                                        # found name matching the AudioSingleFile
                                        singlefile = os.path.join(parentdir, fname)
                                        break
                        except Exception:
                            pass

                        if booktype == 'whole' and singlefile and path_isfile(singlefile):
                            if email:
                                logger.debug(f'Emailing {library} {singlefile}')
                            else:
                                logger.debug(f'Opening {library} {singlefile}')
                            return self.send_file(singlefile, name=os.path.basename(singlefile), email=email)

                        index = os.path.join(parentdir, 'playlist.ll')
                        if path_isfile(index):
                            if booktype == 'zip':
                                zipfile = zip_audio(parentdir, book_name, bookid)
                                if zipfile and path_isfile(zipfile):
                                    if email:
                                        logger.debug(f'Emailing {library} {zipfile}')
                                    else:
                                        logger.debug(f'Opening {library} {zipfile}')
                                    return self.send_file(zipfile, name=f'{book_name}.zip', email=email)
                            idx = check_int(booktype, 0)
                            if idx:
                                with open(syspath(index)) as f:
                                    part = f.read().splitlines()[idx - 1]
                                bookfile = os.path.join(parentdir, part)
                                if bookfile and path_isfile(bookfile):
                                    if email:
                                        logger.debug(f'Emailing {library} {bookfile}')
                                    else:
                                        logger.debug(f'Opening {library} {bookfile}')
                                    return self.send_file(bookfile, name=f"{book_name} "
                                                                         f"part{idx}{splitext(bookfile)[1]}",
                                                          email=email)
                            with open(index) as fp:
                                cnt = sum(1 for _ in fp)
                            if cnt <= 1:
                                if email:
                                    logger.debug(f'Emailing {library} {bookfile}')
                                else:
                                    logger.debug(f'Opening {library} {bookfile}')
                                return self.send_file(bookfile, email=email)
                            if email:
                                msg = i18n.gettext("Please select which part to email")
                            else:
                                msg = i18n.gettext("Please select which part to download")
                            itm = 1
                            partlist = ''
                            while itm <= cnt:
                                if partlist:
                                    partlist += ' '
                                partlist += str(itm)
                                itm += 1
                                partlist += ' zip'
                                if singlefile and path_isfile(singlefile):
                                    partlist += ' whole'
                            safetitle = book_name.replace('&', '&amp;').replace("'", "")

                            return serve_template(templatename="choosetype.html",
                                                  title=safetitle, pop_message=msg,
                                                  pop_types=partlist, bookid=bookid,
                                                  valid=get_list(partlist.replace(' ', ',')),
                                                  email=email)
                        if email:
                            logger.debug(f'Emailing {library} {bookfile}')
                        else:
                            logger.debug(f'Opening {library} {bookfile}')
                        return self.send_file(bookfile, email=email)

                library = 'eBook'
                bookfile = bookdata["BookFile"]
                if bookfile and path_isfile(bookfile):
                    fname, _ = splitext(bookfile)
                    types = []
                    for itm in get_list(CONFIG['EBOOK_TYPE']):
                        target = fname + '.' + itm
                        if path_isfile(target):
                            types.append(itm)
                    logger.debug(f'Preftype:{preftype} Available:{str(types)}')
                    if preftype and len(types):
                        if preftype in types:
                            bookfile = fname + '.' + preftype
                        else:
                            msg = f"{book_name}<br> "
                            typestr = ''
                            for itm in types:
                                if typestr:
                                    typestr += ' '
                                typestr += itm
                            msg += i18n.gettext("Not available as %(type)s, only %(types)s") % {
                                'type': preftype, 'types': typestr}
                            return serve_template(templatename="choosetype.html",
                                                  title=i18n.gettext("Not Available"), pop_message=msg,
                                                  pop_types=typestr, bookid=bookid,
                                                  valid=get_list(CONFIG['EBOOK_TYPE']),
                                                  email=email)
                    elif len(types) > 1:
                        if email:
                            msg = i18n.gettext("Please select format to email")
                        else:
                            msg = i18n.gettext("Please select format to download")
                        typestr = ''
                        for itm in types:
                            if typestr:
                                typestr += ' '
                            typestr += itm
                        return serve_template(templatename="choosetype.html",
                                              title=i18n.gettext("Choose Type"), pop_message=msg,
                                              pop_types=typestr, bookid=bookid,
                                              valid=get_list(CONFIG['EBOOK_TYPE']),
                                              email=email)
                    if len(types) and bookfile and path_isfile(bookfile):
                        if email:
                            logger.debug(f'Emailing {library} {bookfile}')
                            return self.send_file(bookfile, name=book_name, email=email)
                        logger.debug(f'Opening {library} {bookfile}')
                        return self.send_file(bookfile, email=email)
                    logger.debug(f'Unable to send {library} {book_name}, no valid types?')

                logger.info(f'Missing {library} {author_name}, {book_name} [{bookfile}]')
                if library == 'AudioBook':
                    raise cherrypy.HTTPRedirect("audio")
                raise cherrypy.HTTPRedirect("books")
            return self.request_book(library=library, bookid=bookid, redirect=redirect)

        if library == 'AudioBook':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def open_comic(self, comicid=None, issueid=None):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            if comicid and '_' in comicid:
                comicid = comicid.split('_')[0]

            # we may want to open an issue with an issueid
            if comicid and issueid:
                cmd = ("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID and "
                       "comics.ComicID=? and IssueID=?")
                iss_data = db.match(cmd, (comicid, issueid))
                if iss_data:
                    issue_file = iss_data["IssueFile"]
                    if issue_file and path_isfile(issue_file):
                        logger.debug(f'Opening file {issue_file}')
                        return self.send_file(issue_file, name=f"{iss_data['Title']} {issueid}"
                                                               f"{splitext(issue_file)[1]}")

            # or we may just have a comicid to find comic in comicissues table
            cmd = ("SELECT Title,IssueFile,IssueID from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                   "and comics.ComicID=?")
            iss_data = db.select(cmd, (comicid,))
        finally:
            db.close()
        if len(iss_data) == 0:
            logger.warning(f"No issues for comic {comicid}")
            raise cherrypy.HTTPRedirect("comics")

        if len(iss_data) == 1 and CONFIG.get_bool('COMIC_SINGLE'):  # we only have one issue, get it
            title = iss_data[0]["Title"]
            issue_id = iss_data[0]["IssueID"]
            issue_file = iss_data[0]["IssueFile"]
            if issue_file and path_isfile(issue_file):
                logger.debug(f'Opening {comicid} - {issue_id}')
                return self.send_file(issue_file, name=f"{title} {issue_id}{splitext(issue_file)[1]}")
            logger.warning(f"No issue {issue_id} for comic {title}")
            raise cherrypy.HTTPError(404, f"Comic Issue {issue_id} not found for {title}")

        # multiple issues, show a list
        logger.debug(f"{comicid} has {len(iss_data)} {plural(len(iss_data), 'issue')}")
        raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")

    @cherrypy.expose
    @require_auth()
    def send_mag(self, bookid=None):
        return self.open_mag(bookid=bookid, email=True)

    @cherrypy.expose
    @require_auth()
    def open_mag(self, bookid=None, email=False):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            # we may want to open an issue with a hashed bookid
            mag_data = db.match('SELECT * from issues WHERE IssueID=?', (bookid,))
            if mag_data:
                issue_file = mag_data["IssueFile"]
                if issue_file and path_isfile(issue_file):
                    if email:
                        logger.debug(f'Emailing file {issue_file}')
                    else:
                        logger.debug(f'Opening file {issue_file}')
                    return self.send_file(issue_file, name=f"{mag_data['Title']} {mag_data['IssueDate']}"
                                                           f"{splitext(issue_file)[1]}", email=email)

            # or we may just have a title to find magazine in issues table
            mag_data = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (unquote(bookid),))
            if not mag_data:
                logger.warning(f"Unknown magazine title: {bookid}")
                raise cherrypy.HTTPError(404, f"Magazine {bookid} not found")
            bookid = mag_data['Title']
            mag_data = db.select('SELECT * from issues WHERE Title=? COLLATE NOCASE', (bookid,))
        finally:
            db.close()

        if len(mag_data) == 1 and CONFIG.get_bool('MAG_SINGLE'):  # we only have one issue, get it
            issue_date = mag_data[0]["IssueDate"]
            issue_file = mag_data[0]["IssueFile"]
            if issue_file and path_isfile(issue_file):
                if email:
                    logger.debug(f'Emailing {bookid} - {issue_date}')
                else:
                    logger.debug(f'Opening {bookid} - {issue_date}')
                return self.send_file(issue_file, name=f"{bookid} {issue_date}{splitext(issue_file)[1]}",
                                      email=email)
            logger.warning(f"No issue {issue_date} for magazine {bookid}")
            raise cherrypy.HTTPRedirect("magazines")
        if len(mag_data) == 0:
            logger.warning(f"No issues found for magazine {bookid}")
            raise cherrypy.HTTPRedirect("magazines")
        # multiple issues, show a list
        logger.debug(f"{bookid} has {len(mag_data)} {plural(len(mag_data), 'issue')}")
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(bookid)}")

    def send_file(self, myfile, name=None, email=False):
        logger = logging.getLogger(__name__)
        userid = owner_id()
        if userid:
            msg = ''
            if email and userid:
                db = database.DBConnection()
                res = db.match('SELECT UserName,SendTo from users where UserID=?', (userid,))
                db.close()
                if res and res['SendTo']:
                    db = database.DBConnection()
                    sent = []
                    not_sent = []
                    # sending files to kindles only seems to work if separate emails
                    if ',' in res['SendTo']:
                        addrs = get_list(res['SendTo'])
                    else:
                        addrs = [res['SendTo']]
                    for addr in addrs:
                        logger.debug(f"Emailing {myfile} to {addr}")
                        if name:
                            msg = lazylibrarian.NEWFILE_MSG.replace('{name}', name).replace(
                                '{method}', ' is attached').replace('{link}', '')
                        result = notifiers.email_notifier.email_file(subject="Message from LazyLibrarian",
                                                                     message=msg, to_addr=addr, files=[myfile])
                        if result:
                            db.action('INSERT into sent_file (WhenSent, UserID, Addr, FileName) VALUES (?, ?, ?, ?)',
                                      (str(int(time.time())), userid, addr, os.path.basename(myfile)))
                            sent.append(addr)
                        else:
                            not_sent.append(addr)
                    db.close()
                    msg = ''
                    if sent:
                        logger.debug(f"Emailed file {os.path.basename(myfile)} to {','.join(sent)}")
                        msg = i18n.gettext("Emailed file %(file)s to %(addresses)s") % {
                            'file': os.path.basename(myfile), 'addresses': ','.join(sent)} + ' '
                    if not_sent:
                        logger.error(f"Failed to email file {os.path.basename(myfile)} to {','.join(not_sent)}")
                        msg += i18n.gettext("Failed to email file %(file)s to %(addresses)s") % {
                            'file': os.path.basename(myfile), 'addresses': ','.join(not_sent)}
                return serve_template(templatename="choosetype.html", title=i18n.gettext('Send file'),
                                      pop_message=msg, pop_types='', bookid='', valid='', email=email)
        if not name:
            name = os.path.basename(myfile)
        if path_isfile(myfile):
            if userid:
                db = database.DBConnection()
                db.action('INSERT into sent_file (WhenSent, UserID, Addr, FileName) VALUES (?, ?, ?, ?)',
                          (str(int(time.time())), userid, 'Open', name))
                db.close()
            return serve_file(myfile, mime_type(myfile), "attachment", name=name)
        logger.error(f"No file [{myfile}]")
        return None
