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

""" Qualities, like Sonarr's and Readarr's: for books the quality is the format, EPUB, MOBI, MP3,
M4B... A release's comes from the format words in its name, a file's from its extension, and a
release that doesn't say is Unknown. Any other type in the eBook or audiobook types settings is a
quality of its own. Quality profiles (services/profiles.py) say which are wanted, in what order """

import contextlib
import os

from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import get_list

UNKNOWN = 'unknown'
MEDIA_TYPES = ('ebook', 'audiobook', 'magazine', 'comic')
# the formats known, best first as the default order, and the words or extensions that are each
FORMATS = {
    'ebook': {'epub': ('epub', 'kepub'), 'azw3': ('azw3', 'azw', 'kfx'), 'mobi': ('mobi', 'prc'), 'pdf': ('pdf',)},
    'audiobook': {'m4b': ('m4b',), 'mp3': ('mp3',), 'flac': ('flac',), 'm4a': ('m4a', 'aac'),
                  'ogg': ('ogg', 'opus')},
    'magazine': {'pdf': ('pdf',), 'epub': ('epub',), 'cbz': ('cbz',), 'cbr': ('cbr',)},
    'comic': {'cbz': ('cbz',), 'cbr': ('cbr',), 'pdf': ('pdf',), 'epub': ('epub',)},
}
NAMES = {'epub': 'EPUB', 'azw3': 'AZW3', 'mobi': 'MOBI', 'pdf': 'PDF', 'm4b': 'M4B', 'mp3': 'MP3', 'flac': 'FLAC',
         'm4a': 'M4A', 'ogg': 'OGG', 'cbz': 'CBZ', 'cbr': 'CBR', UNKNOWN: 'Unknown'}
# the settings that say which files are imported
TYPE_SETTINGS = {'ebook': 'EBOOK_TYPE', 'audiobook': 'AUDIOBOOK_TYPE', 'magazine': 'MAG_TYPE', 'comic': 'COMIC_TYPE'}


def words(media_type: str) -> dict[str, str]:
    """ Each word or extension that means a format, to the format """
    words = {}
    for key, aliases in FORMATS[media_type].items():
        for alias in aliases:
            words[alias] = key
    for extension in get_list(CONFIG[TYPE_SETTINGS[media_type]]):
        words.setdefault(extension.lower(), extension.lower())
    return words


def qualities(media_type: str) -> list[str]:
    """ The qualities of a media type: the known formats, any other imported type, and Unknown """
    found = list(FORMATS[media_type])
    for extension in get_list(CONFIG[TYPE_SETTINGS[media_type]]):
        key = words(media_type).get(extension.lower(), extension.lower())
        if key not in found:
            found.append(key)
    return [*found, UNKNOWN]


def name(quality: str) -> str:
    return NAMES.get(quality, quality.upper())


def imported(media_type: str, quality: str) -> bool:
    """ Whether files of this quality are imported, by the eBook or audiobook types settings. A
    download that can't be imported is no use. Unknown is whatever the download turns out to be """
    if quality == UNKNOWN:
        return True
    types = {extension.lower() for extension in get_list(CONFIG[TYPE_SETTINGS[media_type]])}
    return any(alias in types for alias in FORMATS[media_type].get(quality, (quality,)))


def of_release(title: str, media_type: str) -> list[str]:
    """ The formats a release's name says it has, in the order they're named. None means Unknown """
    known = words(media_type)
    found = []
    for word in get_list(title.lower().replace('.', ' ').replace('_', ' ').replace('-', ' ')):
        key = known.get(word.strip('[]()'))
        if key and key not in found:
            found.append(key)
    return found


def of_file(path: str, media_type: str) -> str:
    """ A file's quality, from its extension """
    extension = os.path.splitext(path or '')[1].lower().lstrip('.')
    return words(media_type).get(extension, UNKNOWN) if extension else UNKNOWN


def of_book(path: str, media_type: str) -> list[str]:
    """ The qualities of a book in the library: its file's, and for an eBook the other formats
    beside it with the same name, which it is kept in as well """
    if not path:
        return []
    found = [of_file(path, media_type)]
    if media_type == 'ebook':
        folder, stem = os.path.dirname(path), os.path.splitext(os.path.basename(path))[0]
        with contextlib.suppress(OSError):
            for entry in os.listdir(folder):
                other_stem, extension = os.path.splitext(entry)
                if other_stem == stem and extension:
                    quality = of_file(entry, media_type)
                    if quality != UNKNOWN and quality not in found:
                        found.append(quality)
    return found
