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

""" /api/v1/manualimport, /api/v1/book and /api/v1/filesystem: what Manual Import needs, like
Sonarr's. The import itself is the ManualImport command, see command.py """

import os
import string

from fastapi import APIRouter, Query

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.filesystem import path_isdir
from lazylibrarian.services import InvalidRequestError, manualimport

router = APIRouter(tags=['Manual Import'])


class Target(ApiModel):
    id: str
    title: str
    author: str = ''
    issue: str = ''
    media_type: str = ''


class ManualImportItem(ApiModel):
    path: str
    files: list[str]
    relative_path: str
    size: int
    media_type: str
    book: Target | None
    queue_id: int | None
    rejections: list[str]


class ManualImportFolder(ApiModel):
    folder: str
    items: list[ManualImportItem]
    error: str


class Book(ApiModel):
    id: str
    title: str
    author: str
    author_id: str | None = None
    status: str | None
    audio_status: str | None


class Folder(ApiModel):
    name: str
    path: str


class FileSystem(ApiModel):
    path: str
    parent: str | None
    directories: list[Folder]


@router.get('/manualimport', response_model=ManualImportFolder)
def manual_import(folder: str = '', queue_id: int | None = Query(None, alias='queueId')):
    """ What could be imported from a folder, or from a queued download's folder (queueId), with
    the book each item looks like and why any of them can't be imported yet """
    return manualimport.candidates(folder, queue_id)


class SuggestedFolder(ApiModel):
    path: str
    label: str


@router.get('/manualimport/folders', response_model=list[SuggestedFolder])
def suggested_folders():
    """ Where downloads are: the download directories and the remote path mappings' local paths """
    return manualimport.suggested_folders()


@router.get('/book', response_model=list[Book], tags=['Book'])
def books(term: str):
    """ Library books with every word of term in their title or author """
    return manualimport.search_books(term)


@router.get('/book/{book_id}', response_model=Book, tags=['Book'])
def book(book_id: str):
    return manualimport.get_book(book_id)


def _roots() -> list[dict]:
    if os.name == 'nt':
        drives = [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.isdir(f"{letter}:\\")]
        return [{'name': drive, 'path': drive} for drive in drives]
    return [{'name': name, 'path': os.path.join('/', name)} for name in sorted(os.listdir('/'))
            if os.path.isdir(os.path.join('/', name))]


@router.get('/filesystem', response_model=FileSystem, tags=['File System'])
def filesystem(path: str = ''):
    """ The folders in a folder, to choose one. No path lists the top level, and a folder that
    doesn't exist lists the nearest one above it that does """
    if not path:
        return {'path': '', 'parent': None, 'directories': _roots()}
    if not os.path.isabs(path):
        raise InvalidRequestError(f'[{path}] is not a full path')
    while not path_isdir(path):
        parent = os.path.dirname(path.rstrip('/\\'))
        if not parent or parent == path:
            return {'path': '', 'parent': None, 'directories': _roots()}
        path = parent
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError as why:
        raise InvalidRequestError(f'Cannot read [{path}]: {why.strerror}') from why
    folders = [{'name': name, 'path': os.path.join(path, name)} for name in names
               if not name.startswith('.') and os.path.isdir(os.path.join(path, name))]
    parent = os.path.dirname(path.rstrip('/\\')) or None
    if parent == path or (os.name == 'nt' and len(path.rstrip('\\')) <= 2):
        parent = ''
    return {'path': path, 'parent': parent, 'directories': folders}
