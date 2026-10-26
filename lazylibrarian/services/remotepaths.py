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

""" Remote path mappings, like Sonarr's and Radarr's. A download client on another machine or in
another container reports paths as it sees them, and a mapping says where those are here: for one
download client host, the start of a path, the client's remote path, is replaced by the local path.
A host can have several, as each media type's category can save to a different place. The most
specific remote path that fits is used, so one for a whole downloads folder can't take over from
one for its audiobooks folder """

import os
import re
from urllib.parse import urlsplit

from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import path_isdir
from lazylibrarian.services import InvalidRequestError, NotFoundError

# each download client's host setting, by the name the settings page shows
CLIENT_HOSTS = {'SABnzbd': 'SAB_HOST', 'NZBGet': 'NZBGET_HOST', 'qBittorrent': 'QBITTORRENT_HOST',
                'Transmission': 'TRANSMISSION_HOST', 'Deluge': 'DELUGE_HOST', 'rTorrent': 'RTORRENT_HOST',
                'uTorrent': 'UTORRENT_HOST', 'Synology': 'SYNOLOGY_HOST'}
# and by the download source recorded for each download
SOURCE_HOSTS = {'SABNZBD': 'SAB_HOST', 'NZBGET': 'NZBGET_HOST', 'QBITTORRENT': 'QBITTORRENT_HOST',
                'TRANSMISSION': 'TRANSMISSION_HOST', 'DELUGEWEBUI': 'DELUGE_HOST', 'DELUGERPC': 'DELUGE_HOST',
                'RTORRENT': 'RTORRENT_HOST', 'UTORRENT': 'UTORRENT_HOST', 'SYNOLOGY_TOR': 'SYNOLOGY_HOST',
                'SYNOLOGY_NZB': 'SYNOLOGY_HOST'}

FIELDS = 'rowid AS Id, Host, RemotePath, LocalPath'


def host_name(value) -> str:
    """ The host part of a download client's host setting, which can have a scheme, port or path """
    value = (value or '').strip()
    if not value:
        return ''
    if '://' not in value:
        value = f"//{value}"
    try:
        return (urlsplit(value).hostname or '').lower()
    except ValueError:
        return ''


def client_hosts() -> list[dict]:
    """ The hosts of the download clients that have one set, each with the names of the clients
    on it, for choosing one """
    hosts = {}
    for name, setting in CLIENT_HOSTS.items():
        host = host_name(CONFIG[setting])
        if host:
            hosts.setdefault(host, []).append(name)
    return [{'host': host, 'names': ', '.join(names)} for host, names in hosts.items()]


def _is_windows(path: str) -> bool:
    return bool(re.match(r'^[A-Za-z]:', path)) or path.startswith('\\\\')


def _names(path: str) -> list[str]:
    """ The folder names in a path, either separator. Windows paths ignore case """
    names = [name for name in re.split(r'[\\/]+', path) if name]
    return [name.lower() for name in names] if _is_windows(path) else names


def _rest_below(parent: str, path: str) -> list[str] | None:
    """ The names in path below parent, or None if path isn't parent or below it """
    if parent.startswith('/') != path.startswith('/') or _is_windows(parent) != _is_windows(path):
        return None
    above, names = _names(parent), _names(path)
    if names[:len(above)] != above:
        return None
    # keep the case the client gave the rest of the path in
    return [name for name in re.split(r'[\\/]+', path) if name][len(above):]


def mappings() -> list[dict]:
    db = database.DBConnection()
    try:
        return [dict(row) for row in db.select(f'SELECT {FIELDS} FROM remotepathmappings ORDER BY Host, RemotePath')]
    finally:
        db.close()


def remote_to_local(host: str, path):
    """ Where a path the client on host reported is here, the path unchanged without a mapping """
    if not path:
        return path
    host = host_name(host)
    best = None
    for mapping in mappings():
        if mapping['Host'] != host:
            continue
        rest = _rest_below(mapping['RemotePath'], path)
        if rest is not None and (best is None or len(_names(mapping['RemotePath'])) > best[0]):
            best = (len(_names(mapping['RemotePath'])), mapping, rest)
    if best is None:
        return path
    return os.path.join(best[1]['LocalPath'], *best[2])


def source_to_local(source: str, path):
    """ remote_to_local for the client a download was sent to, by its source """
    setting = SOURCE_HOSTS.get(source)
    return remote_to_local(CONFIG[setting], path) if setting else path


def get_mapping(mapping_id) -> dict:
    db = database.DBConnection()
    try:
        row = db.match(f'SELECT {FIELDS} FROM remotepathmappings WHERE rowid=?', (mapping_id,))
    finally:
        db.close()
    if not row:
        raise NotFoundError('No such remote path mapping')
    return dict(row)


def _checked(host, remote, local, mapping_id=None) -> tuple[str, str, str]:
    """ The values to store, or InvalidRequestError, with Sonarr's rules: a host, a remote path,
    a full local path that exists here, and only one mapping for each host and remote path """
    host = host_name(host)
    remote = (remote or '').strip()
    local = (local or '').strip()
    if not host:
        raise InvalidRequestError('Choose the download client host')
    if not remote:
        raise InvalidRequestError('Enter the remote path, as the download client reports it')
    if not local or not os.path.isabs(local):
        raise InvalidRequestError('Enter the local path as a full path')
    if not path_isdir(local):
        raise InvalidRequestError(f'Local path [{local}] does not exist')
    for mapping in mappings():
        if mapping['Id'] != mapping_id and mapping['Host'] == host and \
                _names(mapping['RemotePath']) == _names(remote):
            raise InvalidRequestError('There is already a mapping for that host and remote path')
    return host, remote, local


def add_mapping(host, remote, local) -> dict:
    host, remote, local = _checked(host, remote, local)
    db = database.DBConnection()
    try:
        db.action('INSERT INTO remotepathmappings (Host, RemotePath, LocalPath) VALUES (?, ?, ?)',
                  (host, remote, local))
        mapping_id = db.match('SELECT last_insert_rowid() AS Id')['Id']
    finally:
        db.close()
    return get_mapping(mapping_id)


def update_mapping(mapping_id, host, remote, local) -> dict:
    get_mapping(mapping_id)
    host, remote, local = _checked(host, remote, local, mapping_id=int(mapping_id))
    db = database.DBConnection()
    try:
        db.action('UPDATE remotepathmappings SET Host=?, RemotePath=?, LocalPath=? WHERE rowid=?',
                  (host, remote, local, mapping_id))
    finally:
        db.close()
    return get_mapping(mapping_id)


def delete_mapping(mapping_id):
    get_mapping(mapping_id)
    db = database.DBConnection()
    try:
        db.action('DELETE FROM remotepathmappings WHERE rowid=?', (mapping_id,))
    finally:
        db.close()
