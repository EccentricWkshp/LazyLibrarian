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

""" /api/v1/log, /api/v1/log/file and /api/v1/update, like Sonarr's """

import os

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import system, updates

router = APIRouter()


class Event(ApiModel):
    time: str
    level: str
    thread: str
    file: str
    method: str
    line: int
    message: str


class EventPage(ApiModel):
    page: int
    page_size: int
    total_records: int
    records: list[Event]


class LogFile(ApiModel):
    filename: str
    size: int
    last_write_time: str


class Update(ApiModel):
    version: str
    latest_version: str
    branch: str
    install_type: str
    behind: int
    changes: list[str]
    message: str
    can_install: bool
    why_not: str
    last_checked: str | None
    repo: str


class Message(ApiModel):
    message: str


@router.get('/log', response_model=EventPage, tags=['Log'])
def list_events(page: int = Query(1, ge=1), page_size: int = Query(50, alias='pageSize', ge=1, le=1000),
                level: str = '', search: str = ''):
    """ The log kept in memory, the most recent first, at level (info, warn or error) and above """
    found = system.list_events(level, search, (page - 1) * page_size, page_size)
    return {'page': page, 'page_size': page_size, 'total_records': found.matched, 'records': found.items}


@router.delete('/log', response_model=Message, tags=['Log'])
def clear_events():
    system.clear_log()
    return {'message': 'Cleared'}


@router.get('/log/file', response_model=list[LogFile], tags=['Log'])
def list_log_files():
    return system.list_log_files()


@router.delete('/log/file', response_model=Message, tags=['Log'])
def delete_log_files():
    return {'message': system.delete_log_files()}


@router.get('/log/supportzip', tags=['Log'])
def support_zip():
    """ The log and settings with passwords and keys taken out, to send with a problem """
    path = system.support_zip()
    return FileResponse(path, media_type='application/zip', filename=os.path.basename(path))


@router.get('/log/zip', tags=['Log'])
def logs_zip():
    """ Every log file, as it is, in one zip """
    return FileResponse(system.logs_zip(), media_type='application/zip', filename='lazylibrarian-logs.zip')


@router.get('/log/file/{filename}', tags=['Log'])
def log_file(filename: str):
    return FileResponse(system.log_file_path(filename), media_type='text/plain; charset=utf-8',
                        content_disposition_type='inline')


@router.get('/update', response_model=Update, tags=['Update'])
def update_info():
    """ The version running and what has changed since, as the last check for updates found. The
    ApplicationUpdate command installs it, when LazyLibrarian can """
    return updates.info()
