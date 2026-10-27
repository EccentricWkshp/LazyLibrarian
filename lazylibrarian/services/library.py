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

""" The library as the front end's pages show it, like Sonarr's series pages: the authors, one
author with their books, the eBooks and audiobooks, magazines and comics with their issues, the
series, and changing what's wanted of them. The old pages' services do the work, this shapes it
for /api/v1 """

import logging
import os
import re

import lazylibrarian
from lazylibrarian import database, quality
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_float, check_int, fold, natural_sort
from lazylibrarian.importer import author_name_key, update_totals
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    authors,
    books,
    comics,
    magazines,
    series,
)
from lazylibrarian.services.paging import Page

AUTHOR_STATUSES = authors.AUTHOR_STATUSES
# what a book can be set to for a format
BOOK_STATUSES = ('Wanted', 'Skipped', 'Ignored', 'Have')
LIBRARIES = {'ebook': 'eBook', 'audiobook': 'AudioBook'}


def _author(row: dict) -> dict:
    """ An author from their row, or from list_authors, which adds how they sort and their source """
    have, total = check_int(row['HaveBooks'], 0), check_int(row['UnignoredBooks'], 0)
    return {'id': row['AuthorID'], 'name': row['AuthorName'] or '',
            'sort_name': row.get('NameSort') or row['AuthorName'] or '',
            'status': row['Status'] or '', 'image': row['AuthorImg'] or '',
            'last_book': {'id': row['LastBookID'] or '', 'title': row['LastBook'] or '', 'date': row['LastDate'] or ''}
            if row.get('LastBook') else None,
            'added': row['DateAdded'] or '', 'have': have, 'total': total,
            'percent': min(have * 100 // total, 100) if total else 0,
            'source': row.get('BadgeSource') or row.get('PrimarySource') or '',
            'added_reason': row.get('AddedReason') or authors.added_reason(row.get('Reason'))}


def list_authors() -> list[dict]:
    """ Every author, ignored ones too, by name as the settings sort them """
    found = authors.list_authors(limit=None).items + authors.list_authors(ignored=True, limit=None).items
    return sorted((_author(row) for row in found), key=lambda a: a['sort_name'].lower())


def get_author(author_id) -> dict:
    """ An author, with what the old author page shows of them: about, dates, links to the sources,
    and how many of their books are in each state """
    details = authors.author_details(author_id)
    row = details['author']
    author = _author(row)
    links = [{'source': name, 'url': row.get(source['author_link'])}
             for name, source in lazylibrarian.INFOSOURCES.items()
             if source.get('author_link') and row.get(source['author_link'])]
    author.update(born=row.get('AuthorBorn') or '', died=row.get('AuthorDeath') or '', age=details['age'],
                  about=row.get('About') or '', aka=row.get('AKA') or '', links=links,
                  locked=bool(check_int(row.get('Manual'), 0)),
                  ebook_counts=details['ebook_status_counts'], audio_counts=details['audio_status_counts'])
    return author


def author_books(author_id) -> list[dict]:
    """ An author's books, the ones they wrote with others too, newest first, with their series and
    the format of the file the library has of each """
    authors.get_author(author_id)
    db = database.DBConnection()
    try:
        rows = db.select("SELECT BookID, AuthorID, BookName, BookSub, BookDate, BookImg, BookRate, BookLang, "
                         "BookGenre, BookPages, Status, AudioStatus, BookFile, AudioFile, BookAdded, ScanResult "
                         "FROM books WHERE AuthorID=? OR BookID IN (SELECT BookID FROM bookauthors WHERE "
                         "AuthorID=?)", (author_id, author_id))
        series: dict[str, list[dict]] = {}
        for member in db.select("SELECT member.BookID, series.SeriesID, SeriesName, SeriesNum FROM member "
                                "JOIN series ON member.SeriesID=series.SeriesID WHERE member.BookID IN "
                                "(SELECT BookID FROM books WHERE AuthorID=? UNION SELECT BookID FROM bookauthors "
                                "WHERE AuthorID=?)", (author_id, author_id)):
            series.setdefault(member['BookID'], []).append(
                {'id': str(member['SeriesID']), 'name': member['SeriesName'] or '', 'number': member['SeriesNum'] or ''})
    finally:
        db.close()

    found = [{'id': row['BookID'], 'title': row['BookName'] or '', 'subtitle': row['BookSub'] or '',
              'release_date': row['BookDate'] or '', 'image': row['BookImg'] or '',
              'rating': check_float(row['BookRate'], 0), 'language': row['BookLang'] or '',
              'genres': row['BookGenre'] or '', 'pages': check_int(row['BookPages'], 0),
              'status': row['Status'] or '', 'audio_status': row['AudioStatus'] or '',
              'ebook_format': _file_format(row['BookFile'], 'ebook'),
              'audio_format': _file_format(row['AudioFile'], 'audiobook'),
              'added': row['BookAdded'] or '', 'scan_result': row['ScanResult'] or '',
              'is_primary': row['AuthorID'] == author_id, 'series': series.get(row['BookID'], [])}
             for row in rows]
    return sorted(found, key=lambda b: (b['release_date'] or '0000', b['title'].lower()), reverse=True)


AUTHOR_LOOKUP_PAGES = 5


def _title_key(title: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', fold(title or '')).split())


def author_lookup(author_id) -> list[dict]:
    """ The author's books the info sources find, as Readarr's author page lists them: the books
    looked up by their name that are theirs, by id or by name, each saying whether the library has
    it (by id, or a book of theirs with the same title from another source), the ones it hasn't
    first. Any of them can be added with the AddBook command """
    from lazylibrarian.services import addnew  # noqa: PLC0415, it imports this
    name = authors.get_author(author_id)['AuthorName']
    have = {_title_key(book['title']): book for book in author_books(author_id)}
    found, seen = [], set()
    # a name finds hundreds of pages at OpenLibrary, the first few have their best known books
    for book in addnew.lookup(name, max_pages=AUTHOR_LOOKUP_PAGES)['books']:
        if book['author_id'] != author_id and _title_key(book['author_name']) != _title_key(name):
            continue
        key = _title_key(book['title'])
        if not key or key in seen:
            continue
        seen.add(key)
        if not book['in_library'] and key in have:
            # the library's own copy, from another source, so it isn't added twice
            mine = have[key]
            book = {**book, 'id': mine['id'], 'in_library': True, 'status': mine['status'],
                    'audio_status': mine['audio_status']}
        found.append(book)
    # newest first, those without a date last
    return sorted(found, key=lambda book: (book['in_library'], -check_int((book['release_date'] or '')[:4], 0)))


def wanted_books(author_id) -> list[dict]:
    """ An author's wanted books, as the search takes them: {'book_id', 'media_type'} """
    return [{'book_id': book['id'], 'media_type': kind} for book in author_books(author_id)
            for kind, column in (('ebook', 'status'), ('audiobook', 'audio_status')) if book[column] == 'Wanted']


def set_author_status(author_ids: list, status: str) -> int:
    """ Set authors Active, Wanted, Paused or Ignored. Returns how many were """
    if status not in AUTHOR_STATUSES:
        raise InvalidRequestError(f"The status is one of {', '.join(AUTHOR_STATUSES)}")
    passed, _failed = authors.mark_authors(status, author_ids)
    return passed


def delete_authors(author_ids: list, delete_files: bool = False) -> int:
    """ Take authors out of the library, with the folders of their books if delete_files """
    passed, _failed = authors.mark_authors('Delete' if delete_files else 'Remove', author_ids)
    return passed


# why an author was added only for contributing to a book, before nobody was
CONTRIBUTOR_REASON = 'Contributor to '


def _contributors(db) -> tuple[list[dict], list[dict]]:
    """ The authors added only for contributing to a book: the ones that are another author in the
    library with the name written differently (J.A. and J. A., or the dotted Brandon. Sanderson made to
    keep them apart), each with the author to merge into, and the rest """
    rows = [dict(row) for row in db.select('SELECT AuthorID,AuthorName,Reason,Status FROM authors')]
    by_key: dict[str, list[dict]] = {}
    for row in rows:
        by_key.setdefault(author_name_key(row['AuthorName']), []).append(row)
    merges, merged = [], set()
    for same in by_key.values():
        if len(same) < 2:
            continue
        # into one added on purpose, else the one with the most books
        counts = {row['AuthorID']: db.match('SELECT COUNT(*) AS n FROM bookauthors WHERE AuthorID=?',
                                            (row['AuthorID'],))['n'] for row in same}
        keeper = sorted(same, key=lambda row: ((row['Reason'] or '').startswith(CONTRIBUTOR_REASON),
                                               -counts[row['AuthorID']], row['AuthorName']))[0]
        for row in same:
            if row is not keeper and (row['Reason'] or '').startswith(CONTRIBUTOR_REASON):
                merges.append({'id': row['AuthorID'], 'name': row['AuthorName'], 'into_id': keeper['AuthorID'],
                               'into_name': keeper['AuthorName']})
                merged.add(row['AuthorID'])
    rest = [row for row in rows if (row['Reason'] or '').startswith(CONTRIBUTOR_REASON) and row['AuthorID'] not in merged]
    return merges, rest


def _removable(db, row: dict, also=()) -> bool:
    """ A contributor still as they were added, Paused or Ignored, the main author of no book, with
    none of their books in the library. also are the authors that are being merged into them """
    if row['Status'] not in ('Paused', 'Ignored'):
        return False
    for author_id in (row['AuthorID'], *also):
        if db.match('SELECT BookID FROM books WHERE AuthorID=?', (author_id,)) or \
                db.match("SELECT books.BookID FROM books JOIN bookauthors ON books.BookID=bookauthors.BookID "
                         "WHERE bookauthors.AuthorID=? AND (books.Status IN ('Open','Have') OR "
                         "books.AudioStatus IN ('Open','Have'))", (author_id,)):
            return False
    return True


def contributor_authors() -> dict:
    """ What removing the contributor authors would do: the authors added only for contributing to a
    book that would be merged into another author in the library, and the ones that would be
    removed. Their books stay, under their main authors """
    db = database.DBConnection()
    try:
        merges, rest = _contributors(db)
        # one merged into is one author with the other's books
        into = {}
        for merge in merges:
            into.setdefault(merge['into_id'], []).append(merge['id'])
        remove = [{'id': row['AuthorID'], 'name': row['AuthorName'], 'reason': row['Reason'] or ''}
                  for row in rest if _removable(db, row, into.get(row['AuthorID'], []))]
    finally:
        db.close()
    return {'merge': merges, 'remove': sorted(remove, key=lambda row: row['name'].lower())}


def remove_contributor_authors() -> dict:
    """ Merge the contributor authors that are another author in the library, then remove the ones
    that are only contributors with none of their books in the library. Returns how many of each """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    merged = removed = 0
    try:
        merges, _ = _contributors(db)
        for merge in merges:
            old, new = merge['id'], merge['into_id']
            # their books, series and links to books go to the author they are, then they go
            db.action('UPDATE books SET AuthorID=? WHERE AuthorID=?', (new, old))
            db.action('INSERT OR IGNORE INTO bookauthors (BookID,AuthorID,Role) SELECT BookID,?,Role FROM bookauthors '
                      'WHERE AuthorID=? AND BookID NOT IN (SELECT BookID FROM bookauthors WHERE AuthorID=?)',
                      (new, old, new))
            db.action('INSERT OR IGNORE INTO seriesauthors (SeriesID,AuthorID) SELECT SeriesID,? FROM seriesauthors '
                      'WHERE AuthorID=?', (new, old))
            db.action('DELETE FROM bookauthors WHERE AuthorID=?', (old,))
            db.action('DELETE FROM seriesauthors WHERE AuthorID=?', (old,))
            keeper = db.match('SELECT AKA FROM authors WHERE AuthorID=?', (new,))
            akas = [aka.strip() for aka in (keeper['AKA'] or '').split(',') if aka.strip()] if keeper else []
            if merge['name'] != merge['into_name'] and merge['name'] not in akas:
                db.action('UPDATE authors SET AKA=? WHERE AuthorID=?', (', '.join([*akas, merge['name']]), new))
            db.action('DELETE FROM authors WHERE AuthorID=?', (old,))
            update_totals(new)
            logger.info(f"Merged contributor {merge['name']} ({old}) into {merge['into_name']} ({new})")
            merged += 1
        _, rest = _contributors(db)
        for row in rest:
            if _removable(db, row):
                db.action('DELETE FROM bookauthors WHERE AuthorID=?', (row['AuthorID'],))
                db.action('DELETE FROM seriesauthors WHERE AuthorID=?', (row['AuthorID'],))
                db.action('DELETE FROM authors WHERE AuthorID=?', (row['AuthorID'],))
                logger.info(f"Removed contributor {row['AuthorName']} ({row['AuthorID']}), {row['Reason']}")
                removed += 1
    finally:
        db.close()
    return {'merged': merged, 'removed': removed}


def set_book_status(book_ids: list, media_types: list[str], status: str) -> dict:
    """ Want books, or skip, ignore or mark them had, as eBooks, audiobooks or both. Wanting one the
    library has a file of leaves it as it is """
    if status not in BOOK_STATUSES:
        raise InvalidRequestError(f"The status is one of {', '.join(BOOK_STATUSES)}")
    if not media_types or any(kind not in LIBRARIES for kind in media_types):
        raise InvalidRequestError(f"The types are {', '.join(LIBRARIES)}")
    library = '+'.join(LIBRARIES[kind] for kind in media_types)
    result = books.mark_books(status, book_ids, library=library)
    return {'passed': result['passed'], 'failed': result['failed']}


def audio_parts(path: str) -> list[str]:
    """ An audiobook's parts, from its first: the audio files in its folder, part 2 before part 10 """
    folder = os.path.dirname(path)
    names = [name for name in os.listdir(folder) if CONFIG.is_valid_booktype(name, booktype='audiobook')]
    natural_sort(names, key=lambda name: name.lower())
    return [os.path.join(folder, name) for name in names]


def _file_format(path, media_type) -> str:
    return quality.name(quality.of_file(path, media_type)) if path else ''


# --- eBooks and audiobooks

# the list's sorts, by the columns list_books sorts on, the library's date by type
BOOK_SORTS = {'title': 'TitleSort', 'author': 'AuthorSort', 'released': 'BookDate', 'rating': 'BookRate',
              'added': {'ebook': 'BookLibrary', 'audiobook': 'AudioLibrary'}}
# a book is listed in its library once it's more than skipped or ignored
LISTED_STATUSES = ('Wanted', 'Snatched', 'Open', 'Have')
# what Manage lists besides a status: everything, or what's on one of the owner's reading lists
READING_LISTS = {'ToRead': 'To read', 'Read': 'Read', 'Reading': 'Reading', 'Abandoned': 'Abandoned'}
BOOK_FILTERS = LISTED_STATUSES + ('Skipped', 'Ignored', 'All') + tuple(READING_LISTS)
# the reading list a book is on, by the name books.reading_lists gives it
LIST_NAMES = {'ToRead': 'To read', 'HaveRead': 'Read', 'Reading': 'Reading', 'Abandoned': 'Abandoned'}
# what Manage can do to books: their status, a reading list, searching again now, or ignoring
# them with or without deleting their files
MARK_ACTIONS = ('Wanted', 'Have', 'Skipped', 'Ignored', 'NoDelay', 'Remove', 'Delete', 'Unread') + tuple(READING_LISTS)


def _series(text: str) -> list[dict]:
    """ The series list_books gives, seriesid~name #number joined with ^ """
    found = []
    for part in (text or '').split('^'):
        if '~' not in part:
            continue
        series_id, name = part.split('~', 1)
        name, _, number = name.rpartition(' #') if ' #' in name else (name, '', '')
        found.append({'id': series_id, 'name': name, 'number': number})
    return found


def _owner():
    from lazylibrarian.auth import owner_id  # noqa: PLC0415, auth imports the services
    return owner_id()


def list_books(media_type: str, status: str = '', search: str = '', sort: str = 'title', descending: bool = False,
               offset: int = 0, limit: int | None = None) -> Page:
    """ The eBooks or the audiobooks in the library, wanted, snatched or had, or those with a status,
    All of them, or those on one of the owner's reading lists, one row a book, by its primary author.
    Each says which reading list it's on and how its searches have gone """
    if media_type not in LIBRARIES:
        raise InvalidRequestError(f"The type is one of {', '.join(LIBRARIES)}")
    if status and status not in BOOK_FILTERS:
        raise InvalidRequestError(f"The status is one of {', '.join(BOOK_FILTERS)}")
    if sort not in BOOK_SORTS:
        raise InvalidRequestError(f"Sort by one of {', '.join(BOOK_SORTS)}")
    library = LIBRARIES[media_type]
    sort_column = BOOK_SORTS[sort][media_type] if sort == 'added' else BOOK_SORTS[sort]
    # sorted and searched by list_books, but a book written together is listed once for each author
    if status:
        found = books.list_books('Manage', library, status=status, search=search, sort=sort_column,
                                 descending=descending, primary_only=True, userid=_owner())
    else:
        found = books.list_books('Books' if media_type == 'ebook' else 'Audio', library, search=search,
                                 sort=sort_column, descending=descending, primary_only=True, userid=_owner())
    db = database.DBConnection()
    try:
        files = {row['BookID']: dict(row) for row in db.select(
            "SELECT BookID, AuthorID, BookFile, AudioFile FROM books")}
        searches = {row['BookID']: dict(row) for row in db.select(
            "SELECT BookID, Time, Interval, Count FROM failedsearch WHERE Library=?", (library,))}
    finally:
        db.close()
    rows = {}
    for row in found.items:
        book = files.get(row['BookID'], {})
        # its own author's row, the first otherwise
        if row['BookID'] not in rows or row['AuthorID'] == book.get('AuthorID'):
            rows[row['BookID']] = row
    unique = [row for row in found.items if rows.get(row['BookID']) is row]
    page = unique[offset:offset + limit if limit else None]
    column = 'Status' if media_type == 'ebook' else 'AudioStatus'
    records = []
    for row in page:
        path = files.get(row['BookID'], {})
        path = (path['BookFile'] if media_type == 'ebook' else path['AudioFile']) if path else ''
        records.append({'id': row['BookID'], 'title': row['BookName'] or '', 'subtitle': row['BookSub'] or '',
                        'author_id': row['AuthorID'] or '', 'author_name': row['AuthorName'] or '',
                        'series': _series(row['series']), 'release_date': row['BookDate'] or '',
                        'image': row['BookImg'] or '', 'rating': check_float(row['BookRate'], 0),
                        'language': row['BookLang'] or '', 'status': row[column] or '',
                        'format': _file_format(path, media_type),
                        'added': (row['BookLibrary'] if media_type == 'ebook' else row['AudioLibrary']) or '',
                        'reading_list': LIST_NAMES.get(row.get('ReadingList') or '', ''),
                        'search': _search_delay(searches.get(row['BookID']))})
    return Page(items=records, total=len(unique), matched=len(unique))


def _search_delay(row) -> dict | None:
    """ How a book's searches have gone: how many found nothing, when it was last looked for, and
    the hours until it's looked for again """
    if not row:
        return None
    return {'count': check_int(row['Count'], 0), 'last': row['Time'] or '', 'interval': check_int(row['Interval'], 0)}


def mark_books(book_ids: list, media_type: str, action: str) -> dict:
    """ Manage's actions on books, as an eBook or audiobook: want, have, skip or ignore them, search
    again now (NoDelay), ignore them (Remove) or delete their files and ignore them (Delete), or put
    them on a reading list of the owner's or take them off (Unread) """
    if media_type not in LIBRARIES:
        raise InvalidRequestError(f"The type is one of {', '.join(LIBRARIES)}")
    if action not in MARK_ACTIONS:
        raise InvalidRequestError(f"The action is one of {', '.join(MARK_ACTIONS)}")
    result = books.mark_books(action, book_ids, library=LIBRARIES[media_type], userid=_owner())
    return {'passed': result['passed'], 'failed': result['failed']}


def get_book(book_id: str) -> dict:
    """ A book as the Book page shows it: its details, links to the sources, its series, each
    format's status and file, and its downloads """

    details = books.book_details(book_id)
    row = details['book']
    names = {source['book_key']: name for name, source in lazylibrarian.INFOSOURCES.items()}
    links = [{'source': names.get(column, column), 'id': str(source_id), 'url': url}
             for column, source_id, url in details['links']]
    if details['amazon_link']:
        links.append({'source': 'Amazon', 'id': row.get('ASIN') or '', 'url': details['amazon_link']})
    db = database.DBConnection()
    try:
        in_series = [{'id': str(m['SeriesID']), 'name': m['SeriesName'] or '', 'number': m['SeriesNum'] or ''}
                     for m in db.select("SELECT series.SeriesID, SeriesName, SeriesNum FROM member JOIN series "
                                        "ON member.SeriesID=series.SeriesID WHERE BookID=?", (book_id,))]
        downloads = [{'id': d['rowid'], 'title': d['NZBtitle'] or '', 'indexer': d['NZBprov'] or '',
                      'date': d['NZBdate'] or '', 'status': d['Status'] or '', 'source': d['Source'] or '',
                      'media_type': 'audiobook' if d['AuxInfo'] == 'AudioBook' else 'ebook',
                      'message': d['DLResult'] or ''}
                     for d in db.select("SELECT rowid, NZBtitle, NZBprov, NZBdate, Status, Source, AuxInfo, DLResult "
                                        "FROM wanted WHERE BookID=? ORDER BY NZBdate DESC", (book_id,))]
    finally:
        db.close()

    def file(path, media_type) -> dict | None:
        if not path:
            return None
        size = 0
        parts = []
        exists = os.path.exists(path)
        if exists:
            try:
                if media_type == 'audiobook':
                    # an audiobook's file is its first part, its parts are the audio files in its folder
                    parts = audio_parts(path)
                size = sum(os.path.getsize(part) for part in parts or [path])
            except OSError:
                size = 0
        return {'path': path, 'format': _file_format(path, media_type), 'size': size, 'exists': exists,
                'parts': parts}

    return {'id': row['BookID'], 'title': row['BookName'] or '', 'subtitle': row['BookSub'] or '',
            'author_id': row['AuthorID'] or '', 'author_name': row['AuthorName'] or '',
            'series': in_series, 'release_date': row['BookDate'] or '',
            'original_date': row.get('OriginalPubDate') or '', 'publisher': row['BookPub'] or '',
            'isbn': row['BookIsbn'] or '', 'pages': check_int(row['BookPages'], 0), 'language': row['BookLang'] or '',
            'genres': row['BookGenre'] or '', 'rating': check_float(row['BookRate'], 0), 'image': row['BookImg'] or '',
            'description': row['BookDesc'] or '', 'narrator': row.get('Narrator') or '',
            'locked': bool(check_int(row.get('Manual'), 0)), 'added': row['BookAdded'] or '', 'links': links,
            'status': row['Status'] or '', 'audio_status': row['AudioStatus'] or '',
            'ebook_format': _file_format(row['BookFile'], 'ebook'),
            'audio_format': _file_format(row['AudioFile'], 'audiobook'),
            'scan_result': row['ScanResult'] or '',
            'ebook_file': file(row['BookFile'], 'ebook'), 'audio_file': file(row['AudioFile'], 'audiobook'),
            'downloads': downloads}


# --- magazines

# a past issue's status, and what one can be changed to
PAST_ISSUE_STATUSES = ('Skipped', 'Have', 'Ignored', 'Wanted', 'Snatched')
PAST_ISSUE_ACTIONS = ('Skipped', 'Wanted', 'Ignored', 'Remove')


def _magazine(row: dict) -> dict:
    return {'title': row['Title'], 'status': row['Status'] or '', 'issues': check_int(row.get('Iss_Cnt'), 0),
            'latest_issue': row['IssueDate'] or '', 'last_acquired': row['LastAcquired'] or '',
            # the latest issue's cover, its logo from Wikidata until it has one
            'cover': row['LatestCover'] or row.get('Logo') or '', 'added': row['MagazineAdded'] or '',
            'reject_words': row['Reject'] or '', 'language': row.get('Language') or '', 'genre': row.get('Genre') or '',
            'publisher': row.get('Publisher') or '', 'frequency': check_int(row.get('Frequency'), 0)}


UNREAD = {'issue': "SELECT Title AS ID, COUNT(*) AS Unread FROM issues WHERE IssueID NOT IN (SELECT ItemID FROM "
                   "readprogress WHERE Kind='issue' AND Finished=1) GROUP BY Title",
          'comic': "SELECT ComicID AS ID, COUNT(*) AS Unread FROM comicissues WHERE ComicID || '_' || IssueID NOT IN "
                   "(SELECT ItemID FROM readprogress WHERE Kind='comic' AND Finished=1) GROUP BY ComicID"}


def _unread(kind: str) -> dict:
    """ How many issues of each magazine (by title) or comic (by id) the owner hasn't finished """
    db = database.DBConnection()
    try:
        return {row['ID']: row['Unread'] for row in db.select(UNREAD[kind])}
    finally:
        db.close()


def _read_states(kind: str) -> dict:
    """ Each item of a kind the owner has opened: True finished, False started """
    db = database.DBConnection()
    try:
        return {row['ItemID']: bool(row['Finished']) for row in
                db.select('SELECT ItemID, Finished FROM readprogress WHERE Kind=?', (kind,))}
    finally:
        db.close()


def list_magazines() -> list[dict]:
    unread = _unread('issue')
    return [{**_magazine(row), 'unread': unread.get(row['Title'], 0)}
            for row in magazines.list_magazines(limit=None).items]


def get_magazine(title: str) -> dict:
    """ A magazine with its details from Wikidata, its issues newest first, and the issues it's
    missing and when the next is due """
    magazine = magazines.get_magazine(title)
    issues = magazines.list_issues(magazine['Title'], limit=None).items
    found = _magazine({**magazine, 'Iss_Cnt': len(issues)})
    found.update({'description': magazine.get('Description') or '', 'issn': magazine.get('ISSN') or '',
                  'country': magazine.get('Country') or '', 'website': magazine.get('Website') or '',
                  'logo': magazine.get('Logo') or '', 'started': magazine.get('Started') or '',
                  'wikidata_id': magazine.get('WikidataID') or '', 'cover_page': check_int(magazine['CoverPage'], 1),
                  'schedule': magazines.issue_schedule([issue['IssueDate'] for issue in issues],
                                                       check_int(magazine.get('Frequency'), 0)),
                  'keep_issues': check_int(magazine.get('KeepIssues'), 0),
                  'keep_months': check_int(magazine.get('KeepMonths'), 0)})
    states = _read_states('issue')
    found['issue_list'] = [{'id': issue['IssueID'], 'date': issue['IssueDate'] or '',
                            'acquired': issue['IssueAcquired'] or '', 'cover': issue['Cover'] or '',
                            'format': _file_format(issue['IssueFile'], 'magazine'),
                            'description': issue.get('Description') or '', 'pages': check_int(issue.get('Pages'), 0),
                            'number': issue.get('IssueNumber') or '', 'read': states.get(issue['IssueID'], False),
                            'started': issue['IssueID'] in states} for issue in issues]
    found['unread'] = sum(not issue['read'] for issue in found['issue_list'])
    return found


def set_magazine_status(titles: list[str], status: str) -> int:
    if status not in ('Active', 'Paused'):
        raise InvalidRequestError('The status is Active or Paused')
    passed, _failed = magazines.mark_magazines(status, titles)
    return passed


def delete_magazines(titles: list[str], delete_files: bool = False) -> int:
    """ Forget magazines, deleting their issues' files too if delete_files """
    passed, _failed = magazines.mark_magazines('Delete' if delete_files else 'Remove', titles)
    return passed


def delete_issues(issue_ids: list[str], delete_files: bool = False) -> int:
    passed, _failed, _title = magazines.mark_issues('Delete' if delete_files else 'Remove', issue_ids)
    return passed


def recent_issues(media_type: str = 'magazine', limit: int = 0) -> list[dict]:
    """ The magazine or comic issues acquired most recently, as the old Recent Issues wall shows
    them: MAX_WALL of them unless limit is given """
    limit = limit or CONFIG.get_int('MAX_WALL') or 100
    db = database.DBConnection()
    try:
        if media_type == 'comic':
            rows = db.select("SELECT comics.ComicID, Title, IssueID, IssueAcquired, IssueFile, Cover FROM comicissues "
                             "JOIN comics ON comics.ComicID=comicissues.ComicID ORDER BY IssueAcquired DESC LIMIT ?",
                             (limit,))
            return [{'id': f"{row['ComicID']}_{row['IssueID']}", 'title': row['Title'] or '',
                     'issue': str(row['IssueID']), 'parent_id': row['ComicID'], 'acquired': row['IssueAcquired'] or '',
                     'cover': row['Cover'] or '', 'format': _file_format(row['IssueFile'], 'comic')} for row in rows]
        rows = db.select("SELECT Title, IssueID, IssueDate, IssueAcquired, IssueFile, Cover FROM issues "
                         "ORDER BY IssueAcquired DESC LIMIT ?", (limit,))
    finally:
        db.close()
    return [{'id': row['IssueID'], 'title': row['Title'] or '', 'issue': row['IssueDate'] or '',
             'parent_id': row['Title'] or '', 'acquired': row['IssueAcquired'] or '', 'cover': row['Cover'] or '',
             'format': _file_format(row['IssueFile'], 'magazine')} for row in rows]


def search_issues(words: str, limit: int = 100) -> list[dict]:
    """ The pages of issues with these words, best first """
    if not words.strip():
        raise InvalidRequestError('Type the words to look for')
    return magazines.search_issues(words, limit)


def list_past_issues(status: str = 'Skipped', title: str = '') -> list[dict]:
    """ The past issues, search results for a magazine's issues that weren't wanted when they were
    found, with a status, and of one magazine when title is given """
    if status not in PAST_ISSUE_STATUSES:
        raise InvalidRequestError(f"The status is one of {', '.join(PAST_ISSUE_STATUSES)}")
    return [{'url': row['NZBurl'] or '', 'release_title': (row['NZBtitle'] or '').replace('.', ' '),
             'date': row['NZBdate'] or '', 'issue': row['AuxInfo'] or '', 'indexer': row['NZBprov'] or '',
             'title': row['BookID'] or ''}
            for row in magazines.list_past_issues(status, title or None, sort='NZBdate', descending=True).items]


def mark_past_issues(urls: list[str], action: str) -> int:
    """ Want past issues (they're downloaded), skip or ignore them, or forget them (Remove) """
    if action not in PAST_ISSUE_ACTIONS:
        raise InvalidRequestError(f"The action is one of {', '.join(PAST_ISSUE_ACTIONS)}")
    return magazines.mark_past_issues(action, urls)


def set_issue_cover(media_type: str, item_id: str, page: int) -> str:
    """ Make a magazine issue's (by its id) or comic issue's (comicid_issueid) cover from a page """
    if media_type == 'comic':
        comic_id, _, issue_id = item_id.partition('_')
        return comics.set_issue_cover(comic_id, issue_id, page)
    return magazines.set_issue_cover(item_id, page)


# --- comics


def _comic(row: dict) -> dict:
    return {'id': row['ComicID'], 'title': row['Title'] or '', 'status': row['Status'] or '',
            'issues': check_int(row.get('Iss_Cnt'), 0), 'latest_issue': str(row['LatestIssue'] or ''),
            'last_acquired': row['LastAcquired'] or '', 'cover': row['LatestCover'] or '',
            'added': row['Added'] or '', 'publisher': row['Publisher'] or '', 'start': str(row['Start'] or ''),
            'first': check_int(row['First'], 0), 'last': check_int(row['Last'], 0),
            'overview': row.get('Description') or '', 'link': row['Link'] or ''}


def list_comics() -> list[dict]:
    unread = _unread('comic')
    return [{**_comic(row), 'unread': unread.get(row['ComicID'], 0)} for row in comics.list_comics(limit=None).items]


def get_comic(comic_id: str) -> dict:
    """ A comic with its issues, newest first, each saying whether the owner has read it """
    comic = comics.get_comic(comic_id)
    issues = comics.list_issues(comic_id, limit=None).items
    found = _comic({**comic, 'Iss_Cnt': len(issues)})
    states = _read_states('comic')
    found['issue_list'] = [{'id': str(issue['IssueID']), 'acquired': issue['IssueAcquired'] or '',
                            'cover': issue['Cover'] or '', 'overview': issue.get('Description') or '',
                            'format': _file_format(issue['IssueFile'], 'comic'),
                            'pages': check_int(issue.get('Pages'), 0),
                            'read': states.get(f"{comic['ComicID']}_{issue['IssueID']}", False),
                            'started': f"{comic['ComicID']}_{issue['IssueID']}" in states} for issue in issues]
    found['unread'] = sum(not issue['read'] for issue in found['issue_list'])
    return found


def set_comic_status(comic_ids: list[str], status: str) -> int:
    if status not in ('Active', 'Paused'):
        raise InvalidRequestError('The status is Active or Paused')
    return comics.mark_comics(status, comic_ids)


def delete_comics(comic_ids: list[str], delete_files: bool = False) -> int:
    return comics.mark_comics('Delete' if delete_files else 'Remove', comic_ids)


def delete_comic_issues(comic_id: str, issue_ids: list[str], delete_files: bool = False) -> int:
    comics.mark_issues('Delete' if delete_files else 'Remove', [f"{comic_id}_{issue}" for issue in issue_ids])
    return len(issue_ids)


# --- series

SERIES_STATUSES = series.SERIES_STATUSES


def _one_series(row: dict) -> dict:
    have, total = check_int(row['Have'], 0), check_int(row['Total'], 0)
    return {'id': str(row['SeriesID']), 'name': row['SeriesName'] or '', 'status': row['Status'] or '',
            'author_id': row['AuthorID'] or '', 'author_name': row['AuthorName'] or '', 'have': have,
            'total': total, 'percent': min(have * 100 // total, 100) if total else 0,
            'source': str(row['SeriesID'])[:2]}


def list_series(status: str = 'All') -> list[dict]:
    """ The series, by author and name; status one of theirs, or All """
    return [_one_series(row) for row in series.list_series(status=status, limit=None).items]


def get_series(series_id: str) -> dict:
    """ A series with its books, in order, the ignored ones too """
    found = series.series_page(series_id)
    members = found['members'] + series.series_page(series_id, ignored=True)['members']
    db = database.DBConnection()
    try:
        row = db.match('SELECT Status, Have, Total FROM series WHERE SeriesID=?', (series_id,))
        ids = [member['BookID'] for member in members]
        files = {r['BookID']: dict(r) for r in db.select(
            f"SELECT BookID, BookFile, AudioFile, BookDate FROM books WHERE BookID IN ({','.join('?' * len(ids))})",
            tuple(ids))} if ids else {}
    finally:
        db.close()
    if not row:
        raise NotFoundError(f'Series {series_id} not found')
    result = _one_series({**found['series'], **dict(row)})

    def number(member) -> float:
        return check_float(member['SeriesNum'], 9999)

    result['books'] = [{'id': m['BookID'], 'title': m['BookName'] or '', 'subtitle': m['BookSub'] or '',
                        'number': m['SeriesNum'] or '', 'author_id': m['AuthorID'] or '',
                        'author_name': m['AuthorName'] or '', 'image': m['BookImg'] or '',
                        'release_date': (files.get(m['BookID']) or {}).get('BookDate') or '',
                        'status': m['Status'] or '', 'audio_status': m['AudioStatus'] or '',
                        'ebook_format': _file_format((files.get(m['BookID']) or {}).get('BookFile'), 'ebook'),
                        'audio_format': _file_format((files.get(m['BookID']) or {}).get('AudioFile'), 'audiobook')}
                       for m in sorted(members, key=number)]
    return result


def set_series_status(series_ids: list[str], status: str) -> int:
    """ Wanted and Active look for the series' books and keep watching it, the others stop """
    if status not in SERIES_STATUSES:
        raise InvalidRequestError(f"The status is one of {', '.join(SERIES_STATUSES)}")
    passed, _failed = series.mark_series(status, series_ids)
    return passed
