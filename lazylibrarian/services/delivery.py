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

""" Giving the user their library's files: which file to open for a book, audiobook, issue or comic,
    the files behind the feed links, and emailing files """

import logging
import os
import re
import time

import lazylibrarian
from lazylibrarian import database, notifiers
from lazylibrarian.bookrename import name_vars
from lazylibrarian.cache import ImageType, cache_img
from lazylibrarian.common import zip_audio
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, listdir, path_isfile, splitext, syspath
from lazylibrarian.formatter import check_int, get_list
from lazylibrarian.images import createthumb
from lazylibrarian.services import NotFoundError

FEED_TYPES = ('img', 'comic', 'audio', 'book', 'issue')


def ebook_formats(bookfile) -> list[str]:
    """ The formats a book file is there in, next to it with the same name, in EBOOK_TYPE order """
    fname, _ = splitext(bookfile)
    return [itm for itm in get_list(CONFIG['EBOOK_TYPE']) if path_isfile(fname + '.' + itm)]


def picture(cover, size: int) -> str:
    """ A picture in the data folder, as a thumbnail size wide if size is given and one can be made """
    target = createthumb(os.path.join(DIRS.DATADIR, cover), size, False) if size else ''
    return target or os.path.join(DIRS.DATADIR, cover)


def feed_file(feedid: str, ftype: str) -> tuple[str, str | None] | None:
    """ The file behind a feed link: feedid is the user's id then the item's (a book, issue or
        comicid_issueid), with _w and a width for a smaller picture. ftype is one of FEED_TYPES.
        Returns (path, name to give it, None for its own), None if the user can't download or there's no file """
    logger = logging.getLogger(__name__)
    userid = feedid[:10]
    itemid = feedid[10:].split('.')[0]  # discard any extension
    if len(userid) != 10:
        logger.debug(f"Invalid userID [{userid}]")
        return None
    size = re.search(r'_w\d+$', itemid)
    if size:
        size = check_int(size.group()[2:], 0)
        itemid = itemid[:-5]
    else:
        size = 0

    db = database.DBConnection()
    try:
        user = db.match('SELECT UserName,Perms,BookType from users where UserID=?', (userid,))
        if not user:
            logger.debug(f"Invalid userID [{userid}]")
            return None
        if not check_int(user['Perms'], 0) & lazylibrarian.perm_download:
            logger.debug(f"Insufficient permissions for userID [{userid}]")
            return None
        found = None
        if ftype == 'img':
            found = feed_picture(db, itemid, size)
        elif ftype == 'comic':
            try:
                comicid, issueid = itemid.split('_')
                res = db.match("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                               "and comics.ComicID=? and IssueID=?", (comicid, issueid))
            except (IndexError, ValueError):
                res = None
            if res and res['IssueFile'] and path_isfile(res['IssueFile']):
                found = res['IssueFile'], f"{res['Title']} {issueid}{splitext(res['IssueFile'])[1]}"
        elif ftype == 'audio':
            res = db.match('SELECT AudioFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                found = feed_audiobook(res['AudioFile'], res['BookName'], itemid)
        elif ftype == 'book':
            res = db.match('SELECT BookFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                types = ebook_formats(res['BookFile'])
                # serve user preferred type if available, or system preferred type
                extn = user['BookType'] if user['BookType'] and user['BookType'] in types else types[0]
                myfile = splitext(res['BookFile'])[0] + '.' + extn
                if path_isfile(myfile):
                    found = myfile, None
        elif ftype == 'issue':
            res = db.match('SELECT Title,IssueFile from issues WHERE IssueID=?', (itemid,))
            if res and res['IssueFile'] and path_isfile(res['IssueFile']):
                found = res['IssueFile'], f"{res['Title']} {itemid}{splitext(res['IssueFile'])[1]}"
    finally:
        db.close()
    if found:
        logger.debug(f'Opening {ftype} {found[0]}')
        return found
    logger.warning(f"No file found for {ftype} {itemid}")
    return None


def feed_picture(db, itemid, size: int) -> tuple[str, str]:
    """ A book, issue or comic issue's cover, the LazyLibrarian logo if it hasn't one """
    logger = logging.getLogger(__name__)
    if itemid:
        res = db.match('SELECT BookName,BookImg from books WHERE BookID=?', (itemid,))
        if res:
            logger.debug(f"Itemid {itemid} matches ebook")
            bookimg = res['BookImg']
            if bookimg and bookimg.startswith('http'):
                # external URL (set by e.g. googlebooks import) - cache it, point the row at the cached
                # file and serve that, instead of silently falling through to the app logo
                link, ok, _ = cache_img(ImageType.BOOK, itemid, bookimg)
                if ok:
                    db.action("UPDATE books SET BookImg=? WHERE BookID=?", (link, itemid))
                    logger.info(f"Cached external cover for {itemid} from {bookimg}")
                    bookimg = link
            target = picture(bookimg, size)
            if path_isfile(target):
                return target, res['BookName'] + splitext(bookimg)[1]
        else:
            res = db.match('SELECT Title,Cover from issues WHERE IssueID=?', (itemid,))
            if res:
                logger.debug(f"Itemid {itemid} matches issue")
            else:
                try:
                    comicid, issueid = itemid.split('_')
                    res = db.match("SELECT Title,Cover from comics,comicissues WHERE "
                                   "comics.ComicID=comicissues.ComicID and comics.ComicID=? and IssueID=?",
                                   (comicid, issueid))
                except (IndexError, ValueError):
                    res = None
                if res:
                    logger.debug(f"Itemid {itemid} matches comicid")
            if res:
                target = picture(res['Cover'], size)
                if path_isfile(target):
                    return target, res['Title'] + splitext(res['Cover'])[1]
    logger.debug(f"Itemid {itemid} no match")
    target = os.path.join(DIRS.PROG_DIR, 'data', 'images', 'll192.png')
    return (target, 'lazylibrarian.png') if path_isfile(target) else None


def feed_audiobook(audiofile, bookname, bookid) -> tuple[str, str | None] | None:
    """ An audiobook's file, zipped if it's in parts and RSS_PODCAST isn't set """
    parts = 0
    if audiofile and path_isfile(audiofile):
        for _, _, filenames in os.walk(os.path.dirname(audiofile)):
            parts += sum(1 for filename in filenames if CONFIG.is_valid_booktype(filename, 'audiobook'))
    if parts > 1 and not CONFIG.get_bool('RSS_PODCAST'):
        target = zip_audio(os.path.dirname(audiofile), bookname, bookid)
        if target and path_isfile(target):
            return target, bookname + '.zip'
    if audiofile and path_isfile(audiofile):
        return audiofile, None
    return None


def book_to_open(bookid, library: str, booktype=None, preftype: str = '') -> dict:
    """ What opening a book gives: a dict with action
        send: path and name (None for the file's own) to send.
        parts: an audiobook in parts, which to choose from (count, and whole if there's a single file too).
        formats: an ebook in several formats to choose from (formats), unavailable when the one asked for
            (preftype, or booktype if given) isn't one of them.
        missing: the file isn't there.
        For an audiobook, booktype is whole, zip or a part number. NotFoundError if there's no such book """
    logger = logging.getLogger(__name__)
    if booktype is not None:
        preftype = booktype
    # This used to look for the configured source's own id column, but compared the source's settings
    # with its name so never found it. Books are found by BookID, which is what's always been used.
    db = database.DBConnection()
    try:
        bookdata = db.match("SELECT BookFile,AudioFile,AuthorName,BookName from books,authors WHERE books.BookID=? or "
                            "BookID=? and books.AuthorID = authors.AuthorID", (bookid, bookid))
    finally:
        db.close()
    if not bookdata:
        logger.warning(f'Missing bookid: {bookid}')
        raise NotFoundError(f'Missing bookid: {bookid}')
    book_name = bookdata["BookName"]
    found = {'action': 'missing', 'library': library, 'author': bookdata["AuthorName"], 'title': book_name}

    if library == 'AudioBook':
        bookfile = bookdata["AudioFile"]
        if bookfile and path_isfile(bookfile):
            return {**found, **audiobook_to_open(bookid, bookfile, book_name, booktype)}

    library = 'eBook'
    bookfile = bookdata["BookFile"]
    found.update({'library': library, 'path': bookfile})
    if bookfile and path_isfile(bookfile):
        types = ebook_formats(bookfile)
        logger.debug(f'Preftype:{preftype} Available:{str(types)}')
        if preftype and len(types):
            if preftype not in types:
                return {**found, 'action': 'formats', 'formats': types, 'unavailable': preftype}
            bookfile = splitext(bookfile)[0] + '.' + preftype
        elif len(types) > 1:
            return {**found, 'action': 'formats', 'formats': types, 'unavailable': ''}
        if len(types) and bookfile and path_isfile(bookfile):
            return {**found, 'action': 'send', 'path': bookfile, 'name': None, 'ebook': True}
        logger.debug(f'Unable to send {library} {book_name}, no valid types?')
    logger.info(f"Missing {library} {bookdata['AuthorName']}, {book_name} [{bookfile}]")
    return found


def audiobook_to_open(bookid, bookfile, book_name, booktype) -> dict:
    """ Which part of an audiobook to open, see book_to_open """
    parentdir = os.path.dirname(bookfile)
    singlename = name_vars(bookid)['AudioSingleFile']
    singlefile = ''
    # noinspection PyBroadException
    try:
        for fname in listdir(parentdir):
            if CONFIG.is_valid_booktype(fname, booktype='audio') and splitext(fname)[0] == singlename:
                # found name matching the AudioSingleFile
                singlefile = os.path.join(parentdir, fname)
                break
    except Exception:
        pass
    if booktype == 'whole' and singlefile and path_isfile(singlefile):
        return {'action': 'send', 'path': singlefile, 'name': os.path.basename(singlefile)}
    index = os.path.join(parentdir, 'playlist.ll')
    if not path_isfile(index):
        return {'action': 'send', 'path': bookfile, 'name': None}
    if booktype == 'zip':
        zipfile = zip_audio(parentdir, book_name, bookid)
        if zipfile and path_isfile(zipfile):
            return {'action': 'send', 'path': zipfile, 'name': f'{book_name}.zip'}
    idx = check_int(booktype, 0)
    if idx:
        with open(syspath(index)) as f:
            part = f.read().splitlines()[idx - 1]
        partfile = os.path.join(parentdir, part)
        if partfile and path_isfile(partfile):
            return {'action': 'send', 'path': partfile, 'name': f"{book_name} part{idx}{splitext(partfile)[1]}"}
    with open(index) as fp:
        count = sum(1 for _ in fp)
    if count <= 1:
        return {'action': 'send', 'path': bookfile, 'name': None}
    return {'action': 'parts', 'count': count, 'whole': bool(singlefile and path_isfile(singlefile))}


def comic_to_open(comicid, issueid=None) -> dict:
    """ What opening a comic gives: action send (path and name) for the issue asked for, or its only
        issue if COMIC_SINGLE is set, list to show its issues, or missing (with the issue) if that file is
        gone. NotFoundError if it has no issues """
    if comicid and '_' in comicid:
        comicid = comicid.split('_')[0]
    db = database.DBConnection()
    try:
        # we may want to open an issue with an issueid
        if comicid and issueid:
            issue = db.match("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                             "and comics.ComicID=? and IssueID=?", (comicid, issueid))
            if issue and issue["IssueFile"] and path_isfile(issue["IssueFile"]):
                return {'action': 'send', 'path': issue["IssueFile"],
                        'name': f"{issue['Title']} {issueid}{splitext(issue['IssueFile'])[1]}", 'comicid': comicid}
        # or we may just have a comicid to find comic in comicissues table
        issues = db.select("SELECT Title,IssueFile,IssueID from comics,comicissues WHERE "
                           "comics.ComicID=comicissues.ComicID and comics.ComicID=?", (comicid,))
    finally:
        db.close()
    if not issues:
        raise NotFoundError(f"No issues for comic {comicid}")
    if len(issues) == 1 and CONFIG.get_bool('COMIC_SINGLE'):  # we only have one issue, get it
        title, issue_id, issue_file = issues[0]["Title"], issues[0]["IssueID"], issues[0]["IssueFile"]
        if issue_file and path_isfile(issue_file):
            return {'action': 'send', 'path': issue_file, 'name': f"{title} {issue_id}{splitext(issue_file)[1]}",
                    'comicid': comicid}
        return {'action': 'missing', 'issueid': issue_id, 'title': title, 'comicid': comicid}
    return {'action': 'list', 'count': len(issues), 'comicid': comicid}


def magazine_to_open(issue_or_title) -> dict:
    """ What opening an issue (by its id) or a magazine (by title) gives: action send (path and name) for
        the issue, or the magazine's only issue if MAG_SINGLE is set, list (with title) to show its issues,
        or missing if that file is gone or it has none. NotFoundError if there's no such magazine """
    from urllib.parse import unquote
    db = database.DBConnection()
    try:
        # we may want to open an issue with a hashed bookid
        issue = db.match('SELECT * from issues WHERE IssueID=?', (issue_or_title,))
        if issue and issue["IssueFile"] and path_isfile(issue["IssueFile"]):
            return {'action': 'send', 'path': issue["IssueFile"],
                    'name': f"{issue['Title']} {issue['IssueDate']}{splitext(issue['IssueFile'])[1]}"}
        # or we may just have a title to find magazine in issues table
        magazine = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (unquote(issue_or_title),))
        if not magazine:
            raise NotFoundError(f"Magazine {issue_or_title} not found")
        title = magazine['Title']
        issues = db.select('SELECT * from issues WHERE Title=? COLLATE NOCASE', (title,))
    finally:
        db.close()
    if len(issues) == 1 and CONFIG.get_bool('MAG_SINGLE'):  # we only have one issue, get it
        issue_date, issue_file = issues[0]["IssueDate"], issues[0]["IssueFile"]
        if issue_file and path_isfile(issue_file):
            return {'action': 'send', 'path': issue_file, 'name': f"{title} {issue_date}{splitext(issue_file)[1]}",
                    'title': title}
        return {'action': 'missing', 'title': title, 'issuedate': issue_date}
    if not issues:
        return {'action': 'missing', 'title': title, 'issuedate': None}
    return {'action': 'list', 'title': title, 'count': len(issues)}


def record_sent(userid, addr: str, filename: str):
    """ Remember a file was emailed to addr, or opened (addr Open) """
    db = database.DBConnection()
    try:
        db.action('INSERT into sent_file (WhenSent, UserID, Addr, FileName) VALUES (?, ?, ?, ?)',
                  (str(int(time.time())), userid, addr, filename))
    finally:
        db.close()


def email_file(userid, path: str, name: str | None = None) -> tuple[list, list]:
    """ Email a file to the user's send-to addresses, one email each as kindles need. name says what it
        is in the message. Returns (the addresses it was sent to, the ones it failed for) """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        res = db.match('SELECT UserName,SendTo from users where UserID=?', (userid,))
    finally:
        db.close()
    sent = []
    not_sent = []
    if not res or not res['SendTo']:
        return sent, not_sent
    msg = ''
    for addr in get_list(res['SendTo']) if ',' in res['SendTo'] else [res['SendTo']]:
        logger.debug(f"Emailing {path} to {addr}")
        if name:
            msg = lazylibrarian.NEWFILE_MSG.replace('{name}', name).replace('{method}', ' is attached').replace(
                '{link}', '')
        if notifiers.email_notifier.email_file(subject="Message from LazyLibrarian", message=msg, to_addr=addr,
                                               files=[path]):
            record_sent(userid, addr, os.path.basename(path))
            sent.append(addr)
        else:
            not_sent.append(addr)
    if sent:
        logger.debug(f"Emailed file {os.path.basename(path)} to {','.join(sent)}")
    if not_sent:
        logger.error(f"Failed to email file {os.path.basename(path)} to {','.join(not_sent)}")
    return sent, not_sent
