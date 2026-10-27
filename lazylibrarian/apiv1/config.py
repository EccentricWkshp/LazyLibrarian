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
    # a language's value is its codes
    book_languages: list[Choice]
    countries: list[Choice]
    magazine_languages: list[Choice]
    date_languages: list[str]
    special_logs: list[Choice]


class ConfigChange(ApiModel):
    # by setting name; the owner's login as OWNER_USERNAME, OWNER_PASSWORD and OWNER_PASSWORD2
    values: dict[str, Any]


class Saved(ApiModel):
    messages: list[str]


class ConfigKeys(ApiModel):
    keys: list[str]


class ListItem(ApiModel):
    index: int
    # its section, like newznab_0
    name: str
    values: list[ConfigValue]


class SavedItem(ListItem):
    messages: list[str]


class ConfigTest(ApiModel):
    # the connection: a download client, notifier, indexer or tool, or a list's item
    test: str = ''
    values: dict[str, Any]
    list_name: str = ''
    # a list's item, none for a new one
    index: int | None = None


class TestResult(ApiModel):
    ok: bool
    message: str
    # a list's item tested, added if it was new and worked
    index: int | None = None


class ApiKeyIn(ApiModel):
    read_only: bool = False


class ApiKey(ApiModel):
    key: str


class DateFormats(ApiModel):
    # $Y year, $y two digits, $m month, $d day, $D day unless the 1st, $B month name, $b short name
    date_format: str
    author_date_format: str
    issue_date_format: str
    # January to December, each [name, short name]
    months: list[list[str]]


@router.get('', response_model=list[ConfigValue])
def get_values(keys: list[str] = Query(...)):
    """ Settings by name, with their kind and default """
    return settings.config_values(keys)


@router.get('/choices', response_model=Choices)
def get_choices():
    """ The choices of the settings chosen from a list """
    return settings.config_choices()


@router.get('/dates', response_model=DateFormats)
def get_date_formats():
    """ How the pages show dates, as Settings, UI says: a book's and others, an author's born and
    died, an issue's; and the months' names and short names in the date language """
    return settings.date_formats()


@router.put('', response_model=Saved)
def save(change: ConfigChange, request: Request):
    """ Change settings and save them. messages says what wasn't changed, and why """
    return {'messages': settings.save_values(change.values, keep_token=request.cookies.get(SESSION_COOKIE))}


@router.post('/reset', response_model=Saved)
def reset(which: ConfigKeys):
    """ Put settings back to their defaults, as for a download client or notifier taken out """
    settings.reset_values(which.keys)
    return {'messages': []}


@router.post('/test', response_model=TestResult)
def test(testing: ConfigTest):
    """ Test a connection with these settings. If it works they're saved, as the old settings page did,
    a new item of a list is added; if not they're put back """
    return settings.run_test(testing.test, testing.values, testing.list_name, testing.index)


@router.get('/list/{name}', response_model=list[ListItem])
def list_items(name: str):
    """ A list's items: NEWZNAB, TORZNAB, RSS, IRC, GEN or APPRISE """
    return settings.array_items(name)


@router.get('/list/{name}/schema', response_model=list[ConfigValue])
def item_schema(name: str):
    """ A new item's settings, as their defaults """
    return settings.array_schema(name)


@router.post('/list/{name}', response_model=SavedItem, status_code=201)
def add_item(name: str, change: ConfigChange):
    return settings.save_array_item(name, change.values)


@router.put('/list/{name}/{index}', response_model=SavedItem)
def change_item(name: str, index: int, change: ConfigChange):
    return settings.save_array_item(name, change.values, index)


@router.delete('/list/{name}/{index}', response_model=Saved)
def delete_item(name: str, index: int):
    settings.delete_array_item(name, index)
    return {'messages': []}


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
