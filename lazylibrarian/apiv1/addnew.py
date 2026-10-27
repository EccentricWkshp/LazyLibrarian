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

""" Add New, like Readarr's /search and the lookups: authors and books from the info sources,
magazines by title, comics from ComicVine and Comixology. Authors and books are added by the
AddAuthor and AddBook commands, they take a while; magazines and comics here """

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import addnew

router = APIRouter(tags=['Add New'])


class AuthorLookup(ApiModel):
    id: str
    name: str
    source: str
    in_library: bool
    loading: bool
    books: int
    score: float


class BookLookup(ApiModel):
    id: str
    title: str
    subtitle: str
    author_id: str
    author_name: str
    author_in_library: bool
    isbn: str
    publisher: str
    release_date: str
    language: str
    pages: int
    genres: str
    overview: str
    cover: str
    link: str
    rating: float
    ratings: int
    source: str
    score: float
    in_library: bool
    status: str
    audio_status: str


class Lookup(ApiModel):
    authors: list[AuthorLookup]
    books: list[BookLookup]
    # the book types whose libraries are on
    media_types: list[str] = []


class MagazineLookup(ApiModel):
    title: str
    reject_words: str
    in_library: bool
    issues: int
    # the periodical on Wikidata, empty for the title as it was typed
    wikidata_id: str = ''
    description: str = ''
    started: str = ''


class MagazineIn(ApiModel):
    title: str
    reject_words: str = ''
    search: bool = False
    # the periodical on Wikidata it is, else the one called exactly its title
    wikidata_id: str = ''


class Magazine(ApiModel):
    title: str


class ComicLookup(ApiModel):
    id: str
    title: str
    publisher: str
    start: str
    first: int
    last: int
    issues: int
    overview: str
    link: str
    score: int
    in_library: bool


class ComicIn(ApiModel):
    id: str
    search: bool = False


class Comic(ApiModel):
    id: str
    title: str


@router.get('/lookup', response_model=Lookup)
def lookup(term: str):
    """ Authors and books matching a name, title or ISBN at the info sources, each saying whether
    it's in the library. Add them with the AddAuthor and AddBook commands """
    return {**addnew.lookup(term), 'media_types': addnew.media_types()}


@router.get('/magazine/lookup', response_model=list[MagazineLookup])
def lookup_magazine(term: str):
    """ The magazine a title would add, first unless it's there, the ones in the library with the
    title in theirs, and the periodicals Wikidata finds. After a ~ come words that rule a release out """
    return addnew.lookup_magazine(term)


@router.post('/magazine', response_model=Magazine, status_code=201)
def add_magazine(magazine: MagazineIn):
    """ Add a magazine; its details come from Wikidata in the background (RefreshMagazine) """
    return addnew.add_magazine(magazine.title, magazine.reject_words, magazine.search, magazine.wikidata_id)


@router.get('/comic/lookup', response_model=list[ComicLookup])
def lookup_comic(term: str):
    """ Comics matching a title at ComicVine (it needs an API key) and Comixology """
    return addnew.lookup_comic(term)


@router.post('/comic', response_model=Comic, status_code=201)
def add_comic(comic: ComicIn):
    """ Add a comic the last lookup found """
    return addnew.add_comic(comic.id, comic.search)
