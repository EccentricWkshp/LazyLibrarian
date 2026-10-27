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
#
# Purpose:
#   The REST API at /api/v1 below HTTP_ROOT, like Sonarr's /api/v3. Each area has a module
#   with its routes, which check the input and call the services that do the work. JSON field
#   names are camelCase. webapp.py mounts the router and adds the authentication.

from fastapi import APIRouter, HTTPException

from lazylibrarian.apiv1 import (
    addnew,
    command,
    events,
    health,
    history,
    log,
    manualimport,
    notification,
    profiles,
    queue,
    remotepathmapping,
    system,
    wanted,
)

router = APIRouter(prefix='/api/v1')
router.include_router(system.router)
router.include_router(health.router)
router.include_router(log.router)
router.include_router(queue.router)
router.include_router(history.router)
router.include_router(wanted.router)
router.include_router(manualimport.router)
router.include_router(command.router)
router.include_router(profiles.router)
router.include_router(events.router)
router.include_router(remotepathmapping.router)
router.include_router(notification.router)
router.include_router(addnew.router)


@router.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], include_in_schema=False)
def not_found(path: str):
    """ Keep unknown /api/v1 paths away from the CherryPy pages, which would take /api as the old API """
    raise HTTPException(404, f'No such endpoint: {path}')
