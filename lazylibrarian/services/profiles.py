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

""" Quality profiles, like Sonarr's and Readarr's: which qualities (formats) are wanted for eBooks
or audiobooks, best first, and whether to keep looking for a better one until the cutoff, the
quality that is good enough. Each media type has a default profile.

The search uses them to turn down a release whose quality isn't wanted, or is worse than the file
there is, to choose between the releases it would take, best quality first, and to look for
upgrades of books whose file is below the cutoff (Wanted, Cutoff Unmet) """

import json
import logging

from lazylibrarian import database, quality
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import get_list
from lazylibrarian.services import InvalidRequestError, NotFoundError

DEFAULT_SETTINGS = {'ebook': 'EBOOK_PROFILE', 'audiobook': 'AUDIO_PROFILE', 'magazine': 'MAG_PROFILE',
                    'comic': 'COMIC_PROFILE'}
LIBRARIES = {'eBook': 'ebook', 'AudioBook': 'audiobook', 'magazine': 'magazine', 'comic': 'comic'}
# each media type's default profiles: the one that follows its types setting, and one that prefers a
# format and upgrades until it
DEFAULTS = (('ebook', 'Any eBook', 'Prefer EPUB', 'epub'), ('audiobook', 'Any Audiobook', 'Prefer M4B', 'm4b'),
            ('magazine', 'Any Magazine', 'Prefer PDF', 'pdf'), ('comic', 'Any Comic', 'Prefer CBZ', 'cbz'))


def _items(order: list[str], allowed: set[str], media_type: str) -> list[dict]:
    """ Every quality of the media type, those in order first, the rest after, not wanted """
    rest = [q for q in quality.qualities(media_type) if q not in order]
    return [{'quality': q, 'allowed': q in allowed} for q in [*order, *rest]]


def default_profiles() -> list[dict]:
    """ The profiles a new database starts with. The Any ones keep the order of the types settings,
    as the search preferred them before there were profiles. A Prefer one is only there when the
    types setting has another format to upgrade from """
    found = []
    for media_type, any_name, prefer_name, prefer in DEFAULTS:
        words = quality.words(media_type)
        order = []
        for extension in get_types(media_type):
            key = words.get(extension, extension)
            if key not in order:
                order.append(key)
        # a release that doesn't say its format is likely to be a good one, more than one that says PDF
        if media_type == 'ebook' and 'pdf' in order:
            order.insert(order.index('pdf'), quality.UNKNOWN)
        else:
            order.append(quality.UNKNOWN)
        found.append({'name': any_name, 'media_type': media_type, 'items': _items(order, set(order), media_type),
                      'cutoff': order[0], 'upgrade_allowed': False})
        if len([q for q in order if q not in (quality.UNKNOWN, prefer)]) < 1:
            continue
        preferred = [prefer, *[q for q in order if q != prefer]]
        found.append({'name': prefer_name, 'media_type': media_type,
                      'items': _items(preferred, set(preferred), media_type), 'cutoff': prefer,
                      'upgrade_allowed': True})
    return found


def get_types(media_type: str) -> list[str]:
    return [t.lower() for t in get_list(CONFIG[quality.TYPE_SETTINGS[media_type]])]


def ensure_defaults(db):
    """ Add the default profiles of a media type that has none """
    missing = [media_type for media_type in quality.MEDIA_TYPES
               if not db.match('SELECT ProfileID FROM qualityprofiles WHERE MediaType=?', (media_type,))]
    for profile in default_profiles():
        if profile['media_type'] in missing:
            _insert(db, profile)


def _insert(db, profile: dict) -> int:
    db.action('INSERT INTO qualityprofiles (Name, MediaType, Items, Cutoff, UpgradeAllowed) VALUES (?, ?, ?, ?, ?)',
              (profile['name'], profile['media_type'], json.dumps(profile['items']), profile['cutoff'],
               int(bool(profile['upgrade_allowed']))))
    return db.match('SELECT ProfileID FROM qualityprofiles WHERE Name=?', (profile['name'],))['ProfileID']


def _profile(row) -> dict:
    """ A profile from its row, with every quality of its media type, a new type added as not wanted """
    media_type = row['MediaType']
    items = [item for item in json.loads(row['Items'] or '[]') if item.get('quality')]
    known = {item['quality'] for item in items}
    items += [{'quality': q, 'allowed': False} for q in quality.qualities(media_type) if q not in known]
    return {'id': row['ProfileID'], 'name': row['Name'], 'media_type': media_type, 'items': items,
            'cutoff': row['Cutoff'] or '', 'upgrade_allowed': bool(row['UpgradeAllowed'])}


def _default_id(db, media_type: str) -> int | None:
    wanted_id = CONFIG.get_int(DEFAULT_SETTINGS[media_type])
    if wanted_id and db.match('SELECT ProfileID FROM qualityprofiles WHERE ProfileID=? AND MediaType=?',
                              (wanted_id, media_type)):
        return wanted_id
    row = db.match('SELECT ProfileID FROM qualityprofiles WHERE MediaType=? ORDER BY ProfileID', (media_type,))
    return row['ProfileID'] if row else None


def _described(profile: dict, default_id) -> dict:
    """ A profile as the pages show it: each quality's name, whether its files are imported """
    media_type = profile['media_type']
    return {**profile, 'is_default': profile['id'] == default_id,
            'items': [{**item, 'name': quality.name(item['quality']),
                       'imported': quality.imported(media_type, item['quality'])} for item in profile['items']]}


def list_profiles() -> list[dict]:
    db = database.DBConnection()
    try:
        ensure_defaults(db)
        defaults = {media_type: _default_id(db, media_type) for media_type in quality.MEDIA_TYPES}
        rows = db.select('SELECT * FROM qualityprofiles ORDER BY MediaType DESC, ProfileID')
    finally:
        db.close()
    return [_described(profile, defaults[profile['media_type']]) for profile in map(_profile, rows)]


def get(profile_id) -> dict:
    db = database.DBConnection()
    try:
        row = db.match('SELECT * FROM qualityprofiles WHERE ProfileID=?', (profile_id,))
        if not row:
            raise NotFoundError(f'No quality profile {profile_id}')
        profile = _profile(row)
        return _described(profile, _default_id(db, profile['media_type']))
    finally:
        db.close()


def schema(media_type: str) -> dict:
    """ A new profile: every quality, the formats that are imported wanted, in the default order """
    if media_type not in quality.MEDIA_TYPES:
        raise InvalidRequestError(f"The type is one of {', '.join(quality.MEDIA_TYPES)}")
    order = quality.qualities(media_type)
    allowed = {q for q in order if quality.imported(media_type, q)}
    profile = {'id': 0, 'name': '', 'media_type': media_type, 'items': _items(order, allowed, media_type),
               'cutoff': next((q for q in order if q in allowed), ''), 'upgrade_allowed': False}
    return _described(profile, None)


def _checked(profile: dict) -> dict:
    """ A profile to save: a name, the media type's qualities each once, one wanted at least, and a
    cutoff that is wanted """
    name = (profile.get('name') or '').strip()
    if not name:
        raise InvalidRequestError('A profile needs a name')
    media_type = profile.get('media_type')
    if media_type not in quality.MEDIA_TYPES:
        raise InvalidRequestError(f"The type is one of {', '.join(quality.MEDIA_TYPES)}")
    known = quality.qualities(media_type)
    items, seen = [], set()
    for item in profile.get('items') or []:
        key = item.get('quality')
        if key in known and key not in seen:
            seen.add(key)
            items.append({'quality': key, 'allowed': bool(item.get('allowed'))})
    items += [{'quality': q, 'allowed': False} for q in known if q not in seen]
    allowed = [item['quality'] for item in items if item['allowed']]
    if not allowed:
        raise InvalidRequestError('Choose at least one quality the profile wants')
    cutoff = profile.get('cutoff') or allowed[0]
    if cutoff not in allowed:
        raise InvalidRequestError(f"The cutoff, {quality.name(cutoff)}, has to be one the profile wants")
    return {'name': name, 'media_type': media_type, 'items': items, 'cutoff': cutoff,
            'upgrade_allowed': bool(profile.get('upgrade_allowed'))}


def save(profile: dict, profile_id=None) -> dict:
    """ Add a profile, or change one (its media type stays). Returns it as saved """
    checked = _checked(profile)
    db = database.DBConnection()
    try:
        same_name = db.match('SELECT ProfileID FROM qualityprofiles WHERE Name=?', (checked['name'],))
        if same_name and same_name['ProfileID'] != (int(profile_id) if profile_id else None):
            raise InvalidRequestError(f"There is a profile called {checked['name']} already")
        if profile_id:
            row = db.match('SELECT MediaType FROM qualityprofiles WHERE ProfileID=?', (profile_id,))
            if not row:
                raise NotFoundError(f'No quality profile {profile_id}')
            if row['MediaType'] != checked['media_type']:
                raise InvalidRequestError("A profile's type can't change")
            db.action('UPDATE qualityprofiles SET Name=?, Items=?, Cutoff=?, UpgradeAllowed=? WHERE ProfileID=?',
                      (checked['name'], json.dumps(checked['items']), checked['cutoff'],
                       int(checked['upgrade_allowed']), profile_id))
        else:
            profile_id = _insert(db, checked)
    finally:
        db.close()
    logging.getLogger(__name__).info(f"Saved the quality profile {checked['name']}")
    return get(profile_id)


def delete(profile_id):
    db = database.DBConnection()
    try:
        row = db.match('SELECT Name, MediaType FROM qualityprofiles WHERE ProfileID=?', (profile_id,))
        if not row:
            raise NotFoundError(f'No quality profile {profile_id}')
        if _default_id(db, row['MediaType']) == int(profile_id):
            raise InvalidRequestError(f"{row['Name']} is the default profile, choose another default first")
        db.action('DELETE FROM qualityprofiles WHERE ProfileID=?', (profile_id,))
    finally:
        db.close()
    logging.getLogger(__name__).info(f"Deleted the quality profile {row['Name']}")


def set_default(profile_id) -> dict:
    profile = get(profile_id)
    CONFIG.set_int(DEFAULT_SETTINGS[profile['media_type']], int(profile_id))
    CONFIG.save_config_and_backup_old(section='General')
    return get(profile_id)


def for_media(media_type: str, db=None) -> dict | None:
    """ The profile a media type's searches use, its default """
    own = db is None
    db = db or database.DBConnection()
    try:
        ensure_defaults(db)
        profile_id = _default_id(db, media_type)
        row = db.match('SELECT * FROM qualityprofiles WHERE ProfileID=?', (profile_id,)) if profile_id else None
    finally:
        if own:
            db.close()
    return _profile(row) if row else None


def for_library(library: str, db=None) -> dict | None:
    """ The profile for eBook or AudioBook """
    media_type = LIBRARIES.get(library)
    return for_media(media_type, db) if media_type else None


# --- decisions


def rank(profile: dict, key: str) -> int:
    """ How good a quality is to a profile, higher is better, 0 when the profile doesn't want it """
    allowed = [item['quality'] for item in profile['items'] if item['allowed']]
    return len(allowed) - allowed.index(key) if key in allowed else 0


def release_quality(profile: dict, formats: list[str]) -> str:
    """ A release's quality from the formats its name says it has: the best of them the profile
    wants, or the first when it wants none of them. Unknown when it says none """
    if not formats:
        return quality.UNKNOWN
    return max(formats, key=lambda key: rank(profile, key)) if any(rank(profile, f) for f in formats) \
        else formats[0]


def book_quality(profile: dict, qualities: list[str]) -> str:
    """ The quality of a book in the library, the best of its formats to the profile """
    return max(qualities, key=lambda key: rank(profile, key)) if qualities else ''


def cutoff_met(profile: dict, current: str) -> bool:
    return rank(profile, current) >= rank(profile, profile['cutoff'])


def wants_upgrade(profile: dict, current: str) -> bool:
    """ Whether a book with a file of this quality is to be upgraded: the profile allows upgrades and
    the file is below the cutoff """
    return profile['upgrade_allowed'] and not cutoff_met(profile, current)
