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

""" /api/v1/health and /api/v1/diskspace, like Sonarr's """

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import health

router = APIRouter(tags=['Health'])


class HealthCheck(ApiModel):
    source: str
    type: str
    message: str
    link: str


class DiskSpace(ApiModel):
    path: str
    label: str
    free_space: int
    total_space: int


@router.get('/health', response_model=list[HealthCheck])
def list_health():
    """ What stops LazyLibrarian working as it should, errors first: type is error, warning or
    notice, link where to put it right. The download clients' answers are kept 5 minutes """
    return health.checks()


@router.get('/diskspace', response_model=list[DiskSpace])
def disk_space():
    """ Each disk the libraries, downloads and LazyLibrarian's data are on, in bytes """
    return health.disk_space()
