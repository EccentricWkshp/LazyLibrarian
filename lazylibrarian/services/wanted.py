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

""" Wanted, Missing, like Sonarr's: what LazyLibrarian is looking for, to search for automatically
or interactively, or to stop looking for (unmonitor). Books and audiobooks are wanted one by one.
A magazine or comic that is active is looked for issue by issue, its next one, so it is one
record with its latest issue. The searches run as commands, so how they ended shows """

from lazylibrarian import database, quality
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import path_isfile
from lazylibrarian.formatter import plural, thread_name
from lazylibrarian.services import InvalidRequestError
from lazylibrarian.services.paging import Page, page_of

LIBRARIES = {'ebook': 'eBook', 'audiobook': 'AudioBook'}
MEDIA_TYPES = ('ebook', 'audiobook', 'magazine', 'comic')
SORTS = ('title', 'author', 'added', 'media_type', 'published')


def media_types() -> list[str]:
    """ The kinds that are shown, by the library tabs """
    kinds = []
    for kind, tab in (('ebook', 'EBOOK_TAB'), ('audiobook', 'AUDIO_TAB'), ('magazine', 'MAG_TAB'),
                      ('comic', 'COMIC_TAB')):
        if CONFIG.get_bool(tab):
            kinds.append(kind)
    return kinds


def _record(item_id, kind: str, title: str, **fields) -> dict:
    return {'id': f"{item_id}:{kind}", 'book_id': item_id, 'title': title, 'subtitle': '', 'author': '',
            'author_id': None, 'media_type': kind, 'added': '', 'published': '', **fields}


def list_missing(media_type: str = '', search: str = '', sort: str = 'added', descending: bool = True,
                 offset: int = 0, limit: int | None = None) -> Page:
    """ What is wanted: books and audiobooks one record each, and each active magazine and comic """
    kinds = [media_type] if media_type else media_types()
    if any(kind not in MEDIA_TYPES for kind in kinds):
        raise InvalidRequestError(f"The type is one of {', '.join(MEDIA_TYPES)}")
    if sort not in SORTS:
        raise InvalidRequestError(f"Sort by one of {', '.join(SORTS)}")
    records = []
    db = database.DBConnection()
    try:
        if any(kind in LIBRARIES for kind in kinds):
            for row in db.select("SELECT BookID,BookName,BookSub,AuthorName,books.AuthorID,BookAdded,BookDate,"
                                 "books.Status,AudioStatus FROM books,authors WHERE books.AuthorID=authors.AuthorID "
                                 "AND (books.Status='Wanted' OR AudioStatus='Wanted')"):
                for kind in kinds:
                    if kind in LIBRARIES and row['AudioStatus' if kind == 'audiobook' else 'Status'] == 'Wanted':
                        records.append(_record(row['BookID'], kind, row['BookName'], subtitle=row['BookSub'] or '',
                                               author=row['AuthorName'], author_id=row['AuthorID'],
                                               added=row['BookAdded'] or '', published=row['BookDate'] or ''))
        if 'magazine' in kinds:
            for row in db.select("SELECT Title,IssueDate,MagazineAdded FROM magazines WHERE Status='Active'"):
                records.append(_record(row['Title'], 'magazine', row['Title'],
                                       subtitle=f"Latest issue {row['IssueDate']}" if row['IssueDate']
                                       else 'No issues yet', added=row['MagazineAdded'] or '',
                                       published=row['IssueDate'] or ''))
        if 'comic' in kinds:
            for row in db.select("SELECT ComicID,Title,Publisher,LatestIssue,Added FROM comics WHERE Status='Active'"):
                records.append(_record(row['ComicID'], 'comic', row['Title'], author=row['Publisher'] or '',
                                       subtitle=f"Latest issue {row['LatestIssue']}" if row['LatestIssue']
                                       else 'No issues yet', added=row['Added'] or ''))
    finally:
        db.close()
    return page_of(records, search=search, search_fields=('title', 'author', 'subtitle'), sort=sort,
                   descending=descending, natural=sort == 'title', offset=offset, limit=limit)


CUTOFF_SORTS = ('title', 'author', 'added', 'media_type', 'quality')
# for each library: its status, file and import date columns
BOOK_COLUMNS = {'ebook': ('Status', 'BookFile', 'BookLibrary'), 'audiobook': ('AudioStatus', 'AudioFile',
                                                                             'AudioLibrary')}


def _cutoff_unmet(kinds: list[str]) -> list[dict]:
    """ The books whose file is below their quality profile's cutoff, when it allows upgrades """
    from lazylibrarian.services import profiles  # it reads the settings
    records = []
    db = database.DBConnection()
    try:
        for kind in kinds:
            profile = profiles.for_media(kind, db)
            if not profile or not profile['upgrade_allowed']:
                continue
            status, file_column, imported = BOOK_COLUMNS[kind]
            rows = db.select(f"SELECT BookID,BookName,AuthorName,books.AuthorID,{file_column} AS Path,{imported} AS "
                             f"Imported,BookDate FROM books,authors WHERE books.AuthorID=authors.AuthorID AND "
                             f"books.{status} IN ('Open','Have') AND IFNULL({file_column},'')!=''")
            for row in rows:
                # the file's own format first, the others beside it only when that isn't good enough
                if profiles.cutoff_met(profile, quality.of_file(row['Path'], kind)):
                    continue
                if not path_isfile(row['Path']):
                    continue
                current = profiles.book_quality(profile, quality.of_book(row['Path'], kind))
                if profiles.cutoff_met(profile, current):
                    continue
                records.append(_record(row['BookID'], kind, row['BookName'], author=row['AuthorName'],
                                       author_id=row['AuthorID'], added=row['Imported'] or '',
                                       published=row['BookDate'] or '', quality=quality.name(current),
                                       cutoff=quality.name(profile['cutoff']), profile=profile['name']))
    finally:
        db.close()
    return records


def list_cutoff_unmet(media_type: str = '', search: str = '', sort: str = 'title', descending: bool = False,
                      offset: int = 0, limit: int | None = None) -> Page:
    """ Sonarr's Wanted, Cutoff Unmet: the books and audiobooks to upgrade, each with the quality of
    its file and the cutoff it's to be upgraded until """
    kinds = [media_type] if media_type else [kind for kind in media_types() if kind in LIBRARIES]
    if any(kind not in LIBRARIES for kind in kinds):
        raise InvalidRequestError('The type is ebook or audiobook')
    if sort not in CUTOFF_SORTS:
        raise InvalidRequestError(f"Sort by one of {', '.join(CUTOFF_SORTS)}")
    return page_of(_cutoff_unmet(kinds), search=search, search_fields=('title', 'author'), sort=sort,
                   descending=descending, natural=sort == 'title', offset=offset, limit=limit)


def search_upgrades(books: list[dict], progress=None) -> tuple[int, str]:
    """ Search for better releases of these books, [{'book_id', 'media_type'}], or of every book in
    Cutoff Unmet when there are none. Only a release better than the file there is is taken """
    from lazylibrarian.searchbook import search_book  # it imports most of LazyLibrarian

    if not CONFIG.total_active_providers():
        raise InvalidRequestError('No search providers are enabled, add one in Settings, Providers')
    if any(book.get('media_type') not in LIBRARIES for book in books):
        raise InvalidRequestError('Upgrades are for books and audiobooks')
    wanted = books or [{'book_id': record['book_id'], 'media_type': record['media_type']}
                       for record in _cutoff_unmet([kind for kind in media_types() if kind in LIBRARIES])]
    if not wanted:
        return 0, 'Nothing is below its cutoff'
    last = _last_download()
    for kind, library in LIBRARIES.items():
        ids = [{'bookid': book['book_id']} for book in wanted if book['media_type'] == kind]
        if ids:
            if progress:
                progress(f"Searching for upgrades of {len(ids)} {plural(len(ids), library)}")
            thread_name('FORCE-SEARCHBOOK')
            search_book(ids, library, upgrade=True)
    found = _snatched_since(last)
    if len(wanted) == 1:
        name = _name(wanted[0])
        return found, (f'Search for an upgrade of {name} completed, found and sent to the download client' if found
                       else f'Search for an upgrade of {name} completed, nothing better found')
    return found, f"Search for upgrades of {len(wanted)} books completed, {found} {plural(found, 'upgrade')} found"


def _name(item: dict) -> str:
    db = database.DBConnection()
    try:
        kind, item_id = item.get('media_type'), item['book_id']
        if kind == 'comic':
            row = db.match('SELECT Title AS Name FROM comics WHERE ComicID=?', (item_id,))
        elif kind == 'magazine':
            return item_id
        else:
            row = db.match('SELECT BookName AS Name FROM books WHERE BookID=?', (item_id,))
    finally:
        db.close()
    return row['Name'] if row else item_id


def _last_download() -> int:
    db = database.DBConnection()
    try:
        return db.match('SELECT IFNULL(MAX(rowid),0) AS last FROM wanted')['last']
    finally:
        db.close()


def _snatched_since(last: int) -> int:
    """ How many downloads were sent to a download client since, the searches don't all say """
    db = database.DBConnection()
    try:
        return db.match("SELECT COUNT(*) AS counter FROM wanted WHERE rowid>? AND Status IN ('Snatched','Seeding',"
                        "'Processed')", (last,))['counter']
    finally:
        db.close()


def _search_kinds(items: list[dict], progress=None):
    """ The automatic search for these items, each {'book_id', 'media_type'}, or for everything
    wanted of these kinds when items is None """
    from lazylibrarian.comicsearch import search_comics  # they import most of LazyLibrarian
    from lazylibrarian.searchbook import search_book
    from lazylibrarian.searchmag import search_magazines

    everything = items is None
    kinds = media_types() if everything else sorted({item.get('media_type') for item in items})
    if everything and ('ebook' in kinds or 'audiobook' in kinds):
        if progress:
            progress('Searching for every wanted book')
        thread_name('FORCE-SEARCHBOOK')
        search_book(None, None)
    for kind, library in LIBRARIES.items():
        ids = [] if everything else [{'bookid': item['book_id']} for item in items if item.get('media_type') == kind]
        if ids:
            if progress:
                progress(f"Searching for {len(ids)} {plural(len(ids), library)}")
            thread_name('FORCE-SEARCHBOOK')
            search_book(ids, library)
    if 'magazine' in kinds:
        mags = None if everything else [{'bookid': item['book_id']} for item in items
                                         if item.get('media_type') == 'magazine']
        if everything or mags:
            if progress:
                progress('Searching for magazines' if everything else
                         f"Searching for {len(mags)} {plural(len(mags), 'magazine')}")
            # recorded under the scheduled search's name when it is the same search
            thread_name('SEARCHALLMAG' if everything else 'FORCE-SEARCHMAG')
            search_magazines(mags)
    if 'comic' in kinds:
        comics = [None] if everything else [item['book_id'] for item in items if item.get('media_type') == 'comic']
        if comics and progress:
            progress('Searching for comics' if everything else
                     f"Searching for {len(comics)} {plural(len(comics), 'comic')}")
        for comicid in comics:
            thread_name('SEARCHALLCOMICS' if everything else 'FORCE-SEARCHCOMIC')
            search_comics(comicid)


def search_books(books: list[dict], progress=None) -> tuple[int, str]:
    """ The automatic search for these items, [{'book_id', 'media_type'}], or for everything wanted
    when there are none. Returns how many it found and sent to a download client, and a message """
    if not CONFIG.total_active_providers():
        raise InvalidRequestError('No search providers are enabled, add one in Settings, Providers')
    if any(book.get('media_type') not in MEDIA_TYPES for book in books):
        raise InvalidRequestError(f"The type is one of {', '.join(MEDIA_TYPES)}")
    last = _last_download()
    _search_kinds(books or None, progress)
    found = _snatched_since(last)
    if not books:
        return found, f"Search for wanted items completed, {found} {plural(found, 'download')} found"
    if len(books) == 1:
        name = _name(books[0])
        if found:
            return found, f'Search for {name} completed, found and sent to the download client'
        hint = '. Try Interactive Search' if books[0].get('media_type') in LIBRARIES else ''
        return found, f'Search for {name} completed, nothing found that the automatic search would take{hint}'
    return found, f"Search for {len(books)} items completed, {found} {plural(found, 'download')} found"


def set_monitored(items: list[dict], monitored: bool) -> str:
    """ Stop looking for these, as Sonarr's unmonitor: books and audiobooks Skipped, magazines and
    comics Paused. Or look for them again: Wanted, and Active """
    from lazylibrarian.services import books as book_service  # they import a lot
    from lazylibrarian.services import comics, magazines

    if not items:
        raise InvalidRequestError('Choose what to change')
    if any(item.get('media_type') not in MEDIA_TYPES for item in items):
        raise InvalidRequestError(f"The type is one of {', '.join(MEDIA_TYPES)}")
    for kind, library in LIBRARIES.items():
        ids = [item['book_id'] for item in items if item.get('media_type') == kind]
        if ids:
            book_service.mark_books('Wanted' if monitored else 'Skipped', ids, library)
    titles = [item['book_id'] for item in items if item.get('media_type') == 'magazine']
    if titles:
        magazines.mark_magazines('Active' if monitored else 'Paused', titles)
    comicids = [item['book_id'] for item in items if item.get('media_type') == 'comic']
    if comicids:
        comics.mark_comics('Active' if monitored else 'Paused', comicids)
    what = f"{len(items)} {plural(len(items), 'item')}"
    return f"Looking for {what} again" if monitored else f"No longer looking for {what}"
