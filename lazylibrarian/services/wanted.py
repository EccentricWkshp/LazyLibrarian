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

""" Wanted, Missing, like Sonarr's: the books and audiobooks that are wanted and not downloaded, to
search for automatically or interactively. The searches run as commands, so how they ended shows """

from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import plural, thread_name
from lazylibrarian.services import InvalidRequestError
from lazylibrarian.services.paging import Page, page_of

LIBRARIES = {'ebook': 'eBook', 'audiobook': 'AudioBook'}
SORTS = ('title', 'author', 'added', 'media_type')


def media_types() -> list[str]:
    """ The kinds of book that are shown, by the library tabs """
    kinds = []
    if CONFIG.get_bool('EBOOK_TAB'):
        kinds.append('ebook')
    if CONFIG.get_bool('AUDIO_TAB'):
        kinds.append('audiobook')
    return kinds


def list_missing(media_type: str = '', search: str = '', sort: str = 'added', descending: bool = True,
                 offset: int = 0, limit: int | None = None) -> Page:
    """ The wanted books and audiobooks, one record each, most recently added first """
    kinds = [media_type] if media_type else media_types()
    if any(kind not in LIBRARIES for kind in kinds):
        raise InvalidRequestError('The type is ebook or audiobook')
    if sort not in SORTS:
        raise InvalidRequestError(f"Sort by one of {', '.join(SORTS)}")
    db = database.DBConnection()
    try:
        rows = db.select("SELECT BookID,BookName,BookSub,AuthorName,books.AuthorID,BookAdded,BookDate,"
                         "books.Status,AudioStatus FROM books,authors WHERE books.AuthorID=authors.AuthorID "
                         "AND (books.Status='Wanted' OR AudioStatus='Wanted')")
    finally:
        db.close()
    records = []
    for row in rows:
        for kind in kinds:
            if row['AudioStatus' if kind == 'audiobook' else 'Status'] == 'Wanted':
                records.append({'id': f"{row['BookID']}:{kind}", 'book_id': row['BookID'],
                                'title': row['BookName'], 'subtitle': row['BookSub'] or '',
                                'author': row['AuthorName'], 'author_id': row['AuthorID'],
                                'media_type': kind, 'added': row['BookAdded'] or '',
                                'published': row['BookDate'] or ''})
    return page_of(records, search=search, search_fields=('title', 'author', 'subtitle'), sort=sort,
                   descending=descending, natural=sort == 'title', offset=offset, limit=limit)


def _title(book_id) -> str:
    db = database.DBConnection()
    try:
        book = db.match('SELECT BookName FROM books WHERE BookID=?', (book_id,))
    finally:
        db.close()
    return book['BookName'] if book else book_id


def search_books(books: list[dict], progress=None) -> tuple[int, str]:
    """ The automatic search for these books, [{'book_id', 'media_type'}], or every wanted one when
    there are none. Returns how many it found and sent to a download client, and a message """
    from lazylibrarian.searchbook import search_book  # it imports most of LazyLibrarian

    if not CONFIG.total_active_providers():
        raise InvalidRequestError('No search providers are enabled, add one in Settings, Providers')
    thread_name('FORCE-SEARCHBOOK')
    if not books:
        if progress:
            progress('Searching for every wanted book')
        found = search_book(None, None) or 0
        return found, f"Search for wanted books completed, {found} {plural(found, 'book')} found"
    found = 0
    for kind, library in LIBRARIES.items():
        ids = [{'bookid': book['book_id']} for book in books if book.get('media_type') == kind]
        if ids:
            if progress:
                progress(f"Searching for {len(ids)} {plural(len(ids), library)}")
            found += search_book(ids, library) or 0
            thread_name('FORCE-SEARCHBOOK')  # search_book names the thread back when it's done
    if len(books) == 1:
        name = _title(books[0]['book_id'])
        return found, f'Search for {name} completed, found and sent to the download client' if found else \
            f'Search for {name} completed, nothing found that the automatic search would take. ' \
            f'Try Interactive Search'
    return found, f"Search for {len(books)} books completed, {found} {plural(found, 'book')} found"
