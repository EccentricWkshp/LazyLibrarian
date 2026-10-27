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

""" /api/v1/qualityprofile, like Sonarr's """

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import profiles

router = APIRouter(prefix='/qualityprofile', tags=['Quality Profile'])


class ProfileItem(ApiModel):
    quality: str
    allowed: bool
    name: str = ''
    imported: bool = True


class QualityProfile(ApiModel):
    id: int = 0
    name: str
    media_type: str
    items: list[ProfileItem]
    cutoff: str
    upgrade_allowed: bool
    is_default: bool = False


class Message(ApiModel):
    message: str


@router.get('', response_model=list[QualityProfile])
def list_profiles():
    """ The quality profiles. items are every quality of the media type, best first, allowed the ones
    the profile wants. A quality that isn't imported (the eBook or audiobook types settings) is
    never downloaded. The default of each media type is the one its searches use """
    return profiles.list_profiles()


@router.get('/schema', response_model=QualityProfile)
def schema(media_type: str = 'ebook'):
    """ A new profile of a media type (ebook or audiobook) to fill in """
    return profiles.schema(media_type)


@router.get('/{profile_id}', response_model=QualityProfile)
def get_profile(profile_id: int):
    return profiles.get(profile_id)


@router.post('', response_model=QualityProfile, status_code=201)
def add_profile(profile: QualityProfile):
    return profiles.save(profile.model_dump())


@router.put('/{profile_id}', response_model=QualityProfile)
def update_profile(profile_id: int, profile: QualityProfile):
    return profiles.save(profile.model_dump(), profile_id)


@router.delete('/{profile_id}', response_model=Message)
def delete_profile(profile_id: int):
    profiles.delete(profile_id)
    return {'message': 'Deleted'}


@router.post('/{profile_id}/default', response_model=QualityProfile)
def make_default(profile_id: int):
    """ Make a profile the one its media type's searches use """
    return profiles.set_default(profile_id)
