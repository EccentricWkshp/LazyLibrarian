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

""" /api/v1/wanted/missing and /api/v1/release, like Sonarr's """

from typing import Literal

from fastapi import APIRouter, Query

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import releases, wanted

router = APIRouter(tags=['Wanted'])


class MissingBook(ApiModel):
    id: str
    book_id: str
    title: str
    subtitle: str
    author: str
    author_id: str | None
    media_type: str
    added: str
    published: str


class MissingPage(ApiModel):
    page: int
    page_size: int
    sort_key: str
    sort_direction: str
    total_records: int
    records: list[MissingBook]


class Release(ApiModel):
    id: str
    title: str
    indexer: str
    protocol: str
    size: int
    seeders: int
    score: float
    rejections: list[str]
    approved: bool


class ReleaseChoice(ApiModel):
    id: str


class Message(ApiModel):
    message: str


@router.get('/wanted/missing', response_model=MissingPage)
def missing(page: int = Query(1, ge=1), page_size: int = Query(20, alias='pageSize', ge=1, le=1000),
            sort_key: str = Query('added', alias='sortKey'),
            sort_direction: Literal['ascending', 'descending'] = Query('descending', alias='sortDirection'),
            media_type: str = Query('', alias='mediaType'), search: str = ''):
    """ What is wanted, a page at a time, like Sonarr's Wanted, Missing: books and audiobooks, and
    the magazines and comics that are active, each with its latest issue """
    found = wanted.list_missing(media_type, search, sort_key, sort_direction == 'descending',
                                (page - 1) * page_size, page_size)
    return {'page': page, 'page_size': page_size, 'sort_key': sort_key, 'sort_direction': sort_direction,
            'total_records': found.matched, 'records': found.items}


class WantedItem(ApiModel):
    book_id: str
    media_type: str


class Monitor(ApiModel):
    items: list[WantedItem]
    monitored: bool


@router.put('/wanted/missing/monitor', response_model=Message)
def monitor(body: Monitor):
    """ Stop looking for these (monitored false), as Sonarr's Unmonitor: books and audiobooks are
    Skipped, magazines and comics Paused. Or look for them again """
    return {'message': wanted.set_monitored([item.model_dump() for item in body.items], body.monitored)}


@router.get('/release', response_model=list[Release], tags=['Release'])
def search_releases(book_id: str = Query(alias='bookId'), media_type: str = Query(alias='mediaType')):
    """ Interactive search: every release the providers have for a book, with the reasons the
    automatic search would reject each. Takes as long as the providers do """
    return releases.search(book_id, media_type)


@router.post('/release', response_model=Message, tags=['Release'])
def download_release(choice: ReleaseChoice):
    """ Download a release from an interactive search, by its id """
    return {'message': releases.download(choice.id)}
