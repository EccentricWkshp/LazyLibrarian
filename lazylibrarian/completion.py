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

""" A book's or an author's missing details filled in from every enabled info source, as each is
often missing pieces: the one a book came from first (by its id), then the others, where the same
book is found by its ISBN or by its title and author. Only what's missing is filled in, what's there
is never changed, and a book or author edited by hand (Manual) is left as it is. Each detail filled
in records its source (FilledFrom), and when the sources were last asked (Completed), so they're
asked again only after CACHE_AGE days.

Books are completed in the background as they're added and their authors refreshed, one at a time
in a thread of their own (queue), or all that are due by the CompleteBooks command """

import datetime
import json
import logging
import queue
import re
import threading

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import database
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_float, check_int, get_list, is_valid_isbn, today

# a book's details that are filled in: its column, and the key a source's book has it under
BOOK_FIELDS = (('BookDesc', 'bookdesc'), ('BookIsbn', 'bookisbn'), ('BookPub', 'bookpub'),
               ('BookPages', 'bookpages'), ('BookDate', 'bookdate'), ('BookLang', 'booklang'),
               ('BookGenre', 'bookgenre'), ('BookRate', 'bookrate'), ('BookImg', 'bookimg'),
               ('BookSub', 'booksub'))
AUTHOR_FIELDS = (('About', 'about'), ('AuthorBorn', 'authorborn'), ('AuthorDeath', 'authordeath'),
                 ('AuthorImg', 'authorimg'))
# what sources put for a description they haven't got
NO_DESCRIPTION = ('not available', 'no description', 'no description available', 'none', 'n/a')
# how alike a source's title and author have to be for its book to be the same one, out of 100
SAME_TITLE = 90
SAME_AUTHOR = 88
# fewer pages than this is a source's mistake (OpenLibrary's median of its editions can be 1)
MIN_PAGES = 10

_queue: queue.Queue = queue.Queue()
_queued: set = set()
_lock = threading.Lock()
_worker: threading.Thread | None = None


def is_missing(column: str, value) -> bool:
    """ Whether a book's or author's detail is missing: empty, or what a source puts for none """
    text = str(value or '').strip()
    if column in ('BookImg', 'AuthorImg'):
        return not text or 'nocover' in text or 'nophoto' in text
    if column in ('BookPages', 'BookRate'):
        return check_float(text, 0) <= 0
    if column == 'BookLang':
        return text.lower() in ('', 'unknown', 'und')
    if column == 'BookDate':
        return text in ('', '0000', '0')
    if column in ('BookDesc', 'About'):
        return text.lower().strip('.') in NO_DESCRIPTION or len(text) < 10
    return not text


def _text(value) -> str:
    if isinstance(value, (list, tuple)):
        return ', '.join(str(item).strip() for item in value if str(item).strip())
    return str(value or '').strip()


def _isbn13(isbn: str) -> str:
    """ An ISBN as its 13 digits, '' for one that isn't valid """
    isbn = str(isbn or '').replace('-', '').replace(' ', '')
    if not is_valid_isbn(isbn):
        return ''
    if len(isbn) == 13:
        return isbn
    digits = f"978{isbn[:9]}"
    check = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits)) % 10) % 10
    return f"{digits}{check}"


def _isbns(value) -> set[str]:
    return {found for found in (_isbn13(item) for item in get_list(_text(value))) if found}


def _value(column: str, raw):
    """ A source's detail as the column keeps it, or None when it hasn't got it """
    if raw is None:
        return None
    if column == 'BookIsbn':
        found = next((item for item in get_list(_text(raw)) if is_valid_isbn(item)), '')
        return found.replace('-', '') or None
    if column == 'BookPages':
        pages = check_int(raw, 0)
        return pages if pages >= MIN_PAGES else None
    if column == 'BookRate':
        rate = check_float(raw, 0)
        return rate if rate > 0 else None
    if column == 'BookDate':
        date = _text(raw)
        return date[:10] if re.match(r'^\d{4}(-\d\d(-\d\d)?)?', date) and not is_missing(column, date) else None
    text = _text(raw)
    return None if is_missing(column, text) else text


def _main_title(title: str) -> str:
    """ A title without its subtitle or the series in brackets after it, as titles are compared """
    return default_process(_search_title(title))


def same_book(row: dict, author: str, found: dict) -> bool:
    """ Whether a source's book is the library's: an ISBN they share, or their titles and authors """
    if _isbns(row.get('BookIsbn')) & _isbns(found.get('bookisbn')):
        return True
    if fuzz.token_sort_ratio(author, found.get('authorname', ''), processor=default_process) < SAME_AUTHOR:
        return False
    return fuzz.ratio(_main_title(row['BookName']), _main_title(found.get('bookname', ''))) >= SAME_TITLE


def _sources(own: str = '') -> list[str]:
    """ The enabled info sources that aren't blocked, the book's own first, then the one set as the
    main source, then the others """
    order = [own, CONFIG['BOOK_API'], *lazylibrarian.INFOSOURCES]
    found = []
    for name in order:
        source = lazylibrarian.INFOSOURCES.get(name)
        if name and source and name not in found and CONFIG[source['enabled']] and not BLOCKHANDLER.is_blocked(name):
            found.append(name)
    return found


def _id_column(name: str) -> str:
    """ The column a book's id at a source is kept in, gr_id """
    column = lazylibrarian.INFOSOURCES.get(name, {}).get('book_key', '')
    return '' if column == 'bookid' else column


def _own_source(row: dict) -> str:
    """ The source a book came from, the one whose id is its BookID """
    return next((name for name in lazylibrarian.INFOSOURCES
                 if _id_column(name) and row.get(_id_column(name)) == row['BookID']), '')


def _search_title(title: str) -> str:
    """ A title as it's searched for, without its subtitle or the series in brackets after it """
    return re.split(r'\s*[:(\[]', str(title or ''), maxsplit=1)[0].strip() or str(title or '')


def _details(name: str, bookid: str) -> dict:
    """ A source's book by its id there, {} when it can't give one that way """
    api = lazylibrarian.INFOSOURCES[name]['api']()
    if not hasattr(api, 'get_bookdict_for_bookid'):
        return {}
    found = api.get_bookdict_for_bookid(bookid)
    if isinstance(found, tuple):
        found = found[0]
    return found or {}


def _find(name: str, row: dict, author: str) -> dict:
    """ The same book at a source, by its ISBN or its title and author, {} if it isn't there """
    from lazylibrarian.importer import search_for  # noqa: PLC0415, it imports most of LazyLibrarian
    terms = [isbn for isbn in get_list(row.get('BookIsbn')) if is_valid_isbn(isbn)][:1]
    terms.append(f"{_search_title(row['BookName'])}<ll>{author}")
    for term in terms:
        results = search_for(term, name, max_pages=1) or []
        for found in sorted(results, key=lambda result: -check_float(result.get('highest_fuzz'), 0)):
            if same_book(row, author, found):
                return found
    return {}


def _filled(column: str, value, bookid: str, name: str):
    """ A detail as it's written: a cover is kept in the cache """
    if column == 'BookImg' and str(value).startswith('http'):
        from lazylibrarian.images import cache_bookimg  # noqa: PLC0415, it imports most of LazyLibrarian
        cached = cache_bookimg(value, bookid, name.lower())
        return cached if cached and not is_missing(column, cached) else None
    return value


def complete_book(bookid: str, force: bool = False) -> dict:
    """ Fill in a book's missing details from the info sources, unless they were asked within
    CACHE_AGE days (force asks again). Returns {column: source} for what was filled in """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        row = db.match('SELECT books.*,AuthorName from books,authors WHERE books.AuthorID=authors.AuthorID '
                       'AND BookID=?', (bookid,))
        if not row:
            return {}
        row = dict(row)
    finally:
        db.close()
    if check_int(row.get('Manual'), 0):
        logger.debug(f"Not completing {row['BookName']}, it was edited by hand")
        return {}
    if not force and not _due(row.get('Completed')):
        return {}
    from lazylibrarian.images import chosen_cover  # noqa: PLC0415, it imports most of LazyLibrarian
    missing = [(column, key) for column, key in BOOK_FIELDS if is_missing(column, row.get(column)) and
               not (column == 'BookImg' and chosen_cover(row.get('BookImg')))]
    want_series = CONFIG.get_bool('ADD_SERIES') and not _has_series(bookid)
    filled, ids, series = {}, {}, None
    own = _own_source(row)
    for name in _sources(own):
        if not missing and not (want_series and series is None):
            break
        try:
            id_column = _id_column(name)
            known = row.get(id_column) if id_column else ''
            found = _details(name, known) if known else {}
            if not found or any(_value(column, found.get(key)) is None for column, key in missing):
                # its search result has what its book by id hasn't, OpenLibrary's editions' ISBN
                # and pages beside its work
                searched = _find(name, row, row['AuthorName'])
                if searched and searched.get('bookid'):
                    if not found:
                        # the whole book where the source can give it, not just its search result
                        found = _details(name, searched['bookid'])
                        if id_column and not known:
                            ids[id_column] = searched['bookid']
                    found = {**searched, **{key: value for key, value in found.items() if value}}
        except Exception as e:
            logger.warning(f"Completing {row['BookName']} from {name} failed: {type(e).__name__} {e}")
            continue
        if not found:
            continue
        for column, key in list(missing):
            value = _value(column, found.get(key))
            if value is not None:
                value = _filled(column, value, bookid, name)
            if value is not None:
                filled[column] = (value, name)
                missing.remove((column, key))
        # a year alone, from one source, gives way to the whole date of that year from another
        year = filled.get('BookDate', ('', ''))[0]
        whole = _value('BookDate', found.get('bookdate'))
        if len(year) == 4 and whole and len(whole) > 4 and whole.startswith(year):
            filled['BookDate'] = (whole, name)
        if want_series and series is None and found.get('series'):
            series = (found['series'], name)
    if ('BookImg', 'bookimg') in missing:
        # a cover where else covers are looked for: beside its file, by its ISBN, at its sources
        cover = _found_cover(bookid, {**row, **{column: value for column, (value, _) in filled.items()},
                                      **ids})
        if cover:
            filled['BookImg'] = cover
    _write_book(row, filled, ids, series)
    done = {column: source for column, (_, source) in filled.items()}
    if series:
        done['Series'] = series[1]
    if done:
        logger.info(f"{row['BookName']} by {row['AuthorName']}: {described(done)}")
    return done


# what each detail is called, to say what was filled in
NAMES = {'BookDesc': 'description', 'BookIsbn': 'ISBN', 'BookPub': 'publisher', 'BookPages': 'pages',
         'BookDate': 'date', 'BookLang': 'language', 'BookGenre': 'genres', 'BookRate': 'rating',
         'BookImg': 'cover', 'BookSub': 'subtitle', 'About': 'about', 'AuthorBorn': 'born',
         'AuthorDeath': 'died', 'AuthorImg': 'picture', 'Series': 'series'}


def described(filled: dict) -> str:
    """ What was filled in from where, "description and pages from OpenLibrary, cover from GoogleBooks" """
    by_source = {}
    for column, source in filled.items():
        by_source.setdefault(source, []).append(NAMES.get(column, column))
    return ', '.join(f"{' and '.join(names) if len(names) < 3 else ', '.join(names[:-1]) + ' and ' + names[-1]} "
                     f"from {source}" for source, names in by_source.items())


def _found_cover(bookid: str, book: dict) -> tuple[str, str] | None:
    """ The cover images.get_book_cover finds for a book as it is with what's been filled in (its
    ISBN, its ids at the other sources), and where, or None """
    from lazylibrarian.images import get_book_cover  # noqa: PLC0415, it imports most of LazyLibrarian
    db = database.DBConnection()
    try:
        # it looks for the book's ISBN and ids in the database
        columns = [column for column in ('BookIsbn', *(_id_column(name) for name in lazylibrarian.INFOSOURCES))
                   if column and book.get(column)]
        if columns:
            db.action(f"UPDATE books SET {', '.join(f'{column}=?' for column in columns)} WHERE BookID=?",
                      (*(book[column] for column in columns), bookid))
    finally:
        db.close()
    link, source = get_book_cover(bookid)
    if link and not is_missing('BookImg', link):
        return link, COVER_SOURCES.get(source, source or 'a cover search')
    return None


# where images.get_book_cover found a cover, as it's said
COVER_SOURCES = {'cover': 'its file', 'cache': 'the cache', 'openlibrary': 'OpenLibrary', 'goodreads': 'GoodReads',
                 'hardcover': 'HardCover', 'googleisbn': 'GoogleBooks', 'librarything': 'LibraryThing',
                 'ranobedb': 'RanobeDB'}


def _has_series(bookid: str) -> bool:
    db = database.DBConnection()
    try:
        return bool(db.match('SELECT SeriesID from member WHERE BookID=?', (bookid,)))
    finally:
        db.close()


def _due(completed) -> bool:
    """ Whether the sources weren't asked for a book's or author's details within CACHE_AGE days """
    if not completed:
        return True
    try:
        then = datetime.date.fromisoformat(str(completed)[:10])
    except ValueError:
        return True
    return (datetime.date.today() - then).days >= max(CONFIG.get_int('CACHE_AGE'), 1)


def _write_book(row: dict, filled: dict, ids: dict, series):
    from lazylibrarian.bookwork import genre_filter, set_genres  # noqa: PLC0415, it imports most of LazyLibrarian
    bookid = row['BookID']
    sources = _sources_of(row.get('FilledFrom'))
    sources.update({column: source for column, (_, source) in filled.items()})
    if series:
        sources['Series'] = series[1]
    changes = {column: value for column, (value, _) in filled.items() if column != 'BookGenre'}
    changes.update(ids)
    changes.update({'Completed': today(), 'FilledFrom': json.dumps(sources) if sources else ''})
    db = database.DBConnection()
    try:
        db.action(f"UPDATE books SET {', '.join(f'{column}=?' for column in changes)} WHERE BookID=?",
                  (*changes.values(), bookid))
        if series:
            from lazylibrarian.bookdict import add_series_members  # noqa: PLC0415
            add_series_members(db, bookid, row['AuthorID'], row['AuthorName'], series[0], series[1])
    finally:
        db.close()
    if 'BookGenre' in filled:
        genres = [genre for genre in (genre_filter(item) for item in get_list(filled['BookGenre'][0], ',')) if genre]
        if genres:
            set_genres(genres, bookid)


def _sources_of(value) -> dict:
    try:
        found = json.loads(value) if value else {}
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def complete_author(authorid: str, force: bool = False) -> dict:
    """ Fill in an author's missing details (about, born, died, picture) from the info sources that
    know authors, by the author's id at each or found by their name. Returns {column: source} """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        row = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        title = db.match('SELECT BookName from books WHERE AuthorID=?', (authorid,))
    finally:
        db.close()
    if not row:
        return {}
    row = dict(row)
    if check_int(row.get('Manual'), 0) or (not force and not _due(row.get('Completed'))):
        return {}
    missing = [(column, key) for column, key in AUTHOR_FIELDS if is_missing(column, row.get(column))]
    filled, ids = {}, {}
    for name in _sources(row.get('PrimarySource') or ''):
        source = lazylibrarian.INFOSOURCES[name]
        id_column = source['author_key']
        if not missing:
            break
        if not id_column or id_column == 'authorid':  # a source without author ids
            continue
        try:
            api = source['api']()
            known = row.get(id_column) or (row['AuthorID'] if name == CONFIG['BOOK_API'] else '')
            if not known:
                found = api.find_author_id(authorname=row['AuthorName'], title=title['BookName'] if title else '')
                known = (found or {}).get('authorid', '')
                if known:
                    ids[id_column] = known
            info = api.get_author_info(authorid=known, authorname=row['AuthorName']) if known else {}
        except Exception as e:
            logger.warning(f"Completing {row['AuthorName']} from {name} failed: {type(e).__name__} {e}")
            continue
        if not info or fuzz.token_sort_ratio(row['AuthorName'], info.get('authorname', ''),
                                             processor=default_process) < SAME_AUTHOR:
            ids.pop(id_column, None)
            continue
        for column, key in list(missing):
            value = _value(column, info.get(key))
            if value is not None and column == 'AuthorImg' and str(value).startswith('http'):
                from lazylibrarian.cache import ImageType, cache_img  # noqa: PLC0415
                from lazylibrarian.images import img_id  # noqa: PLC0415
                cached, success, _ = cache_img(ImageType.AUTHOR, img_id(), value)
                value = cached if success else None
            if value is not None:
                filled[column] = (value, name)
                missing.remove((column, key))
    sources = _sources_of(row.get('FilledFrom'))
    sources.update({column: source for column, (_, source) in filled.items()})
    changes = {column: value for column, (value, _) in filled.items()}
    changes.update(ids)
    changes.update({'Completed': today(), 'FilledFrom': json.dumps(sources) if sources else ''})
    db = database.DBConnection()
    try:
        db.action(f"UPDATE authors SET {', '.join(f'{column}=?' for column in changes)} WHERE AuthorID=?",
                  (*changes.values(), authorid))
    finally:
        db.close()
    done = {column: source for column, (_, source) in filled.items()}
    if done:
        logger.info(f"{row['AuthorName']}: {described(done)}")
    return done


# what's missing from a book, as SQL, to find the ones worth asking the sources about
BOOK_GAPS = ("(BookDesc IS NULL OR length(BookDesc) < 10 OR lower(BookDesc) IN ('not available', 'no description') "
             "OR BookIsbn IS NULL OR BookIsbn='' OR BookPub IS NULL OR BookPub='' OR IFNULL(BookPages,0)=0 "
             "OR BookDate IS NULL OR BookDate IN ('', '0000') OR BookLang IS NULL OR BookLang IN ('', 'Unknown') "
             "OR BookGenre IS NULL OR BookGenre='' OR IFNULL(BookRate,0)=0 OR BookImg IS NULL OR BookImg='' "
             "OR instr(BookImg,'nocover')>0)")
AUTHOR_GAPS = ("(About IS NULL OR length(About) < 10 OR AuthorBorn IS NULL OR AuthorBorn='' OR AuthorImg IS NULL "
               "OR AuthorImg='' OR instr(AuthorImg,'nophoto')>0)")


def due_books(authorid: str = '', limit: int = 0) -> list[str]:
    """ The books missing details whose sources weren't asked within CACHE_AGE days, an author's when
    given, the ones the library has or wants first """
    cutoff = (datetime.date.today() - datetime.timedelta(days=max(CONFIG.get_int('CACHE_AGE'), 1))).isoformat()
    cmd = (f"SELECT BookID from books WHERE {BOOK_GAPS} AND IFNULL(Manual,'0') IN ('', '0') AND "
           f"(IFNULL(Completed,'')='' OR Completed < ?)")
    args = [cutoff]
    if authorid:
        cmd += " AND AuthorID=?"
        args.append(authorid)
    cmd += (" ORDER BY (Status IN ('Open','Have','Wanted','Snatched') OR AudioStatus IN "
            "('Open','Have','Wanted','Snatched')) DESC, BookAdded DESC")
    if limit:
        cmd += f" LIMIT {int(limit)}"
    db = database.DBConnection()
    try:
        return [row['BookID'] for row in db.select(cmd, tuple(args))]
    finally:
        db.close()


def due_authors(limit: int = 0) -> list[str]:
    cutoff = (datetime.date.today() - datetime.timedelta(days=max(CONFIG.get_int('CACHE_AGE'), 1))).isoformat()
    cmd = (f"SELECT AuthorID from authors WHERE {AUTHOR_GAPS} AND IFNULL(Manual,'0') IN ('', '0') AND "
           f"Status != 'Ignored' AND (IFNULL(Completed,'')='' OR Completed < ?)")
    if limit:
        cmd += f" LIMIT {int(limit)}"
    db = database.DBConnection()
    try:
        return [row['AuthorID'] for row in db.select(cmd, (cutoff,))]
    finally:
        db.close()


def queue_books(bookids, authorid: str = ''):
    """ Complete these books, and the author, in the background, one at a time """
    if not CONFIG.get_bool('FILL_MISSING'):
        return
    items = [('author', authorid)] if authorid else []
    items += [('book', bookid) for bookid in bookids if bookid]
    global _worker
    with _lock:
        for item in items:
            if item not in _queued:
                _queued.add(item)
                _queue.put(item)
        if items and (_worker is None or not _worker.is_alive()):
            _worker = threading.Thread(target=_work, name='COMPLETE-INFO', daemon=True)
            _worker.start()


def queue_author(authorid: str):
    """ An author, and their books that are missing details, completed in the background """
    if CONFIG.get_bool('FILL_MISSING') and authorid:
        queue_books(due_books(authorid), authorid)


def _work():
    global _worker
    logger = logging.getLogger(__name__)
    while True:
        try:
            item = _queue.get(timeout=30)
        except queue.Empty:
            with _lock:
                if _queue.empty():
                    _worker = None
                    return
            continue
        try:
            if item[0] == 'author':
                complete_author(item[1])
            else:
                complete_book(item[1])
        except Exception as e:
            logger.warning(f"Completing {item[0]} {item[1]} failed: {type(e).__name__} {e}")
        finally:
            with _lock:
                _queued.discard(item)


def pending() -> int:
    """ How many books and authors are waiting to be completed in the background """
    with _lock:
        return len(_queued)
