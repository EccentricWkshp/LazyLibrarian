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

""" /api/v1/queue, like Sonarr's """

from fastapi import APIRouter, Query

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import queue

router = APIRouter(prefix='/queue', tags=['Queue'])


class StatusMessage(ApiModel):
    title: str
    messages: list[str]


class QueueItem(ApiModel):
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
    download_client: str
    download_id: str
    size: int
    added: str
    progress: int
    status: str
    tracked_download_state: str
    tracked_download_status: str
    status_messages: list[StatusMessage]
    error_message: str = ''


class RemoveResult(ApiModel):
    message: str


@router.get('', response_model=list[QueueItem])
def list_queue():
    """ What has been sent to a download client and not imported yet. status, trackedDownloadState
    and trackedDownloadStatus are Sonarr's: a finished download that couldn't be imported is
    completed, importBlocked and warning, with the reason in statusMessages """
    return queue.list_queue()


@router.delete('/{item_id}', response_model=RemoveResult)
def remove(item_id: int, remove_from_client: bool = Query(True, alias='removeFromClient'),
           blocklist: bool = False, skip_redownload: bool = Query(False, alias='skipRedownload')):
    """ Take a download off the queue. removeFromClient deletes it and its files from the download
    client, blocklist stops a search taking that release again and searches again unless
    skipRedownload. Without blocklist the item is wanted again """
    return {'message': queue.remove(item_id, remove_from_client, blocklist, skip_redownload)}
