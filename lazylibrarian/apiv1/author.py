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

""" /api/v1/author and /api/v1/book, like Sonarr's /series and /episode: the authors in the
library, one with their books, and changing what's wanted. Adding and refreshing are commands """

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import library

router = APIRouter(tags=['Author'])


class LastBook(ApiModel):
    id: str
    title: str
    date: str


class Author(ApiModel):
    id: str
    name: str
    sort_name: str
    # Active, Wanted, Paused or Ignored
    status: str
    image: str
    last_book: LastBook | None
    added: str
    # books in the library, and the ones not ignored
    have: int
    total: int
    percent: int
    source: str
    added_reason: str


class SourceLink(ApiModel):
    source: str
    url: str


class AuthorDetail(Author):
    born: str
    died: str
    age: int | None
    about: str
    aka: str
    links: list[SourceLink]
    locked: bool
    ebook_counts: dict[str, int]
    audio_counts: dict[str, int]


class SeriesRef(ApiModel):
    id: str
    name: str
    number: str


class Book(ApiModel):
    id: str
    title: str
    subtitle: str
    release_date: str
    image: str
    rating: float
    language: str
    genres: str
    pages: int
    status: str
    audio_status: str
    # the format of the file the library has, empty when it has none
    ebook_format: str
    audio_format: str
    added: str
    scan_result: str
    # by this author rather than with them
    is_primary: bool
    series: list[SeriesRef]


class AuthorStatus(ApiModel):
    status: str


class AuthorEditor(ApiModel):
    author_ids: list[str]
    status: str = ''
    delete_files: bool = False


class BookStatus(ApiModel):
    book_ids: list[str]
    # ebook, audiobook
    media_types: list[str]
    # Wanted, Skipped, Ignored or Have
    status: str


class Changed(ApiModel):
    changed: int
    failed: int = 0


@router.get('/author', response_model=list[Author])
def list_authors():
    """ Every author, ignored ones too """
    return library.list_authors()


@router.put('/author/editor', response_model=Changed)
def edit_authors(editor: AuthorEditor):
    """ Set authors' status """
    return {'changed': library.set_author_status(editor.author_ids, editor.status)}


@router.delete('/author/editor', response_model=Changed)
def delete_authors(editor: AuthorEditor):
    """ Take authors out of the library, the folders of their books too if deleteFiles """
    return {'changed': library.delete_authors(editor.author_ids, editor.delete_files)}


@router.get('/author/{author_id}', response_model=AuthorDetail)
def get_author(author_id: str):
    return library.get_author(author_id)


@router.put('/author/{author_id}', response_model=AuthorDetail)
def set_author_status(author_id: str, change: AuthorStatus):
    """ Set an author Active, Wanted, Paused or Ignored """
    library.set_author_status([author_id], change.status)
    return library.get_author(author_id)


@router.delete('/author/{author_id}', response_model=Changed)
def delete_author(author_id: str, delete_files: bool = False):
    return {'changed': library.delete_authors([author_id], delete_files)}


@router.get('/author/{author_id}/books', response_model=list[Book])
def list_books(author_id: str):
    """ An author's books, newest first """
    return library.author_books(author_id)


@router.put('/book/status', response_model=Changed)
def set_book_status(change: BookStatus):
    """ Want books, or skip, ignore or mark them had, as eBooks, audiobooks or both """
    result = library.set_book_status(change.book_ids, change.media_types, change.status)
    return {'changed': result['passed'], 'failed': result['failed']}
