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

""" /api/v1/remotepathmapping, like Sonarr's """

from fastapi import APIRouter, Response

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import remotepaths

router = APIRouter(prefix='/remotepathmapping', tags=['Remote Path Mappings'])


class RemotePathMappingIn(ApiModel):
    host: str
    remote_path: str
    local_path: str


class RemotePathMapping(RemotePathMappingIn):
    id: int


def _out(mapping: dict) -> dict:
    return {'id': mapping['Id'], 'host': mapping['Host'], 'remote_path': mapping['RemotePath'],
            'local_path': mapping['LocalPath']}


@router.get('', response_model=list[RemotePathMapping])
def list_mappings():
    """ Every remote path mapping """
    return [_out(mapping) for mapping in remotepaths.mappings()]


@router.get('/{mapping_id}', response_model=RemotePathMapping)
def get_mapping(mapping_id: int):
    return _out(remotepaths.get_mapping(mapping_id))


@router.post('', response_model=RemotePathMapping, status_code=201)
def add_mapping(mapping: RemotePathMappingIn):
    """ Add a mapping. The local path has to exist, and a host can only have one for each remote path """
    return _out(remotepaths.add_mapping(mapping.host, mapping.remote_path, mapping.local_path))


@router.put('/{mapping_id}', response_model=RemotePathMapping)
def update_mapping(mapping_id: int, mapping: RemotePathMappingIn):
    return _out(remotepaths.update_mapping(mapping_id, mapping.host, mapping.remote_path, mapping.local_path))


@router.delete('/{mapping_id}', status_code=204)
def delete_mapping(mapping_id: int):
    remotepaths.delete_mapping(mapping_id)
    return Response(status_code=204)
