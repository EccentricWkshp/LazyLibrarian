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

""" /api/v1/config: the settings by name, for the Settings pages. Secrets are sent back masked,
and saving one masked keeps it """

from typing import Any

from fastapi import APIRouter, Query, Request

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import settings
from lazylibrarian.sessions import SESSION_COOKIE

router = APIRouter(prefix='/config', tags=['Config'])


class ConfigValue(ApiModel):
    key: str
    # bool, int, float, str, csv, url, email, folder, perm, interval or password
    kind: str
    value: Any
    default: Any
    # an interval's: min, hour or day
    unit: str


class Choice(ApiModel):
    value: str
    label: str = ''
    example: str = ''


class Choices(ApiModel):
    themes: list[str]
    ui_languages: list[Choice]
    author_date_formats: list[Choice]
    date_formats: list[Choice]
    issue_date_formats: list[Choice]
    book_statuses: list[str]
    owner: str


class ConfigChange(ApiModel):
    # by setting name; the owner's login as OWNER_USERNAME, OWNER_PASSWORD and OWNER_PASSWORD2
    values: dict[str, Any]


class Saved(ApiModel):
    messages: list[str]


class ApiKeyIn(ApiModel):
    read_only: bool = False


class ApiKey(ApiModel):
    key: str


@router.get('', response_model=list[ConfigValue])
def get_values(keys: list[str] = Query(...)):
    """ Settings by name, with their kind and default """
    return settings.config_values(keys)


@router.get('/choices', response_model=Choices)
def get_choices():
    """ The choices of the settings chosen from a list """
    return settings.config_choices()


@router.put('', response_model=Saved)
def save(change: ConfigChange, request: Request):
    """ Change settings and save them. messages says what wasn't changed, and why """
    return {'messages': settings.save_values(change.values, keep_token=request.cookies.get(SESSION_COOKIE))}


@router.post('/apikey', response_model=ApiKey)
def new_api_key(change: ApiKeyIn):
    """ A new API key, full access or read only. The old one stops working """
    key = settings.new_api_key(change.read_only)
    settings.save_config()
    return {'key': key}


@router.post('/apikey/show', response_model=ApiKey)
def show_api_key(which: ApiKeyIn):
    """ The API key as it is, to copy. A POST, so the read-only key can't see the full one """
    return {'key': CONFIG['API_RO_KEY' if which.read_only else 'API_KEY']}
