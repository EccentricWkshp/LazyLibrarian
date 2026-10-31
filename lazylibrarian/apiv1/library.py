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
from pydantic import Field

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
    # all of them, an audiobook's parts
    size: int
    exists: bool
    # an audiobook's files, from its first part
    parts: list[str] = []


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
    # the details filled in from the other info sources, and from which
    filled_from: str = ''


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
    publisher: str = ''
    # days between issues, from Wikidata, 0 when it isn't known
    frequency: int = 0
    # the issues the owner hasn't finished
    unread: int = 0


class Issue(ApiModel):
    id: str
    date: str
    acquired: str
    cover: str
    format: str
    # what its file says
    description: str = ''
    pages: int = 0
    number: str = ''
    # the owner has finished it, or opened it
    read: bool = False
    started: bool = False


class IssueSchedule(ApiModel):
    # days between issues, taken from the issues when inferred, 0 when it can't be told
    frequency: int
    inferred: bool
    # the issue dates or numbers missing between the first and the latest
    missing: list[str]
    # the next issue's date, or number
    next: str
    overdue: bool


class MagazineDetail(Magazine):
    description: str = ''
    issn: str = ''
    country: str = ''
    website: str = ''
    logo: str = ''
    started: str = ''
    wikidata_id: str = ''
    cover_page: int = 1
    # how many of its newest issues it keeps, and of how many months; 0 for all
    keep_issues: int = 0
    keep_months: int = 0
    schedule: IssueSchedule
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
    # the issues the owner hasn't finished
    unread: int = 0


class ComicIssue(ApiModel):
    id: str
    acquired: str
    cover: str
    overview: str
    format: str
    pages: int = 0
    read: bool = False
    started: bool = False


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


class RemovedBook(ApiModel):
    id: str
    title: str
    number: str


class SeriesDetail(Series):
    books: list[SeriesBook]
    # the books taken out of it by hand, they stay out until put back
    removed: list[RemovedBook] = []


class Editor(ApiModel):
    ids: list[str]
    status: str = ''
    delete_files: bool = False


class IssueEditor(ApiModel):
    ids: list[str]
    delete_files: bool = False


class RecentIssue(ApiModel):
    # an issue's id, a comic issue's comicid_issueid
    id: str
    # the magazine's or comic's title
    title: str
    # its date or number
    issue: str
    # the magazine's title or the comic's id, for its page
    parent_id: str
    acquired: str
    cover: str
    format: str


class IssuePage(ApiModel):
    issue_id: str
    # the magazine
    title: str
    date: str
    cover: str
    page: int
    # the words around the ones searched for, which are between [ and ]
    snippet: str


class PastIssue(ApiModel):
    # the release's link, which identifies it
    url: str
    release_title: str
    date: str
    issue: str
    indexer: str
    # the magazine
    title: str
    # why it has no issue: set aside (several issues in one, a special, another edition), or no date
    # or number the magazine's issues can be matched to; or why its download failed
    reason: str = ''
    # the issue its name gives, as it would be typed, when it has none the magazine's issues match
    named: str = ''
    # another edition's words, as the name has them (South Africa), when it's set aside as one
    edition: str = ''
    # its issue is in the library now, found since it was stored
    in_library: bool = False


class PastIssueEdition(ApiModel):
    url: str


class EditionAdded(ApiModel):
    # the edition's magazine, and how many past issues moved to it
    title: str
    moved: int


class PastIssueMark(ApiModel):
    urls: list[str]
    # Skipped, Wanted, Ignored or Remove
    action: str
    # for one that's wanted, the issue to file it under, typed as in an issue's Edit
    issue: str = ''


class CoverPage(ApiModel):
    # counted from 1, 0 for no cover
    page: int = Field(ge=0)


class Message(ApiModel):
    message: str


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


@router.get('/issues/recent', response_model=list[RecentIssue])
def recent_issues(media_type: Literal['magazine', 'comic'] = Query('magazine', alias='mediaType'), limit: int = 0):
    """ The magazine or comic issues acquired most recently, as many as the cover wall shows unless
    limit is given """
    return library.recent_issues(media_type, limit)


@router.get('/magazine/search', response_model=list[IssuePage])
def search_issues(q: str, limit: int = Query(100, ge=1, le=500)):
    """ The pages of issues with these words, best first. Words in quotes are a phrase, the last word
    can be the start of one. The IndexIssues command puts the issues' words in the index """
    return library.search_issues(q, limit)


@router.get('/magazine/pastissues', response_model=list[PastIssue])
def list_past_issues(status: str = 'Skipped', title: str = ''):
    """ Search results for magazines' issues that weren't wanted when they were found (Skipped,
    Have, Ignored, Wanted or Snatched), one magazine's when title is given """
    return library.list_past_issues(status, title)


@router.put('/magazine/pastissues', response_model=Changed)
def mark_past_issues(mark: PastIssueMark):
    """ Want past issues (they're downloaded), skip or ignore them, or forget them (Remove) """
    return {'changed': library.mark_past_issues(mark.urls, mark.action, mark.issue)}


@router.post('/magazine/pastissues/edition', response_model=EditionAdded)
def add_edition(edition: PastIssueEdition):
    """ The other edition a past issue is, added as a magazine of its own, with that edition's past
    issues moved to it """
    return library.add_edition(edition.url)


@router.put('/magazine/issue/{issue_id}/cover', response_model=Message)
def set_issue_cover(issue_id: str, cover: CoverPage):
    """ Make an issue's cover from one of its pages, counted from 1, or none (page 0) """
    return {'message': library.set_issue_cover('magazine', issue_id, cover.page)}


@router.put('/comic/{comic_id}/issue/{issue_id}/cover', response_model=Message)
def set_comic_issue_cover(comic_id: str, issue_id: str, cover: CoverPage):
    return {'message': library.set_issue_cover('comic', f"{comic_id}_{issue_id}", cover.page)}


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
    """ The series; status one of theirs, Empty, Partial or Complete for how much the library has, or
    AllButIgnored, the list as the page shows it with the ignored ones hidden """
    return library.list_series(status)


@router.get('/series/{series_id}', response_model=SeriesDetail)
def get_series(series_id: str):
    return library.get_series(series_id)


class SeriesMember(ApiModel):
    number: str
    title: str
    author_name: str
    author_id: str
    year: str
    # the book at the series' info source, '' when it gave none
    id: str
    source: str
    in_library: bool
    library_id: str
    status: str
    audio_status: str


@router.get('/series/{series_id}/lookup', response_model=list[SeriesMember])
def series_lookup(series_id: str):
    """ The books in the series as its info source lists them, in order, each saying whether the
    library has it. One it hasn't can be added with the AddBook command """
    return library.series_lookup(series_id)


@router.delete('/series/{series_id}/books', response_model=Changed)
def remove_from_series(series_id: str, editor: Editor):
    """ Take books out of a series and keep them out, whatever source or refresh lists them in it """
    return {'changed': library.remove_from_series(series_id, editor.ids)}


@router.put('/series/{series_id}/books', response_model=Changed)
def put_back_in_series(series_id: str, editor: Editor):
    """ Put books taken out of a series back in it """
    return {'changed': library.put_back_in_series(series_id, editor.ids)}


@router.put('/series', response_model=Changed)
def set_series_status(editor: Editor):
    """ Wanted and Active look for the series' books and keep watching it, Skipped, Ignored and
    Paused stop """
    return {'changed': library.set_series_status(editor.ids, editor.status)}
