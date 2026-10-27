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

""" /api/v1/system """

import asyncio
import contextlib
import os
import tempfile

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.filesystem import DIRS
from lazylibrarian.services import backups, system, tasks

router = APIRouter(prefix='/system', tags=['System'])


class SystemStatus(ApiModel):
    app_name: str
    version: str
    branch: str
    install_type: str
    latest_version: str
    commits_behind: int
    database_version: int
    url_base: str
    authentication: str
    is_docker: bool
    os_name: str
    os_version: str
    python_version: str
    app_data: str
    startup_path: str
    database_path: str
    start_time: str


class Task(ApiModel):
    name: str
    task_name: str
    interval: int
    last_start_time: str | None
    last_execution: str | None
    last_duration: float | None
    next_execution: str | None
    is_running: bool
    disabled_reason: str


class ManualTask(ApiModel):
    # the command that runs it
    command: str
    task_name: str
    description: str
    last_start_time: str | None
    last_execution: str | None
    last_duration: float | None
    is_running: bool


@router.get('/status', response_model=SystemStatus)
def get_status():
    """ Versions, platform and web settings """
    return system.status()


class Backup(ApiModel):
    id: str
    name: str
    type: str
    size: int
    time: str


class Message(ApiModel):
    message: str


@router.get('/task', response_model=list[Task])
def list_tasks():
    """ The scheduled tasks, like Sonarr's: interval in minutes, lastDuration in seconds, and why a
    task doesn't run when it doesn't. The RunTask command runs one now """
    return tasks.list_tasks()


@router.get('/task/manual', response_model=list[ManualTask])
def list_manual_tasks():
    """ The tasks that only run when asked, each by the command that runs it """
    return tasks.list_manual_tasks()


@router.post('/restart', response_model=Message)
def restart():
    system.request_stop('restart')
    return {'message': 'Restarting'}


@router.post('/shutdown', response_model=Message)
def shutdown():
    system.request_stop('shutdown')
    return {'message': 'Shutting down'}


@router.get('/backup', response_model=list[Backup], tags=['Backup'])
def list_backups():
    """ The backups, the most recent first. type is scheduled, manual, update or restore (what was
    there before a restore). The Backup command makes one now """
    return backups.list_backups()


@router.get('/backup/file/{backup_id:path}', tags=['Backup'])
def download_backup(backup_id: str):
    path = backups.path_of(backup_id)
    return FileResponse(path, media_type='application/gzip', filename=os.path.basename(path))


@router.delete('/backup/{backup_id:path}', response_model=Message, tags=['Backup'])
def delete_backup(backup_id: str):
    backups.delete(backup_id)
    return {'message': 'Deleted'}


@router.post('/backup/restore/{backup_id:path}', response_model=Message, tags=['Backup'])
def restore_backup(backup_id: str):
    """ Restore a backup: LazyLibrarian restarts and puts it in place as it starts, keeping what was
    there as a backup of its own """
    path = backups.path_of(backup_id)
    backups.stage_restore(path, os.path.basename(path))
    system.request_stop('restart')
    return {'message': 'Restoring, LazyLibrarian is restarting'}


@router.post('/backup/upload', response_model=Message, tags=['Backup'])
async def upload_backup(request: Request):
    """ Restore a backup sent as the request's body, a .tgz from System, Backup """
    handle, path = tempfile.mkstemp(suffix='.tgz', dir=DIRS.DATADIR)
    try:
        with os.fdopen(handle, 'wb') as out:
            async for chunk in request.stream():
                out.write(chunk)
        name = request.headers.get('X-File-Name') or 'an uploaded backup'
        await asyncio.to_thread(backups.stage_restore, path, os.path.basename(name))
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)
    system.request_stop('restart')
    return {'message': 'Restoring, LazyLibrarian is restarting'}
