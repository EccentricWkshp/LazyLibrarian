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

""" Add New, like Readarr's: look an author or book up at the info sources, a magazine by its
title, a comic at ComicVine and Comixology, and add what's chosen, with whether to want the
author's books and to search for them. Adding an author fetches all their books, which takes a
while, so it runs as a command, as do refreshing an author's or a book's details """

import logging

import lazylibrarian
from lazylibrarian import database, wikidata
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_float, check_int, plural
from lazylibrarian.importer import add_author_to_db, update_totals
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    authors,
    books,
    comics,
    magazines,
    wanted,
)

# what to want of a new author's books: what the settings say for the books they have now and the
# ones to come, all of them, or none, the author paused
MONITOR = ('new', 'all', 'none')
LIBRARIES = {'ebook': 'eBook', 'audiobook': 'AudioBook'}
STATUS_COLUMNS = {'ebook': 'Status', 'audiobook': 'AudioStatus'}
TABS = {'ebook': 'EBOOK_TAB', 'audiobook': 'AUDIO_TAB'}


def media_types() -> list[str]:
    """ The book types whose libraries are switched on """
    return [kind for kind, tab in TABS.items() if CONFIG.get_bool(tab)]


def _media_types(asked) -> list[str]:
    asked = list(asked or media_types())
    if any(kind not in LIBRARIES for kind in asked):
        raise InvalidRequestError(f"The types are {', '.join(LIBRARIES)}")
    return asked


# --- authors and books


def _text(result: dict, key: str) -> str:
    """ The sources don't all give text, OpenLibrary's publisher is the year it was first published """
    value = result.get(key)
    return '' if value is None else str(value)


def lookup(term: str, max_pages: int = 0) -> dict:
    """ Authors and books matching a name, title or ISBN, best match first, each saying whether
    it's in the library already. max_pages limits the pages of a paged source's results """
    term = (term or '').strip()
    if not term:
        raise InvalidRequestError('Type an author, a title or an ISBN to look for')
    found = authors.search_sources(term, max_pages)
    have = set(found['authorlist'])
    loading = set(found['loadlist'])
    statuses = {row['BookID']: row for row in found['booksearch']}
    found_authors: dict[str, dict] = {}
    found_books = []
    for result in found['results']:
        author_id = _text(result, 'authorid')
        name = _text(result, 'authorname')
        publisher, released = _text(result, 'bookpub'), _text(result, 'bookdate')
        if publisher.isdigit():
            publisher, released = '', released or publisher
        if author_id and author_id not in found_authors:
            found_authors[author_id] = {'id': author_id, 'name': name, 'source': _text(result, 'source'),
                                        'in_library': author_id in have, 'loading': author_id in loading,
                                        'books': 0, 'score': check_float(result.get('author_fuzz'), 0)}
        if author_id:
            found_authors[author_id]['books'] += 1
        book_id = _text(result, 'bookid')
        row = statuses.get(book_id)
        found_books.append({
            'id': book_id, 'title': _text(result, 'bookname'), 'subtitle': _text(result, 'booksub'),
            'author_id': author_id, 'author_name': name, 'author_in_library': author_id in have,
            'isbn': _text(result, 'bookisbn'), 'publisher': publisher, 'release_date': released,
            'language': _text(result, 'booklang'),
            'pages': check_int(result.get('bookpages'), 0), 'genres': _text(result, 'bookgenre'),
            'overview': _text(result, 'bookdesc'), 'cover': _text(result, 'bookimg'),
            'link': _text(result, 'booklink'), 'rating': check_float(result.get('bookrate'), 0),
            'ratings': check_int(result.get('bookrate_count'), 0), 'source': _text(result, 'source'),
            'score': check_float(result.get('highest_fuzz'), 0), 'in_library': row is not None,
            # a book in the library can have no status for a format yet
            'status': row['Status'] or '' if row else '', 'audio_status': row['AudioStatus'] or '' if row else ''})
    return {'authors': sorted(found_authors.values(), key=lambda a: (-a['score'], -a['books'])),
            'books': found_books}


def _author_books(db, author_id) -> int:
    row = db.match('SELECT COUNT(*) AS counter FROM books WHERE AuthorID=?', (author_id,))
    return row['counter'] if row else 0


def _wanted_books(db, author_id, kinds: list[str]) -> list[dict]:
    found = []
    for kind in kinds:
        column = STATUS_COLUMNS[kind]
        found += [{'book_id': row['BookID'], 'media_type': kind} for row in
                  db.select(f"SELECT BookID FROM books WHERE AuthorID=? AND {column}='Wanted'", (author_id,))]
    return found


def _search(found: list[dict], progress=None) -> str:
    """ Search for what was added, what to say about it """
    if not found:
        return ''
    try:
        _count, message = wanted.search_books(found, progress=progress)
    except InvalidRequestError as why:
        return f". Not searched: {why}"
    return f". {message}"


def add_author(author_id: str, name: str = '', monitor: str = 'new', kinds=None, search: bool = False,
               progress=None) -> tuple[str, dict]:
    """ Add an author and all their books from the info source the id is from. monitor: new
    wants their books as the settings say, all wants every one of them, none pauses the author.
    Returns what happened, and the author's id and name in the library """
    if not author_id:
        raise InvalidRequestError('Which author?')
    if monitor not in MONITOR:
        raise InvalidRequestError(f"Monitor is one of {', '.join(MONITOR)}")
    kinds = _media_types(kinds)
    db = database.DBConnection()
    try:
        there = db.match('SELECT AuthorName, Status FROM authors WHERE AuthorID=?', (author_id,))
        if there and there['Status'] != 'Loading':
            raise InvalidRequestError(f"{there['AuthorName']} is in the library already")
    finally:
        db.close()
    if progress:
        progress(f"Adding {name or author_id}, fetching their books")
    added = add_author_to_db(name or None, False, author_id, True, f'Add New {author_id}')
    db = database.DBConnection()
    try:
        row = db.match('SELECT AuthorID, AuthorName FROM authors WHERE AuthorID=?', (added or author_id,))
        if not row:
            raise InvalidRequestError(f"Couldn't add {name or author_id}, see the log")
        author_id, name = row['AuthorID'], row['AuthorName']
        if monitor == 'all':
            for kind in kinds:
                column = STATUS_COLUMNS[kind]
                db.action(f"UPDATE books SET {column}='Wanted' WHERE AuthorID=? AND {column}='Skipped'",
                          (author_id,))
        elif monitor == 'none':
            db.action("UPDATE authors SET Status='Paused' WHERE AuthorID=?", (author_id,))
        update_totals(author_id)
        count = _author_books(db, author_id)
        found = _wanted_books(db, author_id, kinds) if search else []
    finally:
        db.close()
    logging.getLogger(__name__).info(f"Added the author {name}, {count} {plural(count, 'book')}")
    message = f"Added {name}, {count} {plural(count, 'book')}" + _search(found, progress)
    return message, {'author_id': author_id, 'author_name': name}


def add_book(book_id: str, source: str = '', author_id: str = '', kinds=None, search: bool = False,
             progress=None, title: str = '') -> tuple[str, dict]:
    """ Add a book from an info source and want it, as an eBook, audiobook or both, a format the
    library has staying as it is. Its author is added too, without their other books. title is
    what progress calls it until it is added """
    if not book_id:
        raise InvalidRequestError('Which book?')
    kinds = _media_types(kinds)
    if source and source not in _sources():
        raise InvalidRequestError(f"The source is one of {', '.join(_sources())}")
    library = 'Both' if len(kinds) == 2 else LIBRARIES[kinds[0]]
    if progress:
        progress(f"Adding {title or book_id}")
    found_author, _ebook, _audio = books.add_book(book_id, author_id or None, library, source or None,
                                                  search=False, wait=None)
    db = database.DBConnection()
    try:
        row = db.match('SELECT BookName, AuthorID, Status, AudioStatus FROM books WHERE BookID=?', (book_id,))
    finally:
        db.close()
    if not row:
        raise InvalidRequestError(f"Couldn't add the book {book_id}, see the log")
    wanted_now = [{'book_id': book_id, 'media_type': kind} for kind in kinds
                  if row[STATUS_COLUMNS[kind]] == 'Wanted']
    message = f"Added {row['BookName']}" + (_search(wanted_now, progress) if search else '')
    return message, {'book_id': book_id, 'author_id': row['AuthorID'] or found_author, 'title': row['BookName']}


def _sources() -> list[str]:
    return list(lazylibrarian.INFOSOURCES)


def refresh_author(author_id: str, progress=None) -> str:
    """ Fetch an author's details and books again, now """
    author = authors.get_author(author_id)
    name = author['AuthorName']
    if progress:
        progress(f"Refreshing {name}")
    lookup_name = None if not name or 'unknown' in name.lower() or 'anonymous' in name.lower() else name
    add_author_to_db(lookup_name, True, author_id, True, f'Refresh {author_id}')
    db = database.DBConnection()
    try:
        count = _author_books(db, author_id)
    finally:
        db.close()
    return f"Refreshed {name}, {count} {plural(count, 'book')}"


def refresh_book(book_id: str, progress=None) -> str:
    """ Fetch a book's details again, now, from the first source it's linked to, and what that
    hasn't got from the others """
    from lazylibrarian import completion  # noqa: PLC0415, it imports most of LazyLibrarian
    if progress:
        progress(f"Refreshing {_book_name(book_id)}")
    source = books.refresh_book(book_id, wait=True)
    filled = {}
    if CONFIG.get_bool('FILL_MISSING'):
        if progress:
            progress(f"Filling in what {_book_name(book_id)} is missing from the other sources")
        filled = completion.complete_book(book_id, force=True)
    if not source and not filled:
        raise InvalidRequestError("The book is locked against changes, or its id isn't from an info source")
    message = f"Refreshed {_book_name(book_id)}" + (f" from {source}" if source else '')
    if filled:
        message += f", {completion.described(filled)}"
    return message


def _book_name(book_id: str) -> str:
    db = database.DBConnection()
    try:
        row = db.match('SELECT BookName FROM books WHERE BookID=?', (book_id,))
    finally:
        db.close()
    return row['BookName'] if row and row['BookName'] else book_id


# --- magazines and comics


def lookup_magazine(term: str) -> list[dict]:
    """ The magazine a title would add, the ones in the library whose title has it in, and the
    periodicals Wikidata finds for it, each with its Wikidata id and description. A title can end
    with ~ and words that rule out a release """
    term = (term or '').strip()
    if not term:
        raise InvalidRequestError('Type a magazine title')
    title, reject = magazines.clean_title(term)
    db = database.DBConnection()
    try:
        rows = db.select("SELECT Title, WikidataID, Description, Started, (SELECT COUNT(*) FROM issues WHERE "
                         "issues.Title=magazines.Title) AS Issues FROM magazines WHERE Title LIKE ? ORDER BY Title",
                         (f'%{title}%',))
        linked = {row['WikidataID']: row['Title'] for row in db.select(
            "SELECT Title, WikidataID FROM magazines WHERE IFNULL(WikidataID, '') != ''")}
    finally:
        db.close()
    found = [{'title': row['Title'], 'reject_words': '', 'in_library': True, 'issues': row['Issues'],
              'wikidata_id': row['WikidataID'] or '', 'description': row['Description'] or '',
              'started': row['Started'] or ''} for row in rows]
    try:
        matches = wikidata.search(title, (CONFIG['PREF_MAGLANG'] or 'en')[:2])
    except Exception as why:
        logging.getLogger(__name__).warning(f"Wikidata couldn't be searched: {type(why).__name__} {why}")
        matches = []
    titles = {row['title'].casefold() for row in found}
    for match in matches:
        if match['id'] in linked or match['label'].casefold() in titles:
            continue
        found.append({'title': match['label'], 'reject_words': reject or '', 'in_library': False, 'issues': 0,
                      'wikidata_id': match['id'], 'description': match['description'], 'started': match['started']})
    if title.casefold() not in {row['title'].casefold() for row in found}:
        # the title as it was typed, without Wikidata's details
        found.insert(0, {'title': title, 'reject_words': reject or '', 'in_library': False, 'issues': 0,
                         'wikidata_id': '', 'description': '', 'started': ''})
    return found


def add_magazine(title: str, reject_words: str = '', search: bool = False, wikidata_id: str = '') -> dict:
    """ Add a magazine, and take its details from Wikidata in the background: from the item asked
    for, or the one called exactly its title """
    title = (title or '').strip()
    if not title:
        raise InvalidRequestError('A magazine needs a title')
    if any(c in title for c in '<>='):
        raise InvalidRequestError("A title can't have < > or = in it")
    stored, new = magazines.add_magazine(f"{title} ~ {reject_words}" if reject_words.strip() else title,
                                         search=search)
    if not new:
        raise InvalidRequestError(f"{stored} is in the library already")
    from lazylibrarian.services import commands  # noqa: PLC0415, its commands import this
    commands.start('RefreshMagazine', {'title': stored, 'wikidata_id': wikidata_id})
    return {'title': stored}


def lookup_comic(term: str) -> list[dict]:
    """ Comics matching a title at ComicVine and Comixology, best match first. A title starting
    CV looks for a ComicVine id """
    term = (term or '').strip()
    if not term:
        raise InvalidRequestError('Type a comic title')
    db = database.DBConnection()
    try:
        have = {row['ComicID'] for row in db.select('SELECT ComicID FROM comics')}
        same = db.match('SELECT ComicID FROM comics WHERE Title=?', (term,))
    finally:
        db.close()
    results = comics.find_comics(term)
    if results is None:  # the title is in the library
        results = []
        if same:
            have.add(same['ComicID'])
    return [{'id': item.get('seriesid', ''), 'title': item.get('title', ''), 'publisher': item.get('publisher') or '',
             'start': str(item.get('start') or ''), 'first': check_int(item.get('first'), 0),
             'last': check_int(item.get('last'), 0), 'issues': check_int(item.get('count'), 0),
             'overview': item.get('description') or '', 'link': item.get('link') or '',
             'score': check_int(item.get('fuzz'), 0), 'in_library': item.get('seriesid') in have}
            for item in results]


def add_comic(comic_id: str, search: bool = False) -> dict:
    """ Add a comic the last lookup found """
    if not comic_id:
        raise InvalidRequestError('Which comic?')
    if not comics.add_comic(comic_id, search=search):
        raise InvalidRequestError('The comic is in the library already')
    db = database.DBConnection()
    try:
        row = db.match('SELECT ComicID, Title FROM comics WHERE ComicID=?', (comic_id,))
    finally:
        db.close()
    if not row:
        raise NotFoundError(f'No comic {comic_id}')
    return {'id': row['ComicID'], 'title': row['Title']}
