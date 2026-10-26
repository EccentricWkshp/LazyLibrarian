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

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import system, tasks

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


@router.get('/status', response_model=SystemStatus)
def get_status():
    """ Versions, platform and web settings """
    return system.status()


@router.get('/task', response_model=list[Task])
def list_tasks():
    """ The scheduled tasks, like Sonarr's: interval in minutes, lastDuration in seconds, and why a
    task doesn't run when it doesn't. The RunTask command runs one now """
    return tasks.list_tasks()
