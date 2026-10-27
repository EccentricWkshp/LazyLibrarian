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
author with their books, and changing what's wanted of them. The old pages' services do the work,
this shapes it for /api/v1 """

import lazylibrarian
from lazylibrarian import database, quality
from lazylibrarian.formatter import check_float, check_int
from lazylibrarian.services import InvalidRequestError, authors, books

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

    def file_format(path, media_type) -> str:
        return quality.name(quality.of_file(path, media_type)) if path else ''

    found = [{'id': row['BookID'], 'title': row['BookName'] or '', 'subtitle': row['BookSub'] or '',
              'release_date': row['BookDate'] or '', 'image': row['BookImg'] or '',
              'rating': check_float(row['BookRate'], 0), 'language': row['BookLang'] or '',
              'genres': row['BookGenre'] or '', 'pages': check_int(row['BookPages'], 0),
              'status': row['Status'] or '', 'audio_status': row['AudioStatus'] or '',
              'ebook_format': file_format(row['BookFile'], 'ebook'),
              'audio_format': file_format(row['AudioFile'], 'audiobook'),
              'added': row['BookAdded'] or '', 'scan_result': row['ScanResult'] or '',
              'is_primary': row['AuthorID'] == author_id, 'series': series.get(row['BookID'], [])}
             for row in rows]
    return sorted(found, key=lambda b: (b['release_date'] or '0000', b['title'].lower()), reverse=True)


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
