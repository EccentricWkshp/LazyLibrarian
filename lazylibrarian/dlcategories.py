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

""" The category (or label) each download client files LazyLibrarian's downloads under, one per
media type. Separate categories let the client save eBooks, AudioBooks, magazines and comics to
different places, for whatever imports each of them, and tell our downloads from anyone else's """

from lazylibrarian.config2 import CONFIG
from lazylibrarian.configdefs import CATEGORY_SUFFIXES, CATEGORY_UNSET, DOWNLOAD_CATEGORIES


def category_setting(client: str, library: str = 'eBook') -> str:
    """ The name of the client's category setting for a library (eBook, AudioBook, magazine, comic),
    or '' for a client without categories. Both Deluge connections share the DELUGE settings """
    base = DOWNLOAD_CATEGORIES.get('DELUGE' if client.startswith('DELUGE') else client)
    if not base:
        return ''
    return f"{base}{CATEGORY_SUFFIXES.get((library or 'eBook').lower(), '')}"


def download_category(client: str, library: str = 'eBook') -> str:
    """ The category to file a download for this library under, '' for none """
    setting = category_setting(client, library)
    if not setting:
        return ''
    value = CONFIG.get_str(setting)
    if value == CATEGORY_UNSET:
        # loading config.ini gives every type its value, this is for a config that wasn't loaded
        CONFIG.fixup_download_categories()
        value = CONFIG.get_str(setting)
    return value


def download_categories(client: str) -> set[str]:
    """ Every category we file the client's downloads under, leaving out none at all """
    return {download_category(client, library) for library in CATEGORY_SUFFIXES} - {''}
