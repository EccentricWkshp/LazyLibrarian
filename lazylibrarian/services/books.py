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

""" Books: the ebook and audiobook lists, a book's details and edits, adding, searching for,
    snatching and marking books, and the language refresh """

import contextlib
import datetime
import logging
import os
import threading
import time
import uuid
from shutil import copyfile, rmtree
from urllib.parse import urlencode

import lazylibrarian
from lazylibrarian import ROLE, database, notifiers
from lazylibrarian.bookwork import delete_empty_series, language_from_words, set_series
from lazylibrarian.cache import gr_xml_request
from lazylibrarian.common import get_readinglist, is_valid_language, reading_status, set_readinglist
from lazylibrarian.config2 import CONFIG
from lazylibrarian.downloadmethods import (
    direct_dl_method,
    irc_dl_method,
    nzb_dl_method,
    tor_dl_method,
)
from lazylibrarian.filesystem import (
    DIRS,
    book_file,
    opf_file,
    path_exists,
    path_isdir,
    path_isfile,
    remove_file,
    safe_copy,
    safe_move,
    splitext,
)
from lazylibrarian.formatter import (
    check_int,
    check_year,
    clean_name,
    get_list,
    now,
    plural,
    sort_definite,
    surname_first,
    thread_name,
    unaccented,
)
from lazylibrarian.images import chosen_cover, get_book_cover
from lazylibrarian.importer import add_author_to_db, update_totals
from lazylibrarian.manual_import import process_book_from_dir
from lazylibrarian.manualbook import search_item
from lazylibrarian.metadata_opf import create_opf
from lazylibrarian.notifiers import custom_notify_snatch, notify_snatch
from lazylibrarian.opfedit import opf_read, opf_write
from lazylibrarian.scheduling import SchedulerCommand, schedule_job
from lazylibrarian.searchbook import search_book
from lazylibrarian.services import InvalidRequestError, NotFoundError, ServiceError
from lazylibrarian.services.files import remove_from_calibre
from lazylibrarian.services.paging import Page, page_of
from lazylibrarian.services.system import is_running, start_task

# which books each list shows
BOOK_VIEWS = ('Books', 'Audio', 'Author', 'Manage')
READING_LISTS = ('ToRead', 'HaveRead', 'Reading', 'Abandoned')
# the reading list actions, Unread takes a book off them all
READING_ACTIONS = ("Unread", "Read", "ToRead", "Reading", "Abandoned")
WANT_ACTIONS = ("Wanted", "WantEbook", "WantAudio", "WantBoth")

# Per-format variants of Have/Skipped/Ignored, mapped to (status, libraries)
FORMAT_STATUS_ACTIONS = {
    'HaveEbook': ('Have', 'eBook'),
    'HaveAudio': ('Have', 'AudioBook'),
    'HaveBoth': ('Have', 'eBook+AudioBook'),
    'SkipEbook': ('Skipped', 'eBook'),
    'SkipAudio': ('Skipped', 'AudioBook'),
    'SkipBoth': ('Skipped', 'eBook+AudioBook'),
    'IgnoreEbook': ('Ignored', 'eBook'),
    'IgnoreAudio': ('Ignored', 'AudioBook'),
    'IgnoreBoth': ('Ignored', 'eBook+AudioBook'),
}

# the fields a book list search looks in, the status one is AudioStatus for audiobooks
SEARCH_FIELDS = ('AuthorName', 'BookName', 'BookDate', 'Status', 'BookID', 'BookLang', 'BookSub', 'AuthorID',
                 'BookGenre', 'ScanResult')
# book list sorts that sort numbers in text by value
NATURAL_SORTS = ('SeriesDisplay', 'BookLibrary', 'AudioLibrary', 'BookAdded')

# the covers edit_book can offer, and the suffix get_book_cover caches each one with
COVER_SUFFIXES = {'librarything': '_lt', 'goodreads': '_gr', 'openlibrary': '_ol', 'googleisbn': '_gi',
                  'googleimage': '_go', 'bing': '_bi', 'ranobedb': '_ra', 'cover': '_cover'}


def status_mark_targets(action: str, library: str) -> tuple[str, str] | None:
    """Return (status, libraries) for a Have/Skipped/Ignored mark, or None for any other action.

    The plain actions follow the page's library; the per-format ones name their own.
    """
    if action in FORMAT_STATUS_ACTIONS:
        return FORMAT_STATUS_ACTIONS[action]
    if action in ('Have', 'Skipped', 'Ignored'):
        return action, library or ''
    return None


def refresh_book_languages(progress=None) -> str:
    """ Background job: re-evaluates language for books in the database.
    Corrects short-title false positives (e.g. English titles misidentified as German/French/Spanish),
    normalizes English dialects (e.g. en-CA), resolves 'Unknown' languages, and automatically
    un-ignores books that were falsely marked Ignored due to invalid language. progress is told how
    far it got now and then. Returns what it did """
    logger = logging.getLogger(__name__)
    message = ''
    incoming_threadname = thread_name()
    thread_name('LANGREFRESH')

    def stop_requested():
        return lazylibrarian.STOPTHREADS and thread_name() == 'LANGREFRESH'

    db = database.DBConnection()
    try:
        db.upsert("jobs", {"Start": time.time()}, {"Name": "LANGREFRESH"})
        rows = db.select(
            "SELECT BookID, BookName, BookLang, BookDesc, Status, ScanResult, AuthorID FROM books "
            "WHERE (Status = 'Ignored' AND ScanResult LIKE '%Invalid language%') "
            "OR BookLang = 'Unknown' OR BookLang IS NULL OR BookLang = '' "
            "OR BookLang NOT IN ('en', 'eng', 'en-US', 'en-GB')"
        )
        total = len(rows)
        lazylibrarian.LANG_REFRESH_STATUS = {'checked': 0, 'updated': 0, 'unignored': 0, 'total': total}
        logger.info(f"Language refresh: {total} candidate book{plural(total)} to check")
        if progress:
            progress(f"Checking {total} {plural(total, 'book')}")

        valid_langs = get_list(CONFIG['IMP_PREFLANG'])
        checked = 0
        updated = 0
        unignored = 0
        authors_to_update = set()

        for row in rows:
            if stop_requested():
                logger.info(f"Language refresh: stopped after checking {checked}/{total}")
                break

            bookid = row['BookID']
            name = row['BookName'] or ''
            old_lang = row['BookLang'] or 'Unknown'
            desc = row['BookDesc'] or ''
            status = row['Status']
            scan_res = row['ScanResult'] or ''
            author_id = row['AuthorID']

            new_lang, conf = language_from_words(name, desc=desc)
            if new_lang and new_lang not in ['None', 'Disabled', 'Blocked'] and conf > 0.5:
                lang_to_set = new_lang
            else:
                lang_to_set = old_lang

            lang_changed = (lang_to_set != old_lang and lang_to_set != 'Unknown')
            was_ignored_for_lang = (status == 'Ignored' and 'Invalid language' in scan_res)
            is_valid_now = is_valid_language(lang_to_set, valid_langs)

            if lang_changed or (was_ignored_for_lang and is_valid_now):
                updates = {}
                if lang_changed:
                    updates['BookLang'] = lang_to_set
                if was_ignored_for_lang and is_valid_now:
                    new_status = CONFIG['NEWBOOK_STATUS'] if CONFIG['NEWBOOK_STATUS'] != 'Ignored' else 'Skipped'
                    updates['Status'] = new_status
                    updates['ScanResult'] = f"[LangRefresh] Restored: {old_lang} -> {lang_to_set}"
                    unignored += 1
                    if author_id:
                        authors_to_update.add(author_id)
                elif lang_changed and not was_ignored_for_lang:
                    updates['ScanResult'] = f"[LangRefresh] Language: {old_lang} -> {lang_to_set}"

                if updates:
                    set_clause = ', '.join(f"{k}=?" for k in updates.keys())
                    values = list(updates.values()) + [bookid]
                    db.action(f"UPDATE books SET {set_clause} WHERE BookID=?", values)
                    updated += 1

            checked += 1
            lazylibrarian.LANG_REFRESH_STATUS['checked'] = checked
            lazylibrarian.LANG_REFRESH_STATUS['updated'] = updated
            lazylibrarian.LANG_REFRESH_STATUS['unignored'] = unignored

            if checked % 250 == 0:
                db.commit()
                logger.info(f"Language refresh: checked {checked}/{total}, updated {updated}, restored {unignored}")
                if progress:
                    progress(f"Checked {checked} of {total}, {updated} updated, {unignored} restored")

        db.commit()
        for auth_id in authors_to_update:
            with contextlib.suppress(Exception):
                lazylibrarian.importer.update_totals(auth_id)

        logger.info(f"Language refresh: complete, checked {checked}/{total}, updated {updated}, restored {unignored}")
        message = (f"Checked {checked} {plural(checked, 'book')}: {updated} updated, "
                   f"{unignored} no longer ignored")
    finally:
        db.upsert("jobs", {"Finish": time.time()}, {"Name": "LANGREFRESH"})
        db.close()
        thread_name(incoming_threadname)
    return message


def start_language_refresh():
    """ Re-evaluate the languages of the books that might be wrong, in the background """
    if is_running('LANGREFRESH'):
        raise InvalidRequestError('Language refresh is already running')
    start_task('LANGREFRESH', refresh_book_languages)
    logging.getLogger(__name__).info("Manually triggered book language refresh")


def refresh_languages_now(progress=None) -> str:
    """ Re-evaluate the languages of the books that might be wrong, in this thread, as the
    RefreshLanguages command does. Returns what it did """
    if is_running('LANGREFRESH'):
        raise InvalidRequestError('Refreshing the book languages is already running')
    return refresh_book_languages(progress)


def language_refresh_status() -> dict:
    """ Whether a language refresh is running, and how far it got """
    status = lazylibrarian.LANG_REFRESH_STATUS
    return {'running': is_running('LANGREFRESH'), 'checked': status.get('checked', 0),
            'updated': status.get('updated', 0), 'unignored': status.get('unignored', 0),
            'total': status.get('total', 0)}


def refresh_source_priority() -> list:
    """ Priority order for picking which single source to refresh a book from -
    author-linkable sources (INFOSOURCES's author_key, richer/more curated data)
    before book-search-only ones (GoogleBooks/DNB/BN), each group in INFOSOURCES'
    own order, as (name, book id column). Every source implements the same
    add_bookid_to_db(bookid, bookstatus, audiostatus, reason) interface (see bookdict.py's
    docstring), so this can dispatch generically rather than needing per-source logic.
    Read from lazylibrarian.INFOSOURCES at call time, as this module is imported before
    startup.init_build_lists() populates INFOSOURCES. """
    author_linkable = [(name, src['book_key']) for name, src in lazylibrarian.INFOSOURCES.items()
                       if src['author_key'] != 'authorid']
    book_only = [(name, src['book_key']) for name, src in lazylibrarian.INFOSOURCES.items()
                 if src['author_key'] == 'authorid']
    return author_linkable + book_only


def _refresh_from(api, book, source_name: str, outcome: list):
    """ Add the book from its source again, keeping what's the user's: its statuses, when it was
    added, and a cover chosen when it was edited. The source's cover is fetched again, the one
    cached for the book stays only if the source has none """
    logger = logging.getLogger(__name__)
    bookid = book['BookID']
    cached = os.path.join(DIRS.CACHEDIR, 'book', f'{bookid}.jpg')
    stale = f'{cached}.refreshing'
    if path_isfile(cached):
        with contextlib.suppress(OSError):
            os.replace(cached, stale)
    try:
        outcome.append(api.add_bookid_to_db(bookid=bookid, bookstatus=book['Status'] or None,
                                            audiostatus=book['AudioStatus'] or None,
                                            reason=f"WebServer refresh_book {bookid} via {source_name}"))
    finally:
        if path_isfile(stale):
            if path_isfile(cached):
                remove_file(stale)
            else:
                os.replace(stale, cached)
        db = database.DBConnection()
        try:
            restore = {'BookAdded': book['BookAdded']} if book['BookAdded'] else {}
            if chosen_cover(book['BookImg']):
                restore['BookImg'] = book['BookImg']
            if restore:
                db.upsert('books', restore, {'BookID': bookid})
        finally:
            db.close()
    logger.debug(f"Refreshed {bookid} from {source_name}")


def refresh_book(bookid, wait: bool = False) -> str:
    """ Fetch the book's details again from the source it was added from, the one its id is from, in
        the background unless wait. Its statuses, when it was added and a cover chosen for it stay.
        Returns the source, or empty if the book is locked against changes or isn't from a source.
        ServiceError if waiting and the source didn't refresh it """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        book = db.match("SELECT BookID,BookName,Manual,Status,AudioStatus,BookAdded,BookImg,gr_id,ol_id,hc_id,"
                        "ran_id,dnb_id,bn_id,dbk_id,gb_id FROM books WHERE BookID=?", (bookid,))
    finally:
        db.close()
    if not book:
        raise NotFoundError(f"BookID {bookid} not found")
    locked = book['Manual']
    if locked and str(locked).isdigit():
        locked = bool(int(locked))
    if locked:
        logger.debug(f"Not refreshing {bookid} ({book['BookName']}) - manually locked")
        return ''
    # Only the source the book's id is from: another source's id would be added as a book of its
    # own (GoodReads, GoogleBooks) or turned down as a duplicate of this one (the others)
    for source_name, id_col in refresh_source_priority():
        if str(book[id_col] or '') == str(bookid):
            api = lazylibrarian.INFOSOURCES[source_name]['api']()
            outcome = []
            refresh = threading.Thread(target=_refresh_from, name=f"REFRESHBOOK_{bookid}",
                                       args=(api, dict(book), source_name, outcome))
            refresh.start()
            if wait:
                refresh.join()
                if not outcome or not outcome[0]:
                    raise ServiceError(f"{source_name} didn't refresh it, see the log")
            return source_name
    logger.debug(f"Not refreshing {bookid} ({book['BookName']}) - its id isn't a source's")
    return ''


def search_providers(searchterm: str, bookid, category: str) -> list:
    """ Search the download providers for a book, category is book, audio or general """
    return search_item(searchterm, bookid, category)


def snatch(bookid, mode: str, provider: str, url: str, size, library: str, title: str = '') -> tuple:
    """ Download a search result for a book. Returns (the book's authorid, whether it was sent to
        a downloader, what happened) """
    logger = logging.getLogger(__name__)
    logger.debug(f"snatch {library} bookid {bookid} mode={mode} from {provider} url=[{url}] {title}")
    db = database.DBConnection()
    try:
        bookdata = db.match('SELECT AuthorID, BookName from books WHERE BookID=?', (bookid,))
        if not bookdata:
            raise NotFoundError(f"BookID {bookid} not found")
        size = round(float(check_int(size, 1000)) / 1048576, 2)  # Need to cater for when this is NONE (Issue 35)
        db.upsert("wanted", {"NZBprov": provider, "BookID": bookid, "NZBdate": now(),  # when we asked for it
                             "NZBsize": size, "NZBtitle": bookdata["BookName"], "NZBmode": mode, "AuxInfo": library,
                             "Status": "Snatched"}, {"NZBurl": url})
        dl_title = title if provider in ['soulseek', 'annas', 'webshare'] else bookdata["BookName"]
        if mode == 'direct':
            snatched, res = direct_dl_method(bookid, dl_title, url, library, provider)
        elif mode in ["torznab", "torrent", "magnet"]:
            snatched, res = tor_dl_method(bookid, bookdata["BookName"], url, library, provider=provider)
        elif mode == 'nzb':
            snatched, res = nzb_dl_method(bookid, bookdata["BookName"], url, library)
        elif mode == 'irc':
            snatched, res = irc_dl_method(bookid, title or bookdata["BookName"], url, library, provider)
        else:
            res = f'Unhandled NZBmode [{mode}] for {url}'
            logger.error(res)
            snatched = False
        if snatched:
            logger.info(f'Requested {library} {bookdata["BookName"]} from {provider}')
            custom_notify_snatch(f"{bookid} {library}")
            notify_snatch(f"{unaccented(bookdata['BookName'], only_ascii=False)} from "
                          f"{CONFIG.disp_name(provider)} at {now()}")
            schedule_job(action=SchedulerCommand.START, target='PostProcessor')
        else:
            db.action("UPDATE wanted SET status='Failed',DLResult=? WHERE NZBurl=?", (res, url))
        return bookdata["AuthorID"], snatched, res
    finally:
        db.close()


def book_languages(library: str = 'eBook') -> list:
    """ The languages of the books in a library list, the ones not skipped or ignored """
    status = 'AUDIOSTATUS' if library == 'AudioBook' else 'STATUS'
    db = database.DBConnection()
    try:
        return db.select(f"SELECT DISTINCT BookLang from books WHERE {status} !='Skipped' AND {status} !='Ignored'")
    finally:
        db.close()


def reading_lists(userid) -> dict:
    """ The user's reading lists, by name """
    if not userid:
        return {name: set() for name in READING_LISTS}
    return {name: set(get_readinglist(name, userid)) for name in READING_LISTS}


def subscribed_books(db, userid) -> set:
    """ The books of the authors and series the user subscribes to, and the ones they asked for in a feed """
    serversidelogger = logging.getLogger('special.serverside')
    mybooks = set()
    res = db.select("SELECT WantID from subscribers WHERE Type='author' and UserID=?", (userid,))
    serversidelogger.debug(f"User subscribes to {len(res)} authors")
    for author in res:
        mybooks.update(b['BookID'] for b in db.select('SELECT BookID from bookauthors WHERE AuthorID=?',
                                                       (author['WantID'],)))
    res = db.select("SELECT WantID from subscribers WHERE Type='series' and UserID=?", (userid,))
    serversidelogger.debug(f"User subscribes to {len(res)} series")
    for series in res:
        mybooks.update(b['BookID'] for b in db.select(
            'SELECT BookID from member,series WHERE series.seriesid=? and member.seriesid=series.seriesid',
            (series['WantID'],)))
    res = db.select("SELECT WantID from subscribers WHERE Type='feed' and UserID=?", (userid,))
    serversidelogger.debug(f"User subscribes to {len(res)} feeds")
    for feed in res:
        mybooks.update(b['BookID'] for b in db.select(
            "SELECT BookID from books WHERE instr(Requester, '?') > 0  or instr(AudioRequester, '?') > 0",
            (feed['WantID'], feed['WantID'])))
    serversidelogger.debug(f"User booklist length {len(mybooks)}")
    return mybooks


def book_sort_key(sort: str):
    """ How a book list sorts on a field: titles ignore case, ratings are numbers """
    if sort in ('BookName', 'TitleSort'):
        return lambda b: b[sort].lower() if b[sort] is not None else ''
    if sort == 'BookRate':
        return lambda b: float(b[sort]) if b[sort] is not None else 0.0
    return lambda b: b[sort] if b[sort] is not None else ''


def list_books(view: str, library: str | None = None, status: str = 'All', authorid=None, ignored: bool = False,
               booklang: str = '', userid=None, subscribed_only: bool = False, primary_only: bool = False,
               search: str = '', sort: str = 'BookName', descending: bool = False, offset: int = 0,
               limit: int | None = None) -> Page:
    """ A page of books, one row per book and author.

        view is one of BOOK_VIEWS: Books and Audio list the books in that library that aren't skipped or
        ignored, Author an author's books (their ignored ones, or the others), Manage the books with a
        status in the library (or All), or on one of the user's reading lists. booklang limits Books,
        Audio and Author to a language, subscribed_only Books and Audio to the books of what the user
        subscribes to, primary_only to books by their primary author. The search ignores case.

        Each item has the books columns the lists show, plus SeriesDisplay, series (seriesid~name #num
        joined with ^), altsub (the series as text), AuthorSort and TitleSort (as the lists sort them, surname
        first or without a leading article if set), ReadingList (which of the user's lists it's on, if any)
        and for Manage FailedSearch, the Time, Interval and Count of its failed searches (None if none).
    """
    if view not in BOOK_VIEWS:
        raise InvalidRequestError(f'Unknown book list {view}')
    serversidelogger = logging.getLogger('special.serverside')
    lists = reading_lists(userid)
    serversidelogger.debug(f"list_books userid {userid} read {', '.join(f'{k} {len(v)}' for k, v in lists.items())}")
    status_type = 'audiostatus' if library == 'AudioBook' else 'books.status'
    cmd = ("SELECT bookimg,authorname,bookname,bookrate,bookdate,books.status,books.bookid,booklang, "
           "booksub,booklink,workpage,bookauthors.authorid,seriesdisplay,booklibrary,audiostatus,audiolibrary, "
           "group_concat(series.seriesid || '~' || series.seriesname || ' #' || member.seriesnum, '^') "
           "as series, bookgenre,bookadded,scanresult,lt_workid, "
           "group_concat(series.seriesname || ' #' || member.seriesnum, '; ') as altsub "
           "FROM books,authors,bookauthors "
           "LEFT OUTER JOIN member ON (bookauthors.BookID = member.BookID and bookauthors.bookid=books.bookid) "
           "LEFT OUTER JOIN series ON (member.SeriesID = series.SeriesID) "
           "WHERE bookauthors.authorid=authors.authorid and bookauthors.bookid=books.bookid ")
    args = []
    if view == "Manage":
        listed = {'ToRead': 'ToRead', 'Read': 'HaveRead', 'Reading': 'Reading', 'Abandoned': 'Abandoned'}
        if status in listed:
            cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in lists[listed[status]]) + ")"
        elif status != 'All':
            cmd += f" and {status_type}=?"
            args.append(status)
    elif view == "Books":
        cmd += " and books.STATUS !='Skipped' AND books.STATUS !='Ignored'"
    elif view == "Audio":
        cmd += " and AUDIOSTATUS !='Skipped' AND AUDIOSTATUS !='Ignored'"
    elif view == "Author":
        cmd += " and bookauthors.AuthorID=?"
        args.append(authorid)
        cmd += f" and {status_type}{'=' if ignored else ' != '}'Ignored'"

    if view in ["Books", "Author", "Audio"] and booklang and booklang != 'None':
        cmd += " and BOOKLANG=?"
        args.append(booklang)

    db = database.DBConnection()
    try:
        if view in ["Books", "Audio"] and userid and subscribed_only:
            serversidelogger.debug("Getting user booklist")
            cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in subscribed_books(db, userid)) + ")"
        if view in ["Author", "Books", "Audio"] and primary_only:
            # only show book for primary author
            cmd += (" and books.bookid in (SELECT bookid FROM bookauthors where bookauthors.authorid=authors.authorid "
                    f"and books.bookid=bookauthors.bookid and role={ROLE['PRIMARY']})")
        cmd += (" GROUP BY bookimg, authorname, bookname, bookrate, bookdate, books.status, books.bookid, "
                "booklang, booksub, booklink, workpage, bookauthors.authorid, booklibrary, audiostatus, "
                "audiolibrary, bookgenre, bookadded, scanresult, lt_workid")
        serversidelogger.debug(f"list_books {cmd}: {str(args)}")
        rows = db.select(cmd, tuple(args)) if library else []
        serversidelogger.debug(f"list_books selected {len(rows)}")

        postfixes = get_list(CONFIG.get_csv('NAME_POSTFIX'))
        articles = get_list(CONFIG.get_csv('NAME_DEFINITE'))
        books = []
        for row in rows:
            book = dict(row)
            for key in ('Status', 'AudioStatus', 'series'):
                if book[key] is None:
                    book[key] = ""
            book['AuthorSort'] = book['AuthorName']
            if CONFIG.get_bool('SORT_SURNAME'):
                book['AuthorSort'] = surname_first(book['AuthorName'], postfixes=postfixes)
            book['TitleSort'] = book['BookName']
            if CONFIG.get_bool('SORT_DEFINITE'):
                book['TitleSort'] = sort_definite(book['BookName'], articles=articles)
            books.append(book)
        total = len(books)

        if search:
            fields = list(SEARCH_FIELDS)
            if library == 'AudioBook':
                fields[3] = 'AudioStatus'
            wanted = search.lower()
            books = [b for b in books if any(b[key] and wanted in b[key].lower() for key in fields)]
        page = page_of(books, sort_key=book_sort_key(sort), natural=sort in NATURAL_SORTS, descending=descending,
                       offset=offset, limit=limit)
        page.total = total

        for book in page.items:
            book['ReadingList'] = next((name for name in READING_LISTS if book['BookID'] in lists[name]), None)
            if view == 'Manage':
                searches = db.match("SELECT Time,Interval,Count from failedsearch WHERE Bookid=? AND Library='eBook'",
                                    (book['BookID'],))
                book['FailedSearch'] = dict(searches) if searches else None
    finally:
        db.close()
    return page


def add_book(bookid, authorid=None, library: str | None = None, source: str | None = None,
             search: bool | None = None, wait: float | None = 10) -> tuple:
    """ Want a book: eBook, AudioBook, Both, or whichever libraries are switched on. A book we don't
        have yet is added from its author (authorid) or from an info source, the configured one by
        default, waiting for it up to wait seconds, None for as long as it takes. A format we have
        stays as it is, the other isn't changed. Searches for it if search, or if IMP_AUTOSEARCH is
        on when search is None. Returns (its authorid if it's in the database now, ebook status,
        audio status) """
    logger = logging.getLogger(__name__)
    if library == 'eBook':
        ebook_status, audio_status = "Wanted", "Skipped"
    elif library == 'AudioBook':
        ebook_status, audio_status = "Skipped", "Wanted"
    elif library == 'Both':
        ebook_status, audio_status = "Wanted", "Wanted"
    else:
        audio_status = "Wanted" if CONFIG.get_bool('AUDIO_TAB') else "Skipped"
        ebook_status = "Wanted" if CONFIG.get_bool('EBOOK_TAB') else "Skipped"

    author_id = ''
    db = database.DBConnection()
    try:
        match = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        if not match and authorid:
            _ = add_author_to_db(None, False, authorid, False, f'WebServer add_book {bookid}')
            match = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        if match:
            for column, status in (('Status', ebook_status), ('AudioStatus', audio_status)):
                if status == 'Wanted':
                    db.action(f"UPDATE books SET {column}='Wanted' WHERE BookID=? AND "
                              f"IFNULL({column},'') NOT IN ('Open','Have')", (bookid,))
            author_id = match['AuthorID']
            update_totals(author_id)
        else:
            if source and source not in lazylibrarian.INFOSOURCES:
                logger.error(f"Invalid source {source} in add_book")
                source = None
            this_source = lazylibrarian.INFOSOURCES[source or CONFIG['BOOK_API']]
            api = this_source['api']()
            t = threading.Thread(target=api.add_bookid_to_db, name=f"{this_source['src']}-BOOK",
                                 args=[bookid, ebook_status, audio_status, "Added by user"])
            t.start()
            t.join(timeout=wait)
            match = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
            if match:
                author_id = match['AuthorID']
    finally:
        db.close()

    if CONFIG.get_bool('IMP_AUTOSEARCH') if search is None else search:
        start_search([{"bookid": bookid}])
    return author_id, ebook_status, audio_status


def start_search(books: list, library: str | None = None, force: bool = False) -> bool:
    """ Search the download providers for these books ({'bookid': id} each), in the background """
    logger = logging.getLogger(__name__)
    if not books:
        logger.debug("BookSearch called with no books")
        return False
    if not CONFIG.use_any():
        logger.warning("Not searching for book, no search methods set, check config.")
        return False
    logger.debug("Starting search_book thread")
    threading.Thread(target=search_book, name='FORCE-SEARCHBOOK' if force else 'SEARCHBOOK',
                     args=[books, library]).start()
    logger.debug(f"Searching for {library or 'book'} with id: {books[0]['bookid']}")
    return True


def search_for_book(bookid, library: str | None = None) -> str:
    """ Search for one book now, returns its authorid """
    db = database.DBConnection()
    try:
        bookdata = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
    finally:
        db.close()
    if not bookdata:
        raise NotFoundError(f"BookID {bookid} not found")
    start_search([{"bookid": bookid}], library=library, force=True)
    return bookdata["AuthorID"]


def request_book(userid, bookid, details: dict, remote_ip: str) -> tuple:
    """ Email the admin asking for a book to be downloaded, with the details from the request.
        Returns (the book's name, whether it was sent), InvalidRequestError if the user has no email
        address and NotFoundError if there's no such user or book """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        user = db.match('SELECT Name,UserName,UserID,Email from users where UserID=?', (userid,))
        if not user:
            raise NotFoundError('Unknown user')
        bookdata = db.match("SELECT BookFile,AudioFile,AuthorName,BookName from books,authors WHERE BookID=? and "
                            "books.AuthorID = authors.AuthorID", (bookid,))
    finally:
        db.close()
    if not bookdata:
        raise NotFoundError(f"BookID {bookid} not found")
    details = {**details, **dict(bookdata), **dict(user), 'message': 'Request to Download'}
    msg = f'IP: {remote_ip}\n'
    for itm, value in details.items():
        msg += f"{itm}: {unaccented(value, only_ascii=False)}\n" if value else f"{itm}: \n"
    if not details.get('Email'):
        raise InvalidRequestError('No email address supplied')
    sent = notifiers.email_notifier.notify_message('Request from LazyLibrarian User', msg, CONFIG['ADMIN_EMAIL'])
    if not sent:
        logger.error(f"Unable to send message to: {msg}")
    return bookdata['BookName'], bool(sent)


def book_details(bookid) -> dict:
    """ A book with its author's name, and (book id column, id, link) for each source it's linked to,
        plus its Amazon link (empty without an ASIN) """
    db = database.DBConnection()
    try:
        book = db.match("SELECT books.*, AuthorName from books,authors WHERE "
                        "books.AuthorID=authors.AuthorID AND BookID=?", (bookid,))
    finally:
        db.close()
    if not book:
        raise NotFoundError(f"BookID {bookid} not found")
    book = dict(book)
    # Book-level source ids resolve to working pages via simple templates (unlike
    # author ids, which need a live API call) - stored as INFOSOURCES['link_template'],
    # only present for sources verified live against real ids from this library:
    # GoodReads bare id (no title slug) 200s, OpenLibrary work id 301s, Google Books
    # volume id 302s, DNB id 302s. HardCover/RanobeDB have no verified template and
    # ~0 usage in this library's book records, so shown as plain ids (no link_template
    # key) rather than guessed (possibly wrong) links.
    links = []
    for src in lazylibrarian.INFOSOURCES.values():
        col = src['book_key']
        if book.get(col):
            template = src.get('link_template')
            links.append((col, book[col], template.format(book[col]) if template else ''))
    amazon_link = f'https://www.amazon.com/dp/{book["ASIN"]}' if book.get('ASIN') else ''
    return {'book': book, 'links': links, 'amazon_link': amazon_link}


def lookup_asin(bookid) -> str:
    """ Fetch the book's ASIN from GoodReads' single-book endpoint (book/show/{id}.xml has asin and
        kindle_asin, the author book list used during a refresh doesn't) and store it.
        Returns it, empty if GoodReads doesn't have one """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        book = db.match("SELECT gr_id from books WHERE BookID=?", (bookid,))
        if not book or not book['gr_id']:
            raise InvalidRequestError('No GoodReads id linked to this book')
        api = lazylibrarian.INFOSOURCES['GoodReads']['api']()
        try:
            url = '/'.join([CONFIG['GR_URL'], f"book/show/{book['gr_id']}.xml?{urlencode(api.params)}"])
            rootxml, _ = gr_xml_request(url)
        except Exception as e:
            logger.error(f"lookup_book_asin error for book {bookid}: {e}")
            raise ServiceError('Lookup failed, check the logs') from e
        asin = ''
        if rootxml is not None:
            book_el = rootxml.find('book')
            if book_el is not None:
                asin_el = book_el.find('asin')
                asin = asin_el.text if asin_el is not None and asin_el.text else ''
                if not asin:
                    kasin_el = book_el.find('kindle_asin')
                    asin = kasin_el.text if kasin_el is not None and kasin_el.text else ''
        if asin:
            db.action('UPDATE books SET ASIN=? WHERE BookID=?', (asin, bookid))
        return asin
    finally:
        db.close()


def opf_fields(bookfile) -> tuple:
    """ The opf file next to a book file and its template and fields, ('', '', []) if there isn't one """
    opffile = opf_file(os.path.dirname(bookfile)) if bookfile and path_isfile(bookfile) else ''
    if opffile and path_isfile(opffile):
        opf_template, replaces = opf_read(opffile)
        return opffile, opf_template, replaces
    return opffile, '', []


def book_for_edit(bookid, library: str = 'eBook', images: bool = False) -> dict:
    """ What the edit book page needs: the book, its series, the author and series names to choose
        from, cover choices (when images is set) and the fields of its opf file that aren't edited
        elsewhere on the page """
    db = database.DBConnection()
    try:
        authors = db.select("SELECT AuthorName from authors WHERE Status !='Ignored' ORDER by AuthorName COLLATE NOCASE")
        bookdata = db.match("SELECT BookName,BookID,BookSub,BookGenre,BookLang,BookDesc,books.Manual,AuthorName,"
                            "books.AuthorID,BookDate,ScanResult,BookAdded,BookIsbn,WorkID,LT_WorkID,Narrator,BookFile,"
                            "books.gr_id,books.gb_id,books.ol_id, books.hc_id from books,authors WHERE "
                            "books.AuthorID = authors.AuthorID and BookID=?", (bookid,))
        seriesdict = db.select("SELECT SeriesName, SeriesNum from member,series where "
                               "series.SeriesID=member.SeriesID and BookID=?", (bookid,))
        if bookdata:
            series = db.select("SELECT SeriesName from series,seriesauthors WHERE series.seriesid = "
                               "seriesauthors.seriesid and authorid=? ORDER by SeriesName COLLATE NOCASE",
                               (bookdata['AuthorID'],))
    finally:
        db.close()
    if not bookdata:
        raise NotFoundError(f"BookID {bookid} not found")
    bookdata = dict(bookdata)
    bookdata['library'] = library
    if library != "AudioBook":
        bookdata.pop('Narrator', None)
    covers = []
    if images:
        sources = ['current', 'cover', 'goodreads', 'librarything', 'openlibrary', 'googleisbn', 'bing',
                   'googleimage']
        if CONFIG['HC_API']:
            sources.append('hardcover')
        for source in sources:
            cover, _ = get_book_cover(bookid, source)
            if cover:
                covers.append([source, cover])
    _, opf_template, replaces = opf_fields(bookdata['BookFile'])
    if opf_template:
        remove_file(opf_template)  # we don't need the template file yet
    # leave out the ones edited elsewhere on the page, two fields shouldn't edit the same item
    subs = [itm for itm in replaces if itm[0] not in ['title', 'creator', 'ISBN', 'date', 'description']]
    return {'book': bookdata, 'seriesdict': seriesdict, 'authors': authors, 'covers': covers, 'replaces': subs,
            'series': series}


def valid_book_date(bookdate: str) -> bool:
    """ A year (negative for BC), year-month or year-month-day that's a real date """
    if len(bookdate) <= 4:  # eg 412 BC = -412 or 400 AD = 400
        return bool(check_int(bookdate, default=0, positive=False))
    if len(bookdate) not in [7, 10] or not check_year(bookdate[:4]):
        return False
    try:
        datetime.date(int(bookdate[:4]), int(bookdate[5:7]), int(bookdate[8:]) if len(bookdate) == 10 else 1)
    except ValueError:
        return False
    return True


def import_book_files(bookid, source: str) -> str:
    """ Import the book's files from a folder (or the folder of a file), returns the scan result to record.
        Raises ServiceError if there are book files there but importing them failed """
    logger = logging.getLogger(__name__)
    folder = ''
    library = ''
    if path_isfile(source):
        folder = os.path.dirname(source)
    elif path_isdir(source):
        folder = source
    if folder:
        if book_file(folder, booktype='audiobook', config=CONFIG):
            library = 'Audio'
        elif book_file(folder, booktype='ebook', config=CONFIG):
            library = 'eBook'
    if not library:
        logger.debug(f"No {library} found in {source}")
        return ''
    if not process_book_from_dir(folder, library, bookid):
        logger.debug(f"Failed to import {bookid} from {source}")
        raise ServiceError(f"Failed to import {bookid} from {source}")
    return f'Imported manually from {folder}'


def update_book(bookid, name: str, subtitle: str, genre: str, lang: str, date: str, manual: bool, author_name: str,
                description: str, isbn: str, workid: str, cover: str = '', newid: str = '', series=(),
                opf_values: dict | None = None, import_from: str = '') -> str:
    """ Change a book's details, series and author, returns what changed (empty if nothing did).

        date is left alone if it isn't a date, '0000' clears it. cover is one of the covers book_for_edit
        offered. series lists (name, number) for every series the book is in, ones without a number are
        dropped. opf_values are new values for the fields of its opf file, which is rewritten if anything
        changed. import_from is a folder or file to import the book's files from first. A new author_name
        moves the book to that author, if we have them.
    """
    logger = logging.getLogger(__name__)
    opf_values = opf_values or {}
    db = database.DBConnection()
    try:
        scanresult = import_book_files(bookid, import_from) if import_from else ''
        bookdata = db.match("SELECT BookName,BookSub,BookGenre,BookLang,BookImg,BookDate,BookDesc,books.Manual,"
                            "AuthorName,books.AuthorID, BookIsbn, WorkID, ScanResult, BookFile from books,authors "
                            "WHERE books.AuthorID = authors.AuthorID and BookID=?", (bookid,))
        if not bookdata:
            raise NotFoundError(f"BookID {bookid} not found")
        edited = ''
        moved = False
        if genre == 'None':
            genre = ''
        if newid and bookid != newid:
            match = db.match("SELECT BookName,Authorname from books,authors WHERE "
                             "books.AuthorID = authors.AuthorID and BookID=?", (newid,))
            if match:
                logger.warning(f"Cannot change bookid to {newid}, in use by {match['BookName']}/{match['AuthorName']}")
            else:
                logger.warning("Updating bookid is not supported yet")
        if scanresult and bookdata['ScanResult'] != scanresult:
            edited += "ScanResult "
        for field, value, label in (('BookName', name, 'Title'), ('BookSub', subtitle, 'Subtitle'),
                                    ('BookDesc', description, 'Description'), ('BookGenre', genre, 'Genre'),
                                    ('BookLang', lang, 'Language'), ('BookIsbn', isbn, 'ISBN'),
                                    ('WorkID', workid, 'WorkID')):
            if bookdata[field] != value:
                edited += f"{label} "
        if bookdata['BookDate'] != date:
            if date == '0000' or valid_book_date(date):
                edited += "Date "
            else:
                date = bookdata["BookDate"]
        if bool(check_int(bookdata['Manual'], 0)) != manual:
            edited += "Manual "
        if bookdata['AuthorName'] != author_name:
            moved = True

        coverlink = bookdata['BookImg']
        covertype = COVER_SUFFIXES.get(cover, '')
        if covertype:
            coverid = uuid.uuid4().hex
            coverlink = 'cache/book/' + coverid + '.jpg'
            coverfile = os.path.join(DIRS.CACHEDIR, "book", coverid + '.jpg')
            newcoverfile = os.path.join(DIRS.CACHEDIR, "book", bookid + covertype + '.jpg')
            if not path_exists(newcoverfile):
                logger.error(f"Coverfile {newcoverfile} for {bookid} is missing")
            else:
                try:
                    edited += f'Cover ({cover})'
                    dest = copyfile(newcoverfile, coverfile)
                    logger.debug(f"{newcoverfile} {coverlink} {dest}")
                except Exception as e:
                    logger.error(str(e))

        if edited:
            db.upsert("books", {'BookName': name, 'BookSub': subtitle, 'BookGenre': genre, 'BookLang': lang,
                                'BookDate': date, 'BookDesc': description, 'BookIsbn': isbn, 'WorkID': workid,
                                'BookImg': coverlink, 'ScanResult': scanresult, 'Manual': bool(manual)},
                      {'BookID': bookid})

        old_list = [[s['SeriesID'], s['SeriesNum'], s['SeriesName']] for s in db.select(
            "SELECT SeriesName, SeriesNum, series.SeriesID from member,series where "
            "series.SeriesID=member.SeriesID and BookID=?", (bookid,))]
        new_list = []
        for s_name, s_num in series:
            s_name = clean_name(s_name, '&/')
            match = db.match('SELECT SeriesID from series WHERE SeriesName=?', (s_name,))
            new_list.append([match['SeriesID'] if match else '', s_num, s_name])
        logger.debug(f"Old series list for {bookid}: {old_list}")
        new_list = [itm for itm in new_list if itm[1]]
        logger.debug(f"New series list for {bookid}: {new_list}")
        if any(itm[1:] not in [i[1:] for i in new_list] for itm in old_list) or \
                any(itm[1:] not in [i[1:] for i in old_list] for itm in new_list):
            set_series(new_list, bookid, reason=scanresult)
            delete_empty_series()
            edited += "Series "
        else:
            logger.debug("No series changes")

        opffile, opf_template, replaces = opf_fields(bookdata['BookFile'])
        if opf_template:
            subs = []
            for itm in replaces:
                if itm[0] == 'title':
                    subs.append((itm[0], name))
                elif itm[0] == 'creator':
                    subs.append((itm[0], author_name))
                elif itm[0] == 'ISBN':
                    subs.append((itm[0], isbn))
                elif itm[0] == 'date':
                    subs.append((itm[0], date))
                elif itm[0] == 'description':
                    subs.append((itm[0], description))
                elif itm[0] in opf_values and itm[1] != opf_values[itm[0]]:
                    edited += itm[0] + ' '
                    subs.append((itm[0], opf_values[itm[0]]))
                else:
                    subs.append((itm[0], itm[1]))
            if edited:
                new_opf = opf_write(opf_template, subs)
                remove_file(opf_template)
                remove_file(opffile)
                try:
                    safe_move(new_opf, opffile)
                except Exception as e:
                    logger.warning(f"Failed to move file: {str(e)}")
                    moved = False
        if edited:
            logger.info(f'Updated [ {edited}] for {name}')
        else:
            logger.debug(f'Book [{name}] has not been changed')

        if moved:
            authordata = db.match('SELECT AuthorID from authors WHERE AuthorName=?', (author_name,))
            if authordata:
                db.upsert("books", {'AuthorID': authordata['AuthorID']}, {'BookID': bookid})
                update_totals(bookdata["AuthorID"])  # we moved from here
                update_totals(authordata['AuthorID'])  # to here
            logger.info(f'Book [{name}] has been moved')
        else:
            logger.debug(f'Book [{name}] has not been moved')
        if edited or moved:
            data = db.match("SELECT * from books,authors WHERE books.authorid=authors.authorid and BookID=?", (bookid,))
            if data['BookFile'] and path_isfile(data['BookFile']):
                dest_path = os.path.dirname(data['BookFile'])
                global_name = splitext(os.path.basename(data['BookFile']))[0]
                if opf_template and CONFIG.get_bool('IMP_EBOOKOPF'):  # we already have a valid (new) opffile
                    dest_opf = os.path.join(dest_path, global_name + '.opf')
                    if opffile != dest_opf:
                        try:
                            safe_copy(opffile, dest_opf)
                        except Exception as e:
                            logger.warning(f"Failed to copy opf file: {str(e)}")
                elif CONFIG.get_bool('IMP_EBOOKOPF'):
                    create_opf(dest_path, data, global_name, overwrite=True)
        return edited
    finally:
        db.close()


def set_narrator(bookid, narrator: str):
    """ Change an audiobook's narrator """
    db = database.DBConnection()
    try:
        db.action("UPDATE books SET Narrator=? WHERE BookID=?", (narrator, bookid))
    finally:
        db.close()
    logging.getLogger(__name__).info(f"Narrator of {bookid} is now {narrator}")


def add_search_results(action: str, ids) -> tuple[int, int]:
    """ Add books (AddBook, AddAudio or AddBoth to want the ebook, audiobook or both) or authors
        (AddAuthor) from the info source search results. Returns (passed, failed) """
    passed = failed = 0
    if action in ['AddBook', 'AddAudio', 'AddBoth']:
        api = lazylibrarian.INFOSOURCES[CONFIG['BOOK_API']]['api']()
        wantbook = "Wanted" if action in ['AddBook', 'AddBoth'] else 'Skipped'
        wantaudio = "Wanted" if action in ['AddAudio', 'AddBoth'] else 'Skipped'
        for itm in ids:
            if api.add_bookid_to_db(itm, wantbook, wantaudio, f"Added by User from resultlist {wantbook}:{wantaudio}"):
                passed += 1
            else:
                failed += 1
    elif action == 'AddAuthor':
        books = bool(CONFIG['NEWAUTHOR_STATUS'] != 'Ignored') or bool(CONFIG['NEWAUTHOR_AUDIO'] != 'Ignored')
        for itm in ids:
            if add_author_to_db(refresh=False, authorid=itm, addbooks=books, reason=f"User add_author_id {itm}"):
                passed += 1
            else:
                failed += 1
    return passed, failed


def delete_book_files(db, bookid, bookdata, library: str) -> int:
    """ Delete a book's ebook and/or audiobook folder, and the ebook from Calibre. Returns how many failed """
    logger = logging.getLogger(__name__)
    failed = 0
    for lib, column in (('AudioBook', 'AudioFile'), ('eBook', 'BookFile')):
        if lib not in library:
            continue
        bookfile = bookdata[column]
        if bookfile and path_isfile(bookfile):
            try:
                rmtree(os.path.dirname(bookfile))
                logger.info(f'{lib} {os.path.dirname(bookfile)} deleted from disc')
                db.action(f"UPDATE books SET {column}='' WHERE BookID=?", (bookid,))
                if lib == 'eBook' and CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_EBOOK'):
                    remove_from_calibre(bookdata)
            except Exception as e:
                logger.warning(f'rmtree failed on {bookfile}, {type(e).__name__} {str(e)}')
                failed += 1
    return failed


def mark_books(action: str, bookids, library: str = 'eBook', userid=None, authorid=None) -> dict:
    """ Mark books: put them on or take them off the user's reading lists (READING_ACTIONS), want them
        (WANT_ACTIONS), set Have, Skipped or Ignored (see status_mark_targets), search for them again now
        (NoDelay), or ignore them (Remove), deleting their files first (Delete). library says which of
        eBook and AudioBook the plain actions apply to. Searches for wanted books start straight away.

        authorid's totals are updated along with those of the books' authors. Returns passed and failed
        counts, and authorid, the author of the last book marked (or the one given)
    """
    logger = logging.getLogger(__name__)
    passed = failed = 0
    wantedbooks = []
    wantedaudio = []
    check_totals = [authorid] if authorid else []
    if not action:
        return {'passed': passed, 'failed': failed, 'authorid': authorid}
    lists = reading_lists(userid) if action in READING_ACTIONS else {}
    db = database.DBConnection()
    try:
        for bookid in bookids:
            if action in READING_ACTIONS:
                for books in lists.values():
                    books.discard(bookid)
                move_to = {'Read': 'HaveRead', 'ToRead': 'ToRead', 'Reading': 'Reading', 'Abandoned': 'Abandoned'}
                if action in move_to and lists:
                    lists[move_to[action]].add(bookid)
                logger.debug(f'Status set to {action} for {bookid}')
                passed += 1

            elif action in WANT_ACTIONS or status_mark_targets(action, library):
                bookdata = db.match('SELECT AuthorID,BookName,Status,AudioStatus from books WHERE BookID=?', (bookid,))
                if not bookdata:
                    logger.warning(f"Unable to set status {action} for {bookid}")
                    failed += 1
                    continue
                authorid = bookdata['AuthorID']
                bookname = bookdata['BookName']
                if authorid not in check_totals:
                    check_totals.append(authorid)
                for lib, column, label, want, wanted in (
                        ('eBook', 'Status', 'eBook', ["WantEbook", "WantBoth"], wantedbooks),
                        ('AudioBook', 'AudioStatus', 'AudioBook', ["WantAudio", "WantBoth"], wantedaudio)):
                    if (action == "Wanted" and lib in library) or action in want:
                        if bookdata[column] in ["Open", "Have"]:
                            logger.debug(f'{label} "{bookname}" is already marked Open')
                            failed += 1
                        else:
                            # ScanResult set here too, matching the Ignored/Skipped/Have
                            # actions below - otherwise re-wanting a previously-deleted
                            # book leaves its stale "User deleted" ScanResult in place
                            # with no indication the book is active again.
                            db.upsert("books", {column: 'Wanted', 'ScanResult': 'User Wanted'}, {'BookID': bookid})
                            logger.debug(f'{column} set to "Wanted" for "{bookname}"')
                            wanted.append({"bookid": bookid})
                            passed += 1
                targets = status_mark_targets(action, library)
                if targets:
                    status, mark_library = targets
                    for lib, column in (('eBook', 'Status'), ('AudioBook', 'AudioStatus')):
                        if lib in mark_library:
                            db.upsert("books", {column: status, 'ScanResult': f'User {status}'}, {'BookID': bookid})
                            logger.debug(f'{column} set to "{status}" for "{bookname}"')
                            passed += 1

            elif action == "NoDelay":
                for lib in ('eBook', 'AudioBook'):
                    if lib in library:
                        db.action("delete from failedsearch WHERE BookID=? AND Library=?", (bookid, lib))
                logger.debug(f'{library} delay set to zero for {bookid}')
                passed += 1

            elif action in ["Remove", "Delete"]:
                bookdata = db.match("SELECT AuthorName,Bookname,BookFile,AudioFile,books.AuthorID from books,authors "
                                    "WHERE BookID=? and books.AuthorID = authors.AuthorID", (bookid,))
                if not bookdata:
                    continue
                authorid = bookdata['AuthorID']
                bookname = bookdata['BookName']
                if authorid not in check_totals:
                    check_totals.append(authorid)
                if action == "Delete":
                    failed += delete_book_files(db, bookid, bookdata, library)
                for lib, column, label in (('eBook', 'Status', 'ebook'), ('AudioBook', 'AudioStatus', 'audiobook')):
                    if lib in library:
                        db.upsert("books", {column: "Ignored", "ScanResult": f"User {action}d {label}"},
                                  {"BookID": bookid})
                        logger.debug(f'{column} set to Ignored for "{bookname}"')
                        passed += 1
                if action == 'Delete':
                    bookcheck = db.match('SELECT Status,AudioStatus from books WHERE BookID=?', (bookid,))
                    if bookcheck['Status'] == bookcheck['AudioStatus'] == 'Ignored':
                        for table in ['books', 'wanted', 'readinglists']:
                            db.action(f"DELETE from {table} WHERE BookID=?", (bookid,))
                update_totals(authorid)

        if lists and userid:
            for name, books in lists.items():
                set_readinglist(name, userid, books)
            # set_readinglist only adds, so take the books now on none of the lists (Unread) off them here
            statuses = ', '.join(str(reading_status[name.lower()]) for name in READING_LISTS)
            for bookid in bookids:
                if not any(bookid in books for books in lists.values()):
                    db.action(f'DELETE from readinglists WHERE UserID=? AND BookID=? AND Status IN ({statuses})',
                              (userid, bookid))
    finally:
        db.close()

    for author in check_totals:
        update_totals(author)
    if CONFIG.use_any() and check_int(CONFIG['SEARCH_BOOKINTERVAL'], 0):
        if wantedbooks:
            logger.debug(f"Starting ebook search thread, library={library}, action={action}")
            threading.Thread(target=search_book, name='SEARCHBOOK', args=[wantedbooks, 'eBook']).start()
        if wantedaudio:
            logger.debug(f"Starting audio search thread, library={library}, action={action}")
            threading.Thread(target=search_book, name='SEARCHBOOK', args=[wantedaudio, 'AudioBook']).start()
    return {'passed': passed, 'failed': failed, 'authorid': authorid}


def description(itemid) -> dict | None:
    """ The picture, title and description of a book, an author (A_ then their id) or a comic
        (its comicid, or comicid_issueid for an issue), with AuthorID for a book. None if not found """
    db = database.DBConnection()
    try:
        if itemid.startswith('A_'):
            res = db.match("SELECT AuthorName,About,AuthorImg from authors WHERE authorid=?", (itemid[2:],))
        elif itemid.startswith(('CV', 'CX')):
            try:
                comicid, issueid = itemid.split('_')
                res = db.match("SELECT Title as BookName,comicissues.Description as BookDesc,Cover as BookImg,"
                               "Contributors from comics,comicissues where comics.comicid = comicissues.comicid "
                               "and comics.comicid=? and issueid=?", (comicid, issueid))
            except ValueError:
                res = db.match("SELECT Title as BookName,Description as BookDesc,LatestCover as BookImg from comics "
                               "where comicid=?", (itemid,))
        else:
            res = db.match("SELECT BookName,BookDesc,BookImg,AuthorID from books WHERE bookid=?", (itemid,))
    finally:
        db.close()
    if not res:
        return None
    res = dict(res)
    text = res.get('BookDesc') or res.get('About')
    if res.get('Contributors'):
        text = f"{text or ''}<br><br>{res['Contributors']}"
    return {'img': res.get('BookImg') or res.get('AuthorImg'), 'title': res.get('BookName') or res.get('AuthorName'),
            'text': text, 'AuthorID': res.get('AuthorID')}

