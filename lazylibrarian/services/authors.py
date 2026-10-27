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

""" Authors: the author list, an author's details, status, edits, links to info sources and scans,
    and searching the info sources for authors and books to add """

import datetime
import logging
import os
import re
import threading
import time
from shutil import copyfile, rmtree
from urllib.parse import quote

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import ROLE, database, dbk, grsync
from lazylibrarian.cache import ImageType, cache_img
from lazylibrarian.common import delete_empty_folders
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import (
    DIRS,
    get_directory,
    listdir,
    path_exists,
    path_isdir,
    path_isfile,
    setperm,
    splitext,
)
from lazylibrarian.formatter import (
    check_int,
    date_format,
    format_author_name,
    get_list,
    safe_unicode,
    sort_definite,
    strip_quotes,
    surname_first,
    unaccented,
)
from lazylibrarian.images import CHOSEN_PREFIX, get_author_image, img_id
from lazylibrarian.importer import (
    add_author_name_to_db,
    add_author_to_db,
    get_preferred_author,
    search_for,
    update_totals,
)
from lazylibrarian.librarysync import library_scan
from lazylibrarian.services import InvalidRequestError, NotFoundError, ServiceError
from lazylibrarian.services.paging import Page, page_of
from lazylibrarian.services.system import start_task
from lazylibrarian.startup import prioritized_infosources

AUTHOR_STATUSES = ('Active', 'Wanted', 'Paused', 'Ignored')
MARK_ACTIONS = AUTHOR_STATUSES + ('Delete', 'Delete+Ignore', 'Remove', 'Subscribe', 'Unsubscribe')

# the author list fields, in the order the search has always matched them
AUTHOR_LIST_FIELDS = ('AuthorImg', 'NameSort', 'LastBookSort', 'LastDate', 'Percent', 'Status', 'AuthorLink',
                      'LastLink', 'HaveBooks', 'UnignoredBooks', 'AuthorID', 'LastBookID', 'DateAdded',
                      'AddedReason', 'BadgeSource')


# GoodReads prefixes its 'about' field with an editorial note like:
# "<i>Librarian Note: There is more than one author in the Goodreads
# database with this name.</i><br /><br />actual bio..." when applicable
# (duplicate-author disambiguation, merged records, etc.) - GR's own
# convention, not a separate structured API field. get_all_author_details()
# stores 'about' verbatim, so this is detectable straight from what's
# already in the authors table, no extra fetch or schema change needed.
LIBRARIAN_NOTE_RE = re.compile(
    r'^\s*<i>\s*Librarian Note:\s*(?P<note>.*?)\s*</i>\s*(?:<br\s*/?>\s*)*', re.IGNORECASE | re.DOTALL)

# how an author came to be added, from the start of their Reason
ADDED_BY = {
    'webserver': "Manual search",
    'ol.find_book': "OpenLibrary search",
    'ol_get_author_books': "OpenLibrary search",
    'gr.find_book': "GoodReads search",
    'gr_get_author_books': "GoodReads search",
    'hc.find_book': "HardCover search",
    'hc_get_author_books': "HardCover search",
    'gb.find_book': "GoogleBooks search",
    'gb_get_author_books': "GoogleBooks search",
    'import_csv': "CSV import",
    'sync_calibre_list': "Calibre Sync",
    'api': "API",
}


def linkable_sources() -> dict:
    """ Sources that expose a per-author ID and a uniform find_author_id()/
    get_author_info() pair (unlike GoogleBooks/DNB, which are book-search-only -
    see gb.py/dnb.py, neither has find_author_id), by name with their authors column.
    These are the only sources that can be linked to an author record or chosen as an
    author's PrimarySource. Read from lazylibrarian.INFOSOURCES at call time, as this
    module is imported before startup.init_build_lists() populates INFOSOURCES. """
    return {name: src['author_key'] for name, src in lazylibrarian.INFOSOURCES.items()
            if src['author_key'] != 'authorid'}


def added_reason(reason) -> str:
    """ How an author came to be added, from their Reason """
    words = (reason or "Unknown").split()
    first = words[0].lower().strip(":")
    if first in ADDED_BY:
        return ADDED_BY[first]
    match first:
        case 'wishlist':  # added via wishlist rss search
            return "Wishlist search " + ' '.join(words[1:])
        case 'process_alternate':  # added via import of alt folder
            return f"Import {' '.join(words[1:])} from alternate folder"
        case 'add':
            return f"Import author of {' '.join(words[3:])}"
        case 'contributor':
            return ' '.join(words)
        case 'series':
            return "Search for series " + ' '.join(words[1:])
    return ''


def list_authors(search: str = '', sort: str = 'NameSort', descending: bool = False, offset: int = 0,
                 limit: int | None = None, ignored: bool = False, primary_only: bool = False,
                 subscriber=None) -> Page:
    """ A page of authors, by name unless sorted otherwise.

        ignored lists the ignored authors (and paused ones, with IGNORE_PAUSED) instead of the others,
        primary_only only authors who are the primary author of a book, subscriber only the authors
        that user subscribes to. Each item has the authors columns plus:
        NameSort and LastBookSort, the name and last book as the list sorts them (surname first,
        without a leading article, if set); Percent, how many of their books we have;
        AddedReason, how they were added; and BadgeSource, their primary source, or the first linked
        one in priority order if no primary was chosen.
    """
    serversidelogger = logging.getLogger('special.serverside')
    link_sources = list(linkable_sources().items())
    cmd = ("SELECT AuthorImg,AuthorName,LastBook,LastDate,Status,AuthorLink,LastLink,HaveBooks,"
           "UnignoredBooks,AuthorID,LastBookID,DateAdded,Reason,PrimarySource," +
           ",".join(col for _, col in link_sources) + " from authors ")
    hidden = "('Ignored', 'Paused')" if CONFIG.get_bool('IGNORE_PAUSED') else "('Ignored')"
    cmd += f"where Status {'IN' if ignored else 'NOT IN'} {hidden} and AuthorName is not null "
    db = database.DBConnection()
    try:
        if primary_only:
            # is the author a primary author for any book...
            res = db.select(f"SELECT AuthorID from bookauthors WHERE role={ROLE['PRIMARY']}")
            cmd += " and AuthorID in (" + ", ".join(f"'{w}'" for w in {a['AuthorID'] for a in res}) + ")"
        if subscriber:
            res = db.select("SELECT WantID from subscribers WHERE Type='author' and UserID=?", (subscriber,))
            serversidelogger.debug(f"User subscribes to {len(res)} authors")
            cmd += " and AuthorID in (" + ", ".join(f"'{w}'" for w in {a['WantID'] for a in res}) + ")"
        cmd += " order by AuthorName COLLATE NOCASE"
        serversidelogger.debug(f"list_authors {cmd}")
        rows = db.select(cmd)
    finally:
        db.close()

    priority = [name for name, _ in prioritized_infosources()]
    postfixes = get_list(CONFIG.get_csv('NAME_POSTFIX'))
    articles = get_list(CONFIG.get_csv('NAME_DEFINITE'))
    authors = []
    for row in rows:
        author = dict(row)
        author['NameSort'] = author['AuthorName']
        if CONFIG.get_bool('SORT_SURNAME'):
            author['NameSort'] = surname_first(author['AuthorName'], postfixes=postfixes)
        author['LastBookSort'] = author['LastBook']
        if CONFIG.get_bool('SORT_DEFINITE'):
            author['LastBookSort'] = sort_definite(author['LastBook'], articles=articles)
        author['LastDate'] = date_format(author['LastDate'], '', f"{author['NameSort']}/{author['LastBookSort']}",
                                         datelang=CONFIG['DATE_LANG'])
        have = check_int(author['HaveBooks'], 0)
        total = check_int(author['UnignoredBooks'], 0)
        author['Percent'] = min(int((have * 100.0) / total), 100) if total else 0
        author['AddedReason'] = strip_quotes(added_reason(author['Reason']))
        author['BadgeSource'] = author['PrimarySource'] or next(
            (name for name in priority if name in dict(link_sources) and author.get(dict(link_sources)[name])), '')
        authors.append(author)
    return page_of(authors, search=search, search_fields=AUTHOR_LIST_FIELDS, sort=sort, descending=descending,
                   offset=offset, limit=limit)


def get_author(authorid, any_source_id: bool = False) -> dict:
    """ An author's record. any_source_id also finds them by their OpenLibrary, GoodReads or HardCover id """
    db = database.DBConnection()
    try:
        author = db.match("SELECT * from authors WHERE AuthorID=?", (authorid,))
        if not author and any_source_id:
            author = db.match("SELECT * from authors WHERE ol_id=? or gr_id=? or hc_id=?",
                              (authorid, authorid, authorid))
    finally:
        db.close()
    if not author:
        raise NotFoundError(f"AuthorID {authorid} not found")
    return dict(author)


def author_languages(authorid, ignored: bool = False) -> list:
    """ The languages of the author's books, of the ignored ones or the others """
    db = database.DBConnection()
    try:
        return db.select(f"SELECT DISTINCT BookLang from books WHERE AuthorID=? AND Status {'=' if ignored else '!='}"
                         f"'Ignored'", (authorid,))
    finally:
        db.close()


def gb_search_link(authorname) -> str:
    """ GoogleBooks has no author-entity/ID of its own (see INFOSOURCES's author_link) -
    volumes only, not authors - so unlike gr_link/ol_link/hc_link/ran_link this can't
    be a verified per-author page link, just a name-based search results link using
    Google Books' inauthor: search operator. Not stored - built fresh each render so
    it always reflects the current AuthorName. """
    if not CONFIG['GB_API'] or not authorname:
        return ''
    return f'https://books.google.com/books?q=inauthor:%22{quote(authorname)}%22'


def amazon_search_link(authorname) -> str:
    """ Amazon has no free author-lookup API (PA-API needs an Associates account with
    real sales volume) and scraping product pages for the byline's own p_27 author-facet
    value would carry the same ban risk already ruled out elsewhere. This is the
    unauthenticated version of that same p_27 facet search Amazon's own byline links
    use - built from the plain author name, no fetch/scrape involved, same
    unverified-search-link status as gb_search_link. Useful for self-published authors
    (see ASIN work) who often have nothing else to search by. """
    if not authorname:
        return ''
    # The whole "p_27:Name" refinement value needs encoding as one unit (colon -> %3A)
    # to match what Amazon's own byline search links actually send - a bare colon
    # after p_27 with only the name percent-encoded silently fails to filter by author.
    return f'https://www.amazon.com/s?i=stripbooks&rh={quote(f"p_27:{authorname}")}'


def parse_author_date(datestr):
    """ A born or died date, which may be just a year or a year and month, as a date """
    if not datestr:
        return None
    parts = datestr.split('-')
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        day = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        return datetime.date(year, month, day)
    except (ValueError, IndexError):
        return None


def author_age(author) -> int | None:
    """ How old the author is, or was when they died """
    born = parse_author_date(author.get('AuthorBorn'))
    if not born:
        return None
    end = parse_author_date(author.get('AuthorDeath')) or datetime.date.today()
    return end.year - born.year - ((end.month, end.day) < (born.month, born.day))


def author_details(authorid) -> dict:
    """ Everything the author detail view shows: the author with About split from any Goodreads
        librarian note, their age, book counts by status, each source's own About text, and per
        source how many of their books it knows and how many of those another source knows too """
    author = get_author(authorid)
    # Uses every source's book_key column for overlap (a book can carry a gb_id/
    # dnb_id even though those aren't author-linkable sources), counted in Python
    # rather than one SQL query per source since per-author book counts are small.
    # DNB/BN are left out of the counts (but stay in book_source_cols for overlap) because
    # they have no row in author_detail.html - unlike GoogleBooks, which also has no
    # author entity of its own but does get a row.
    book_source_cols = tuple(src['book_key'] for src in lazylibrarian.INFOSOURCES.values()
                             if src.get('book_key')) + ('ASIN',)
    db = database.DBConnection()
    try:
        book_rows = db.select(f"SELECT {','.join(book_source_cols)} from books WHERE AuthorID=?", (authorid,))
        ebook_status_counts = {row['Status'] or 'None': row['cnt'] for row in db.select(
            "SELECT Status, COUNT(*) as cnt FROM books WHERE AuthorID=? GROUP BY Status", (authorid,))}
        audio_status_counts = {row['AudioStatus'] or 'None': row['cnt'] for row in db.select(
            "SELECT AudioStatus, COUNT(*) as cnt FROM books WHERE AuthorID=? GROUP BY AudioStatus", (authorid,))}
    finally:
        db.close()
    source_book_counts = {}
    for col in (c for c in book_source_cols if c not in ('dnb_id', 'bn_id')):
        count = 0
        overlap = 0
        for row in book_rows:
            if row[col]:
                count += 1
                if any(row[other] for other in book_source_cols if other != col):
                    overlap += 1
        source_book_counts[col] = (count, overlap)

    librarian_note = ''
    if author.get('About'):
        match = LIBRARIAN_NOTE_RE.match(author['About'])
        if match:
            librarian_note = match.group('note')
            author['About'] = author['About'][match.end():]

    # Per-source About text - a linear list of what each linked source itself
    # says, not just the single merged/preferred version above.
    about_by_source = []
    for name, col in (('GoodReads', 'gr_about'), ('OpenLibrary', 'ol_about'),
                      ('HardCover', 'hc_about'), ('RanobeDB', 'ran_about'), ('DBK', 'dbk_about')):
        text = author.get(col)
        if text:
            note_match = LIBRARIAN_NOTE_RE.match(text)
            if note_match:
                text = text[note_match.end():]
            about_by_source.append((name, text))

    return {'author': author, 'age': author_age(author), 'librarian_note': librarian_note,
            'ebook_status_counts': ebook_status_counts, 'audio_status_counts': audio_status_counts,
            'about_by_source': about_by_source, 'source_book_counts': source_book_counts}


def author_name(db, authorid) -> str:
    """ The author's name, NotFoundError if there's no such author """
    author = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
    if not author:
        raise NotFoundError(f"AuthorID {authorid} not found")
    return author['AuthorName']


def set_status(authorid, status: str):
    """ Set an author Active, Wanted, Paused or Ignored """
    if status not in AUTHOR_STATUSES:
        raise InvalidRequestError(f'Unknown author status {status}')
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        name = author_name(db, authorid)
        logger.info(f"{status} author: {name}")
        db.upsert("authors", {'Status': status}, {'AuthorID': authorid})
    finally:
        db.close()


def remove_author(authorid):
    """ Remove an author, and any series they were the only author of """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        name = author_name(db, authorid)
        logger.info(f"Removing all references to author: {name}")
        db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
        orphans = db.select('select seriesid from series except select seriesid from seriesauthors')
        for orphan in orphans:
            db.action('DELETE from series where seriesid=?', (orphan[0],))
    finally:
        db.close()


def refresh_author(authorid):
    """ Fetch the author's details and books again, in the background """
    author = get_author(authorid)
    name = author['AuthorName']
    if not name or 'unknown' in name.lower() or 'anonymous' in name.lower():
        name = None
    threading.Thread(target=add_author_to_db, name=f"REFRESHAUTHOR_{authorid}",
                     args=[name, True, authorid, True, f"WebServer refresh_author {authorid}"]).start()


def follow_author(authorid, follow: bool = True) -> str:
    """ Follow or unfollow the author on Goodreads, returns what happened """
    # empty GRfollow is not-yet-used, zero means manually unfollowed so sync leaves it alone
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        author = db.match('SELECT AuthorName, GRfollow from authors WHERE AuthorID=?', (authorid,))
        if not author:
            raise NotFoundError(f"Invalid authorid to {'follow' if follow else 'unfollow'} ({authorid})")
        following = author['GRfollow'] and author['GRfollow'] != '0'
        if following == follow:
            msg = f"{'Already Following' if follow else 'Not Following'} {author['AuthorName']}"
            logger.warning(msg)
            return msg
        msg = grsync.grfollow(authorid, follow)
        if msg.startswith('Unable'):
            logger.warning(msg)
            return msg
        logger.info(msg)
        followid = msg.split("followid=")[1] if follow else '0'
        db.action("UPDATE authors SET GRfollow=? WHERE AuthorID=?", (followid, authorid))
        return msg
    finally:
        db.close()


def author_folder(authorid, library: str) -> tuple:
    """ Where the author's books are in a library: (authorid, folder), folder None if not found.
        The authorid changes when the folder name matches the preferred author for that name """
    logger = logging.getLogger(__name__)
    fuzzlogger = logging.getLogger('special.fuzz')
    db = database.DBConnection()
    try:
        name = author_name(db, authorid)
        authordir = safe_unicode(os.path.join(get_directory(library), name))
        if not path_isdir(authordir):
            logger.debug(f"Assumed authordir [{authordir}] not found")
            # books might not be in exact same authorname folder due to capitalisation
            # or accent stripping etc.
            # eg Calibre puts books into folder "Eric Van Lustbader", but
            # goodreads told lazylibrarian he's "Eric van Lustbader", note the lowercase 'v'
            # or calibre calls "Neil deGrasse Tyson" "Neil DeGrasse Tyson" with a capital 'D'
            # so try a fuzzy match...
            libdir = os.path.dirname(authordir)
            matchname, exists = get_preferred_author(name)
            if exists:
                name = matchname
                if exists != authorid:
                    logger.warning(f"{authorid}:{name} matches preferred id {exists}:{matchname}")
                authorid = exists
            logger.debug(f"Scanning {libdir} for preferred name {matchname}")
            matchname = unaccented(matchname).lower()
            for itm in listdir(libdir):
                match = fuzz.ratio(format_author_name(unaccented(itm), get_list(CONFIG.get_csv('NAME_POSTFIX'))),
                                   matchname, processor=default_process)
                if match >= CONFIG.get_int('NAME_RATIO'):
                    authordir = os.path.join(libdir, itm)
                    fuzzlogger.debug(f"Fuzzy match folder {round(match, 2)}% {itm} for {name}")
                    # TODO Add this name variant as an aka if not already there?
                    break

        if not path_isdir(authordir):
            logger.debug(f"[{authordir}] still not found")
            # if still not found, see if we have a book by them, and what directory it's in
            sourcefile = 'AudioFile' if library == 'AudioBook' else 'BookFile'
            anybook = db.match(f"SELECT {sourcefile} from books where AuthorID=? and {sourcefile} <> ''", (authorid,))
            if anybook:
                logger.debug(f"Found {sourcefile} {anybook[sourcefile]} for {authorid}:{name}")
                authordir = safe_unicode(os.path.dirname(os.path.dirname(anybook[sourcefile])))
            else:
                logger.debug(f"No {sourcefile} in library for {authorid}:{name}")
    finally:
        db.close()
    if path_isdir(authordir):
        logger.debug(f"Using [{authordir}] for {authorid}:{name}")
        return authorid, authordir
    # maybe we don't have any of their books
    logger.warning(f'Unable to find author directory: {authordir}')
    return authorid, None


def start_author_scan(authorid, library: str) -> str:
    """ Scan the author's folder in a library, returns the authorid it was found under """
    authorid, folder = author_folder(authorid, library)
    if folder:
        start_task(f'AUTHOR_SCAN_{authorid}', library_scan, folder, library, authorid, CONFIG.get_bool('FULL_SCAN'))
    return authorid


def add_author_by_name(name: str):
    """ Look the author up and add them, in the background """
    threading.Thread(target=add_author_name_to_db, name='ADDAUTHOR',
                     args=[name, False, True, f'WebServer add_author {name}']).start()
    time.sleep(2)  # so we get some data before showing the author


def add_author_by_id(authorid, name: str = ''):
    """ Add the author with this id from the configured info source, in the background """
    threading.Thread(target=add_author_to_db, name='ADDAUTHORID',
                     args=[name, False, authorid, True, f'WebServer add_author_id {authorid}']).start()
    time.sleep(2)  # so we get some data before showing the author


def delete_author_files(db, authorid) -> list:
    """ Delete the folders of the author's books and their history, returns what went wrong """
    logger = logging.getLogger(__name__)
    failures = []
    books = db.select("SELECT BookFile,AudioFile,BookID from books WHERE AuthorID=? and "
                      "((BookFile IS NOT NULL AND BookFile != '') or (AudioFile IS NOT NULL AND AudioFile != ''))",
                      (authorid,))
    logger.debug(f"Located {len(books)} books for author {authorid}")
    if not books:
        return failures
    for book in books:
        for location in [book['BookFile'], book['AudioFile']]:
            if location and path_exists(location):
                try:
                    foldername = os.path.dirname(location)
                    logger.debug(f"Deleting folder: {foldername}")
                    rmtree(foldername)
                except Exception as e:
                    failures.append(f'rmtree failed on {location}, {type(e).__name__} {str(e)}')
        for table in ['wanted', 'readinglists']:
            db.action(f"DELETE from {table} WHERE BookID=?", (book['BookID'],))
    try:
        logger.debug("Deleting empty folders")
        delete_empty_folders(CONFIG['EBOOK_DIR'])
        delete_empty_folders(CONFIG['AUDIO_DIR'])
    except Exception as e:
        failures.append(f"Error deleting: {e}")
    return failures


def mark_authors(action: str, authorids, userid=None) -> tuple[int, int]:
    """ Set a status on authors, delete them (with their book files, and ignoring them from now on
        with Delete+Ignore), remove them, or subscribe or unsubscribe the user. Returns (passed, failed) """
    logger = logging.getLogger(__name__)
    passed = failed = 0
    if not action:
        return passed, failed
    db = database.DBConnection()
    try:
        for authorid in authorids:
            check = db.match("SELECT AuthorName from authors WHERE AuthorID=?", (authorid,))
            if not check:
                logger.warning(f'Unable to set Status to "{action}" for "{authorid}"')
                failed += 1
            elif action in AUTHOR_STATUSES:
                db.upsert("authors", {'Status': action}, {'AuthorID': authorid})
                logger.info(f'Status set to "{action}" for "{check["AuthorName"]}"')
                passed += 1
            elif action in ("Delete", "Delete+Ignore"):
                logger.info(f"{action} author and media files for {check['AuthorName']}")
                failures = delete_author_files(db, authorid)
                if action == "Delete+Ignore":
                    db.action("UPDATE books SET BookFile='', AudioFile='', Status='Ignored', "
                              "AudioStatus='Ignored', Scanresult='User Delete+Ignore' WHERE AuthorID=?", (authorid,))
                    update_totals(authorid)
                    db.upsert("authors", {'Status': 'Ignored'}, {'AuthorID': authorid})
                    logger.info(f"Author {check['AuthorName']} set to Ignored")
                else:
                    db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
                    logger.info(f"Author {check['AuthorName']} deleted")
                if failures:
                    logger.warning(f"Failures while {action} {check['AuthorName']}: {failures}")
                    failed += 1
                else:
                    passed += 1
            elif action == "Remove":
                logger.info(f"Removing author: {check['AuthorName']}")
                db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
                passed += 1
            elif action == 'Subscribe' and userid:
                res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                               (userid, 'author', authorid))
                if res:
                    logger.debug(f"User {userid} is already subscribed to {authorid}")
                    failed += 1
                else:
                    db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                              (userid, 'author', authorid))
                    logger.debug(f"Subscribe {userid} to author {authorid}")
                    passed += 1
            elif action == 'Unsubscribe' and userid:
                db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?', (userid, 'author', authorid))
                for book in db.select('SELECT bookid from books where authorid=?', (authorid,)):
                    db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                              (userid, 'ebook', book['bookid']))
                logger.debug(f"Unsubscribe {userid} author {authorid}")
                passed += 1
    finally:
        logger.debug(f"Completed {action} for {len(authorids)}")
        db.close()
    return passed, failed


def author_images(authorid) -> list:
    """ Up to 5 pictures of the author found online, as [filename, path from the data folder] """
    photos = []
    res = get_author_image(authorid=authorid, refresh=False, max_num=5)
    if res and path_isdir(res):
        basedir = res.replace(DIRS.DATADIR, '').lstrip('/')
        for itm in listdir(res):
            photos.append([itm, os.path.join(basedir, itm)])
    return photos


def cache_author_image(image: str) -> str | None:
    """ Copy an author picture from a link or file into the cache, returns its cache path or None. It's
    named as chosen, so a refresh keeps it """
    logger = logging.getLogger(__name__)
    if image.startswith('http'):
        cached, success, _ = cache_img(ImageType.AUTHOR, CHOSEN_PREFIX + img_id(), image, refresh=True)
        return cached if success else None
    if not path_isfile(image):
        logger.warning(f"Failed to find file {image}")
        return None
    extn = splitext(image)[1].lower()
    if not extn or extn not in ['.jpg', '.jpeg', '.png', '.webp']:
        logger.warning(f"Invalid extension on [{image}]")
        return None
    image_id = CHOSEN_PREFIX + img_id()
    destfile = os.path.join(DIRS.CACHEDIR, 'author', image_id + '.jpg')
    try:
        copyfile(image, destfile)
        logger.debug(f"{image}->{destfile}")
        setperm(destfile)
    except Exception as why:
        logger.warning(f"Failed to copy file {image}, {type(why).__name__} {str(why)}")
        return None
    return 'cache/author/' + image_id + '.jpg'


def update_author(authorid, name: str, born, died, image: str = '', about: str = '', manual: bool = False,
                  aka: str = '', amazon_url: str = '', cover: str | None = None) -> str:
    """ Change an author's details, returns what changed (empty if nothing did).

        born and died are dates, None to clear them, and are left alone if they aren't dates.
        image is a link or file to use as their picture, 'none' for no picture. cover is what
        the edit page chose: 'manual' to use image, 'current' to keep it, or a picture found
        online from author_images. A new name that another author already has is ignored.
    """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        authdata = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        if not authdata:
            raise NotFoundError(f"AuthorID {authorid} not found")
        edited = ""
        if authdata["AuthorBorn"] != born:
            edited += "Born "
        if authdata["AKA"] != aka:
            edited += "AKA "
        if (authdata["AmazonAuthorURL"] or '') != amazon_url:
            edited += "AmazonURL "
        if authdata["AuthorDeath"] != died:
            edited += "Died "
        if cover == "manual":
            if image and (authdata["AuthorImg"] != image):
                edited += "Image manual"
        elif cover is not None and cover != "current":
            image = os.path.join(DIRS.DATADIR, cover)
            edited += f"Image {cover} "
        if authdata["About"] != about:
            edited += "Description "
        if bool(check_int(authdata['Manual'], 0)) != manual:
            edited += "Manual "
        if authdata["AuthorName"] != name:
            if db.match('SELECT AuthorName from authors where AuthorName=?', (name,)):
                logger.debug(f"Unable to rename, new author name {name} already exists")
                name = authdata["AuthorName"]
            else:
                edited += "Name "

        if not edited:
            logger.debug(f'Author [{name}] has not been changed')
            return edited

        # Check dates, format to yyyy/mm/dd, use None to clear date, leave unchanged if fails datecheck
        if born is not None:
            checked = date_format(born, context=name, datelang=CONFIG['DATE_LANG'])
            if len(checked) == 10:
                born = checked
            else:
                logger.warning(f"Author Born date [{born}] rejected")
                born = authdata["AuthorBorn"]
                edited = edited.replace('Born ', '')
        if died is not None:
            checked = date_format(died, context=name, datelang=CONFIG['DATE_LANG'])
            if len(checked) == 10:
                died = checked
            else:
                logger.warning(f"Author Died date [{died}] rejected")
                died = authdata["AuthorDeath"]
                edited = edited.replace('Died ', '')

        if not image:
            image = authdata["AuthorImg"]
        else:
            if image == 'none':
                image = os.path.join(DIRS.PROG_DIR, 'data', 'images', 'nophoto.png')
            cached = cache_author_image(image)
            if cached:
                image = cached
            else:
                logger.warning(f"Author Image [{image}] rejected")
                image = authdata["AuthorImg"]
                edited = edited.replace('Image ', '')

        db.upsert("authors", {'AuthorName': name, 'AuthorBorn': born, 'AuthorDeath': died, 'AuthorImg': image,
                              'About': about, 'AKA': aka, 'AmazonAuthorURL': amazon_url, 'Manual': bool(manual)},
                  {'AuthorID': authorid})
        logger.info(f'Updated [ {edited}] for {name}')
        return edited
    finally:
        db.close()
        rmtree(os.path.join(DIRS.CACHEDIR, 'icrawler', authorid), ignore_errors=True)


def source_api(source: str):
    """ The info source's API, InvalidRequestError if it's switched off """
    if source not in lazylibrarian.INFOSOURCES:
        raise InvalidRequestError(f'{source} is not a configured source')
    inf_source = lazylibrarian.INFOSOURCES[source]
    if not CONFIG[inf_source['enabled']]:
        raise InvalidRequestError(f'{source} is not enabled in Config -> Importing')
    return inf_source['api']()


def search_source(authorid, source: str) -> dict | None:
    """ Search one source for this author by name, returns the best match (authorid, authorname
        and authorlink in that source) or None. Changes nothing - see link_source """
    logger = logging.getLogger(__name__)
    if source not in linkable_sources():
        raise InvalidRequestError(f'{source} does not support author search')
    db = database.DBConnection()
    try:
        author = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
    finally:
        db.close()
    if not author:
        raise NotFoundError(f'Author {authorid} not found')
    api = source_api(source)
    try:
        result = api.find_author_id(authorname=author['AuthorName'])
    except Exception as e:
        logger.error(f"search_author_source {source} error for author {authorid}: {e}")
        raise ServiceError(f'{source} search failed, check the logs') from e
    if not result or not result.get('authorid'):
        return None
    return {'authorid': result.get('authorid'), 'authorname': result.get('authorname'),
            'authorlink': result.get('authorlink')}


def author_link(source: str, sourceid, name: str, purpose: str, authorid) -> str:
    """ The author's page in a source, empty if the source can't tell """
    try:
        info = lazylibrarian.INFOSOURCES[source]['api']().get_author_info(authorid=sourceid, authorname=name)
    except Exception as e:
        logging.getLogger(__name__).error(f"{purpose} {source} lookup error for author {authorid}: {e}")
        info = None
    return info.get('authorlink', '') if info else ''


def link_source(authorid, source: str, sourceid) -> tuple[str, str]:
    """ Store a user-confirmed source id for this author, and their page in that source, without
        changing their primary source - see set_primary_source. Returns (column, stored id) """
    logger = logging.getLogger(__name__)
    if source not in linkable_sources():
        raise InvalidRequestError(f'{source} cannot be linked to an author')
    if not sourceid:
        raise InvalidRequestError('No source id supplied')
    column = linkable_sources()[source]
    if source == 'DBK':
        # accept the bare number or the author page link, stored as DBK<number>
        sourceid = dbk.DBK.author_id_from_text(sourceid)
        if not sourceid:
            raise InvalidRequestError('Not a Databazeknih author id or link')
    db = database.DBConnection()
    try:
        author = db.match('SELECT AuthorID,AuthorName from authors WHERE AuthorID=?', (authorid,))
        if not author:
            raise NotFoundError(f'Author {authorid} not found')
        updates = {column: sourceid}
        link_column = lazylibrarian.INFOSOURCES[source].get('author_link')
        if link_column:
            link = author_link(source, sourceid, author['AuthorName'], 'link_author_source', authorid)
            if link:
                updates[link_column] = link
        db.upsert('authors', updates, {'AuthorID': authorid})
    finally:
        db.close()
    logger.info(f"Linked author {authorid} to {source} id {sourceid}")
    return column, sourceid


def set_primary_source(authorid, source: str) -> str:
    """ Make one of the author's linked sources their primary, which their name link and source badge
        use. Fetches the link for the stored id rather than guessing a URL template, so AuthorLink
        always matches what that source's own get_author_info() builds. Returns the link """
    logger = logging.getLogger(__name__)
    if source not in linkable_sources():
        raise InvalidRequestError(f'{source} cannot be a primary source')
    column = linkable_sources()[source]
    db = database.DBConnection()
    try:
        author = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        if not author:
            raise NotFoundError(f'Author {authorid} not found')
        sourceid = author[column]
        if not sourceid:
            raise InvalidRequestError(f'Author is not linked to {source} yet')
        link = author_link(source, sourceid, author['AuthorName'], 'set_primary_source', authorid)
        updates = {'PrimarySource': source}
        if link:
            updates['AuthorLink'] = link
            link_column = lazylibrarian.INFOSOURCES[source].get('author_link')
            if link_column:
                updates[link_column] = link
        db.upsert('authors', updates, {'AuthorID': authorid})
    finally:
        db.close()
    logger.info(f"Set primary source for author {authorid} to {source}")
    return link


def unlink_source(authorid, source: str):
    """ Forget a linked source id, so it can be searched for and linked again. Its link goes too, and
        if it was the primary source so do PrimarySource and AuthorLink, as a link to a source that
        isn't linked any more would be misleading. The badge then falls back to the priority order """
    logger = logging.getLogger(__name__)
    if source not in linkable_sources():
        raise InvalidRequestError(f'{source} cannot be unlinked')
    column = linkable_sources()[source]
    db = database.DBConnection()
    try:
        author = db.match('SELECT AuthorID, PrimarySource from authors WHERE AuthorID=?', (authorid,))
        if not author:
            raise NotFoundError(f'Author {authorid} not found')
        updates = {column: ''}
        link_column = lazylibrarian.INFOSOURCES[source].get('author_link')
        if link_column:
            updates[link_column] = ''
        if author['PrimarySource'] == source:
            updates['PrimarySource'] = ''
            updates['AuthorLink'] = ''
        db.upsert('authors', updates, {'AuthorID': authorid})
    finally:
        db.close()
    logger.info(f"Unlinked {source} from author {authorid}")


def search_sources(searchfor: str, max_pages: int = 0) -> dict:
    """ Search the configured info source, and the others if MULTI_SOURCE is on, for an author,
        book or isbn, reading max_pages of a paged source's results when given. Returns the results,
        best match first, and which of them we already have: authors (and ones still loading) by
        their id in the configured source, and books """
    logger = logging.getLogger('special.searching')
    lazylibrarian.SEARCHING = 1
    try:
        # This used to look for the configured source's own id columns, but compared the source's
        # settings with its name so never found them. The results match on AuthorID and BookID,
        # which is what's always been used.
        db = database.DBConnection()
        try:
            authorids = db.select("SELECT AuthorID from authors where status != 'Loading'")
            loadingauthorids = db.select("SELECT AuthorID from authors where status = 'Loading'")
            booksearch = db.select("SELECT Status,AudioStatus,BookID from books")
        finally:
            db.close()
        # we don't know if searchfor is an author, book or isbn
        results = []
        try:
            results = search_for(searchfor, CONFIG['BOOK_API'], max_pages)
            logger.debug(f"Found {len(results)} from {CONFIG['BOOK_API']}")
            if CONFIG.get_bool('MULTI_SOURCE'):
                for info_src, itm in lazylibrarian.INFOSOURCES.items():
                    if CONFIG['BOOK_API'] != info_src and CONFIG[itm['enabled']]:
                        more = search_for(searchfor, info_src, max_pages)
                        logger.debug(f"Found {len(more)} from {info_src}")
                        # Prefer our configured book api if equal matches by downgrading all the others slightly.
                        for res in more:
                            res['highest_fuzz'] -= 1
                            results.append(res)
        except Exception as e:
            logger.debug(str(e))
        return {'results': sorted(results, key=lambda x: (x['highest_fuzz'], x['bookrate_count']), reverse=True),
                'authorlist': list({a['AuthorID'] for a in authorids if a['AuthorID']}),
                'loadlist': list({a['AuthorID'] for a in loadingauthorids if a['AuthorID']}),
                'booklist': list({b['BookID'] for b in booksearch if b['BookID']}),
                'booksearch': booksearch}
    finally:
        lazylibrarian.SEARCHING = 0
