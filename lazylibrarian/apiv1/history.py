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

""" /api/v1/history and /api/v1/blocklist, like Sonarr's """

from typing import Literal

from fastapi import APIRouter, Query

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import blocklist, history

router = APIRouter()


class HistoryItem(ApiModel):
    id: int
    event_type: str
    status: str
    media_type: str
    book_id: str
    title: str
    author: str
    author_id: str | None
    issue: str
    source_title: str
    indexer: str
    download_client: str
    download_id: str
    protocol: str
    size: int
    date: str
    message: str


class HistoryPage(ApiModel):
    page: int
    page_size: int
    sort_key: str
    sort_direction: str
    total_records: int
    records: list[HistoryItem]


class BlocklistItem(ApiModel):
    id: int
    media_type: str
    book_id: str
    title: str
    author: str
    author_id: str | None
    issue: str
    source_title: str
    indexer: str
    protocol: str
    size: int
    date: str
    message: str


class BlocklistPage(ApiModel):
    page: int
    page_size: int
    sort_key: str
    sort_direction: str
    total_records: int
    records: list[BlocklistItem]


class Ids(ApiModel):
    ids: list[int]


class Message(ApiModel):
    message: str


def _page(found, page, page_size, sort_key, sort_direction) -> dict:
    return {'page': page, 'page_size': page_size, 'sort_key': sort_key, 'sort_direction': sort_direction,
            'total_records': found.matched, 'records': found.items}


@router.get('/history', response_model=HistoryPage, tags=['History'])
def list_history(page: int = Query(1, ge=1), page_size: int = Query(20, alias='pageSize', ge=1, le=1000),
                 sort_key: str = Query('date', alias='sortKey'),
                 sort_direction: Literal['ascending', 'descending'] = Query('descending', alias='sortDirection'),
                 event_type: str = Query('', alias='eventType'), search: str = ''):
    """ Each download as Sonarr's history event: grabbed, downloadFolderImported or downloadFailed,
    with message saying why one failed or where it was imported to """
    found = history.list_events(event_type, search, sort_key, sort_direction == 'descending',
                                (page - 1) * page_size, page_size)
    return _page(found, page, page_size, sort_key, sort_direction)


@router.post('/history/failed/{item_id}', response_model=Message, tags=['History'])
def mark_failed(item_id: int):
    """ Mark a download failed, as Sonarr's Mark as Failed: its release is blocklisted and its book
    is wanted again """
    history.mark_failed(item_id)
    return {'message': 'Marked as failed, the release is blocklisted and the book is wanted again'}


@router.get('/blocklist', response_model=BlocklistPage, tags=['Blocklist'])
def list_blocklist(page: int = Query(1, ge=1), page_size: int = Query(20, alias='pageSize', ge=1, le=1000),
                   sort_key: str = Query('date', alias='sortKey'),
                   sort_direction: Literal['ascending', 'descending'] = Query('descending', alias='sortDirection'),
                   search: str = ''):
    """ The releases that failed, which the searches won't take again """
    found = blocklist.list_blocklist(search, sort_key, sort_direction == 'descending', (page - 1) * page_size,
                                     page_size)
    return _page(found, page, page_size, sort_key, sort_direction)


@router.delete('/blocklist/bulk', response_model=Message, tags=['Blocklist'])
def remove_from_blocklist(body: Ids):
    """ Take releases off the blocklist, their history stays. The ClearBlocklist command empties it """
    removed = blocklist.remove(body.ids)
    return {'message': f"Removed {removed} from the blocklist"}


@router.delete('/blocklist/{item_id}', response_model=Message, tags=['Blocklist'])
def remove_one(item_id: int):
    removed = blocklist.remove([item_id])
    return {'message': f"Removed {removed} from the blocklist"}
