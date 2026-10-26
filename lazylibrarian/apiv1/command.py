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

""" /api/v1/command, like Sonarr's: start work that runs in the background, then ask how it went """

from typing import Any

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import commands

router = APIRouter(prefix='/command', tags=['Command'])


class ManualImportFile(ApiModel):
    path: str
    files: list[str] = []
    media_type: str
    book_id: str = ''
    queue_id: int | None = None


class CommandIn(ApiModel):
    name: str
    files: list[ManualImportFile] = []


class Command(ApiModel):
    id: int
    name: str
    status: str
    message: str
    queued: str
    started: str | None
    ended: str | None
    result: Any = None


@router.post('', response_model=Command, status_code=201)
def start(command: CommandIn):
    """ Start a command. ManualImport imports files, each with the book it is for (bookId and
    mediaType) and, when it came from the queue, its queueId """
    return commands.start(command.name, command.model_dump())


@router.get('', response_model=list[Command])
def list_commands():
    """ The commands since LazyLibrarian started, the most recent first """
    return commands.list_commands()


@router.get('/{command_id}', response_model=Command)
def get_command(command_id: int):
    return commands.get(command_id)
