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

""" Editing an author, book, magazine, issue, comic or series: GET .../edit for what can be changed,
PUT it back with the fields to change, the ones left out stay as they are """

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import authors, editing

router = APIRouter(tags=['Edit'])


class Message(ApiModel):
    message: str


class NamedValue(ApiModel):
    name: str
    value: str


# --- authors

class AuthorSource(ApiModel):
    source: str
    # the author's id in it, '' when not linked
    id: str
    enabled: bool
    # the one their link and badge use
    primary: bool


class AuthorEdit(ApiModel):
    id: str
    name: str
    born: str
    died: str
    aka: str
    amazon_url: str
    about: str
    locked: bool
    # why they were added
    reason: str
    image: str
    sources: list[AuthorSource]


class AuthorChange(ApiModel):
    name: str | None = None
    born: str | None = None
    died: str | None = None
    aka: str | None = None
    amazon_url: str | None = None
    about: str | None = None
    locked: bool | None = None
    # a link or file for their picture, 'none' for none
    image: str | None = None
    # one of the pictures found, by its path
    found: str | None = None


class Picture(ApiModel):
    name: str
    # from the data folder
    path: str


class SourceMatch(ApiModel):
    found: bool
    id: str = ''
    name: str = ''
    link: str = ''


class SourceLinkIn(ApiModel):
    source_id: str


@router.get('/author/{author_id}/edit', response_model=AuthorEdit)
def get_author(author_id: str):
    return editing.author_for_edit(author_id)


@router.put('/author/{author_id}/edit', response_model=Message)
def save_author(author_id: str, change: AuthorChange):
    return {'message': editing.save_author(author_id, change.model_dump(exclude_unset=True))}


@router.get('/author/{author_id}/images', response_model=list[Picture])
def author_images(author_id: str):
    """ Pictures of the author found online, to choose one from. It takes a while """
    return editing.author_images(author_id)


@router.post('/author/{author_id}/source/{source}/search', response_model=SourceMatch)
def search_source(author_id: str, source: str):
    """ Look the author up by name at a source, to link them to it. Nothing is changed """
    found = authors.search_source(author_id, source)
    if not found:
        return {'found': False}
    return {'found': True, 'id': str(found['authorid']), 'name': found['authorname'] or '',
            'link': found['authorlink'] or ''}


@router.put('/author/{author_id}/source/{source}', response_model=list[AuthorSource])
def link_source(author_id: str, source: str, link: SourceLinkIn):
    """ Link the author to their id at a source """
    authors.link_source(author_id, source, link.source_id.strip())
    return editing.author_for_edit(author_id)['sources']


@router.delete('/author/{author_id}/source/{source}', response_model=list[AuthorSource])
def unlink_source(author_id: str, source: str):
    authors.unlink_source(author_id, source)
    return editing.author_for_edit(author_id)['sources']


@router.post('/author/{author_id}/source/{source}/primary', response_model=list[AuthorSource])
def set_primary_source(author_id: str, source: str):
    """ Use this linked source for the author's link and badge """
    authors.set_primary_source(author_id, source)
    return editing.author_for_edit(author_id)['sources']


# --- books

class SeriesEntry(ApiModel):
    name: str
    number: str


class BookEdit(ApiModel):
    id: str
    title: str
    subtitle: str
    author: str
    genre: str
    language: str
    release_date: str
    isbn: str
    work_id: str
    narrator: str
    description: str
    locked: bool
    added_by: str
    # its cover now
    image: str
    # by source
    source_ids: dict[str, str]
    series: list[SeriesEntry]
    # the series of its author, to add it to
    author_series: list[str]
    # the authors it can be moved to
    authors: list[str]
    # the other fields of its opf file
    opf_fields: list[NamedValue]


class BookChange(ApiModel):
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    genre: str | None = None
    language: str | None = None
    release_date: str | None = None
    isbn: str | None = None
    work_id: str | None = None
    narrator: str | None = None
    description: str | None = None
    locked: bool | None = None
    # every series it's in, one without a number is taken out
    series: list[SeriesEntry] | None = None
    opf_fields: list[NamedValue] | None = None
    # one of the covers found, by its source
    cover: str | None = None
    # a folder or file to import its files from
    import_from: str | None = None


class CoverChoice(ApiModel):
    source: str
    path: str


@router.get('/library/book/{book_id}/edit', response_model=BookEdit)
def get_book(book_id: str):
    return editing.book_for_edit(book_id)


@router.put('/library/book/{book_id}/edit', response_model=Message)
def save_book(book_id: str, change: BookChange):
    return {'message': editing.save_book(book_id, change.model_dump(exclude_unset=True))}


@router.get('/library/book/{book_id}/covers', response_model=list[CoverChoice])
def book_covers(book_id: str):
    """ Covers for the book found online, the current one first. It takes a while """
    return editing.book_covers(book_id)


# --- magazines and their issues

class MagazineEdit(ApiModel):
    title: str
    # words that rule a release out
    reject: str
    # what it's searched for, instead of its title
    regex: str
    genre: str
    # the parts of its issue dates: Y, M, D, V, I, MM for two months, '' to tell
    date_type: str
    cover_page: int
    language: str


class MagazineChange(ApiModel):
    title: str | None = None
    reject: str | None = None
    regex: str | None = None
    genre: str | None = None
    date_type: str | None = None
    cover_page: int | None = None
    language: str | None = None


class TitleSaved(ApiModel):
    # the magazine's title now
    title: str
    message: str


class IssueEdit(ApiModel):
    id: str
    title: str
    issue_date: str
    file: str
    # the pdf's tags
    tags: list[NamedValue]


class IssueChange(ApiModel):
    title: str | None = None
    issue_date: str | None = None
    tags: list[NamedValue] | None = None


@router.get('/library/magazine/edit', response_model=MagazineEdit)
def get_magazine(title: str):
    return editing.magazine_for_edit(title)


@router.put('/library/magazine/edit', response_model=TitleSaved)
def save_magazine(title: str, change: MagazineChange):
    """ Change a magazine's filters, or rename it, which moves its issue files """
    return editing.save_magazine(title, change.model_dump(exclude_unset=True))


@router.get('/library/magazine/issue/{issue_id}/edit', response_model=IssueEdit)
def get_issue(issue_id: str):
    return editing.issue_for_edit(issue_id)


@router.put('/library/magazine/issue/{issue_id}/edit', response_model=TitleSaved)
def save_issue(issue_id: str, change: IssueChange):
    """ Move an issue to another magazine or issue date, or change its pdf's tags. title is the
    magazine to show after """
    return editing.save_issue(issue_id, change.model_dump(exclude_unset=True))


# --- comics and series

class ComicEdit(ApiModel):
    id: str
    title: str
    aka: str
    description: str
    genre: str


class ComicChange(ApiModel):
    id: str | None = None
    title: str | None = None
    aka: str | None = None
    description: str | None = None
    genre: str | None = None


class IdSaved(ApiModel):
    # its id now
    id: str
    message: str


class SeriesMember(ApiModel):
    number: str
    title: str


class SeriesEdit(ApiModel):
    id: str
    name: str
    reason: str
    members: list[SeriesMember]


class SeriesChange(ApiModel):
    id: str | None = None
    name: str | None = None


@router.get('/library/comic/{comic_id}/edit', response_model=ComicEdit)
def get_comic(comic_id: str):
    return editing.comic_for_edit(comic_id)


@router.put('/library/comic/{comic_id}/edit', response_model=IdSaved)
def save_comic(comic_id: str, change: ComicChange):
    return editing.save_comic(comic_id, change.model_dump(exclude_unset=True))


@router.get('/library/series/{series_id}/edit', response_model=SeriesEdit)
def get_series(series_id: str):
    return editing.series_for_edit(series_id)


@router.put('/library/series/{series_id}/edit', response_model=IdSaved)
def save_series(series_id: str, change: SeriesChange):
    return editing.save_series(series_id, change.model_dump(exclude_unset=True))
