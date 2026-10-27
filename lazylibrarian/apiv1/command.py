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


class BookRef(ApiModel):
    book_id: str
    media_type: str


class CommandIn(ApiModel):
    name: str
    files: list[ManualImportFile] = []
    books: list[BookRef] = []
    task: str = ''
    author_id: str = ''
    author_name: str = ''
    book_id: str = ''
    source: str = ''
    monitor: str = 'new'
    media_types: list[str] = []
    search: bool = False


class Command(ApiModel):
    id: int
    name: str
    title: str
    status: str
    message: str
    queued: str
    started: str | None
    ended: str | None
    result: Any = None


@router.post('', response_model=Command, status_code=201)
def start(command: CommandIn):
    """ Start a command. ManualImport imports files, each with the book it is for (bookId and
    mediaType) and, when it came from the queue, its queueId. BookSearch searches for books
    (bookId and mediaType), MissingBookSearch for every wanted book, ClearBlocklist empties the
    blocklist, RunTask runs a scheduled task (task, its name from /system/task) now.

    AddAuthor adds an author from /lookup (authorId, authorName) with all their books: monitor
    new wants them as the settings say, all wants every one as mediaTypes (ebook, audiobook), none
    pauses the author; search searches for the ones wanted. AddBook adds a book from /lookup
    (bookId, source, authorId) and wants it as mediaTypes. RefreshAuthor (authorId) and RefreshBook
    (bookId) fetch their details again """
    return commands.start(command.name, command.model_dump())


@router.get('', response_model=list[Command])
def list_commands():
    """ The commands since LazyLibrarian started, the most recent first """
    return commands.list_commands()


@router.get('/{command_id}', response_model=Command)
def get_command(command_id: int):
    return commands.get(command_id)
