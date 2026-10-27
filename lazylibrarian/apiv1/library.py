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

""" /api/v1/library: the eBooks and audiobooks, magazines and comics with their issues, and the
series, as the library pages show them. Scans and searches are commands """

from typing import Literal

from fastapi import APIRouter, Query

from lazylibrarian.apiv1.author import Changed, SeriesRef
from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import library

router = APIRouter(prefix='/library', tags=['Library'])


class SearchDelay(ApiModel):
    # searches that found nothing, the last, and the hours until the next
    count: int
    last: str
    interval: int


class LibraryBook(ApiModel):
    id: str
    title: str
    subtitle: str
    author_id: str
    author_name: str
    series: list[SeriesRef]
    release_date: str
    image: str
    rating: float
    language: str
    status: str
    # the format of the file the library has, empty when it has none
    format: str
    # when it came into the library
    added: str
    # the owner's reading list it's on
    reading_list: str = ''
    search: SearchDelay | None = None


class SourceLink(ApiModel):
    source: str
    id: str
    url: str


class BookFile(ApiModel):
    path: str
    format: str
    size: int
    exists: bool


class BookDownload(ApiModel):
    id: int
    title: str
    indexer: str
    date: str
    status: str
    source: str
    media_type: str
    message: str


class BookDetail(ApiModel):
    id: str
    title: str
    subtitle: str
    author_id: str
    author_name: str
    series: list[SeriesRef]
    release_date: str
    original_date: str
    publisher: str
    isbn: str
    pages: int
    language: str
    genres: str
    rating: float
    image: str
    description: str
    narrator: str
    locked: bool
    added: str
    links: list[SourceLink]
    status: str
    audio_status: str
    ebook_format: str
    audio_format: str
    scan_result: str
    ebook_file: BookFile | None
    audio_file: BookFile | None
    downloads: list[BookDownload]


class BookMark(ApiModel):
    ids: list[str]
    media_type: str
    # Wanted, Have, Skipped, Ignored, NoDelay, Remove, Delete, Unread, ToRead, Read, Reading, Abandoned
    action: str


class BookPage(ApiModel):
    page: int
    page_size: int
    sort_key: str
    sort_direction: str
    total_records: int
    records: list[LibraryBook]


class Magazine(ApiModel):
    title: str
    status: str
    issues: int
    latest_issue: str
    last_acquired: str
    cover: str
    added: str
    reject_words: str
    language: str
    genre: str


class Issue(ApiModel):
    id: str
    date: str
    acquired: str
    cover: str
    format: str


class MagazineDetail(Magazine):
    issue_list: list[Issue]


class Comic(ApiModel):
    id: str
    title: str
    status: str
    issues: int
    latest_issue: str
    last_acquired: str
    cover: str
    added: str
    publisher: str
    start: str
    first: int
    last: int
    overview: str
    link: str


class ComicIssue(ApiModel):
    id: str
    acquired: str
    cover: str
    overview: str
    format: str


class ComicDetail(Comic):
    issue_list: list[ComicIssue]


class Series(ApiModel):
    id: str
    name: str
    status: str
    author_id: str
    author_name: str
    have: int
    total: int
    percent: int
    source: str


class SeriesBook(ApiModel):
    id: str
    title: str
    subtitle: str
    number: str
    author_id: str
    author_name: str
    image: str
    release_date: str
    status: str
    audio_status: str
    ebook_format: str
    audio_format: str


class SeriesDetail(Series):
    books: list[SeriesBook]


class Editor(ApiModel):
    ids: list[str]
    status: str = ''
    delete_files: bool = False


class IssueEditor(ApiModel):
    ids: list[str]
    delete_files: bool = False


@router.get('/books', response_model=BookPage)
def list_books(media_type: Literal['ebook', 'audiobook'] = Query('ebook', alias='mediaType'), status: str = '',
               search: str = '', page: int = Query(1, ge=1), page_size: int = Query(50, alias='pageSize', ge=1, le=1000),
               sort_key: str = Query('title', alias='sortKey'),
               sort_direction: Literal['ascending', 'descending'] = Query('ascending', alias='sortDirection')):
    """ The eBooks or audiobooks in the library: wanted, snatched or had, or those with status
    (Wanted, Snatched, Open, Have, Skipped, Ignored), All, or those on a reading list (ToRead,
    Read, Reading, Abandoned). Sorted by title, author, released, rating or added (to the library) """
    found = library.list_books(media_type, status, search, sort_key, sort_direction == 'descending',
                               (page - 1) * page_size, page_size)
    return {'page': page, 'page_size': page_size, 'sort_key': sort_key, 'sort_direction': sort_direction,
            'total_records': found.matched, 'records': found.items}


@router.put('/books/mark', response_model=Changed)
def mark_books(mark: BookMark):
    """ Want, have, skip or ignore books as an eBook or audiobook, search again now (NoDelay),
    ignore them (Remove) or delete their files too (Delete), or put them on a reading list
    (ToRead, Read, Reading, Abandoned) or take them off (Unread) """
    result = library.mark_books(mark.ids, mark.media_type, mark.action)
    return {'changed': result['passed'], 'failed': result['failed']}


@router.get('/book/{book_id}', response_model=BookDetail)
def get_book(book_id: str):
    """ A book: its details, links, series, each format's status and file, and its downloads """
    return library.get_book(book_id)


@router.get('/magazines', response_model=list[Magazine])
def list_magazines():
    return library.list_magazines()


@router.get('/magazine', response_model=MagazineDetail)
def get_magazine(title: str):
    """ A magazine, by its title, with its issues """
    return library.get_magazine(title)


@router.put('/magazines', response_model=Changed)
def set_magazine_status(editor: Editor):
    """ Make magazines Active or Paused, by title """
    return {'changed': library.set_magazine_status(editor.ids, editor.status)}


@router.delete('/magazines', response_model=Changed)
def delete_magazines(editor: Editor):
    """ Forget magazines, by title, their issues' files too if deleteFiles """
    return {'changed': library.delete_magazines(editor.ids, editor.delete_files)}


@router.delete('/magazine/issues', response_model=Changed)
def delete_issues(editor: IssueEditor):
    return {'changed': library.delete_issues(editor.ids, editor.delete_files)}


@router.get('/comics', response_model=list[Comic])
def list_comics():
    return library.list_comics()


@router.get('/comic/{comic_id}', response_model=ComicDetail)
def get_comic(comic_id: str):
    return library.get_comic(comic_id)


@router.put('/comics', response_model=Changed)
def set_comic_status(editor: Editor):
    return {'changed': library.set_comic_status(editor.ids, editor.status)}


@router.delete('/comics', response_model=Changed)
def delete_comics(editor: Editor):
    return {'changed': library.delete_comics(editor.ids, editor.delete_files)}


@router.delete('/comic/{comic_id}/issues', response_model=Changed)
def delete_comic_issues(comic_id: str, editor: IssueEditor):
    return {'changed': library.delete_comic_issues(comic_id, editor.ids, editor.delete_files)}


@router.get('/series', response_model=list[Series])
def list_series(status: str = 'All'):
    """ The series; status one of theirs, or Empty, Partial or Complete for how much the library has """
    return library.list_series(status)


@router.get('/series/{series_id}', response_model=SeriesDetail)
def get_series(series_id: str):
    return library.get_series(series_id)


@router.put('/series', response_model=Changed)
def set_series_status(editor: Editor):
    """ Wanted and Active look for the series' books and keep watching it, Skipped, Ignored and
    Paused stop """
    return {'changed': library.set_series_status(editor.ids, editor.status)}
