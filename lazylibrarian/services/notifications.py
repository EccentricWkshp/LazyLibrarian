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

""" Connections, like Sonarr's Settings, Connect: webhooks, each sent the events it wants as JSON,
shaped as Readarr's. A download's events, grabbed, imported, failed or blocked, are queued by the
triggers on the wanted table (dbupgrade.NOTIFY_TRIGGERS), however they came about, so they are
sent after a restart as well. Health issues come from checking every few minutes, the ones already
told of are kept in appstate, as is the version, which tells of an update.

One thread sends them, so a slow webhook holds nothing else up. A webhook that can't be reached is
shown in System, Status until it can be, as Sonarr does; its events aren't sent again """

import contextlib
import json
import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from lazylibrarian import database, quality
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import plural
from lazylibrarian.services import InvalidRequestError, NotFoundError, history, profiles

IMPLEMENTATIONS = ('Webhook',)
METHODS = ('POST', 'PUT')
# each trigger: its column, its name in the API
TRIGGERS = {'OnGrab': 'on_grab', 'OnDownload': 'on_download', 'OnUpgrade': 'on_upgrade',
            'OnDownloadFailure': 'on_download_failure',
            'OnManualInteractionRequired': 'on_manual_interaction_required', 'OnHealthIssue': 'on_health_issue',
            'IncludeHealthWarnings': 'include_health_warnings', 'OnHealthRestored': 'on_health_restored',
            'OnApplicationUpdate': 'on_application_update'}
EVENT_TRIGGERS = {'DownloadFailure': 'on_download_failure', 'ManualInteractionRequired': 'on_manual_interaction_required',
                  'ApplicationUpdate': 'on_application_update'}
NOW = "datetime('now','localtime')"
# a password is never sent back, a webhook saved with this keeps the one it has
MASK = '********'
INSTANCE = 'LazyLibrarian'
# seconds to wait for a webhook
TIMEOUT = 20
# seconds between looks for events to send, and between health checks, the first a while after starting
POLL = 5
HEALTH_EVERY = 900
HEALTH_FIRST = 300
# an event that couldn't be sent for a day is too late, sent ones are kept a while, an import looks
# up whether its grab was an upgrade
STALE_HOURS = 24
KEEP_DAYS = 30

_stop = threading.Event()
_wake = threading.Event()
_thread: threading.Thread | None = None
# NotificationID: (name, why) of the webhooks whose last send failed
_failures: dict[int, tuple[str, str]] = {}
_failures_lock = threading.Lock()


# --- the webhooks


def _definition(row, masked: bool = True) -> dict:
    settings = json.loads(row['Settings'] or '{}')
    if masked and settings.get('password'):
        settings['password'] = MASK
    found = {'id': row['NotificationID'], 'name': row['Name'], 'implementation': row['Implementation'],
             'settings': {'url': settings.get('url', ''), 'method': settings.get('method', 'POST'),
                          'username': settings.get('username', ''), 'password': settings.get('password', ''),
                          'headers': settings.get('headers', [])}}
    for column, key in TRIGGERS.items():
        found[key] = bool(row[column])
    return found


def list_notifications() -> list[dict]:
    db = database.DBConnection()
    try:
        rows = db.select('SELECT * FROM notifications ORDER BY Name COLLATE NOCASE')
    finally:
        db.close()
    return [_definition(row) for row in rows]


def _row(db, notification_id):
    row = db.match('SELECT * FROM notifications WHERE NotificationID=?', (notification_id,))
    if not row:
        raise NotFoundError(f'No connection {notification_id}')
    return row


def get(notification_id) -> dict:
    db = database.DBConnection()
    try:
        return _definition(_row(db, notification_id))
    finally:
        db.close()


def schema() -> list[dict]:
    """ A new connection of each kind to fill in """
    found = {'id': 0, 'name': '', 'implementation': 'Webhook',
             'settings': {'url': '', 'method': 'POST', 'username': '', 'password': '', 'headers': []}}
    found.update({key: key in ('on_grab', 'on_download', 'on_upgrade', 'on_download_failure',
                               'on_manual_interaction_required') for key in TRIGGERS.values()})
    return [found]


def _checked(definition: dict, stored: dict | None = None) -> dict:
    """ A connection to save or test: a name, a web address, POST or PUT, headers with names. The
    password masked keeps the stored one """
    name = (definition.get('name') or '').strip()
    if not name:
        raise InvalidRequestError('A connection needs a name')
    implementation = definition.get('implementation') or 'Webhook'
    if implementation not in IMPLEMENTATIONS:
        raise InvalidRequestError(f"The kind is one of {', '.join(IMPLEMENTATIONS)}")
    settings = definition.get('settings') or {}
    url = (settings.get('url') or '').strip()
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        raise InvalidRequestError('The URL has to be a web address, starting http:// or https://')
    method = (settings.get('method') or 'POST').upper()
    if method not in METHODS:
        raise InvalidRequestError(f"The method is one of {', '.join(METHODS)}")
    headers = []
    for header in settings.get('headers') or []:
        key, value = (header.get('key') or '').strip(), str(header.get('value') or '')
        if not key and not value:
            continue
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
            raise InvalidRequestError(f"[{key}] isn't a header name")
        if '\r' in value or '\n' in value:
            raise InvalidRequestError(f"The {key} header has to be one line")
        headers.append({'key': key, 'value': value})
    password = settings.get('password') or ''
    if password == MASK:
        password = (stored or {}).get('settings', {}).get('password', '')
    checked = {'name': name, 'implementation': implementation,
               'settings': {'url': url, 'method': method, 'username': (settings.get('username') or '').strip(),
                            'password': password, 'headers': headers}}
    for key in TRIGGERS.values():
        checked[key] = bool(definition.get(key))
    return checked


def _stored(db, notification_id) -> dict | None:
    return _definition(_row(db, notification_id), masked=False) if notification_id else None


def save(definition: dict, notification_id=None) -> dict:
    """ Add a connection, or change one. Returns it as saved """
    db = database.DBConnection()
    try:
        checked = _checked(definition, _stored(db, notification_id))
        same_name = db.match('SELECT NotificationID FROM notifications WHERE Name=?', (checked['name'],))
        if same_name and same_name['NotificationID'] != (int(notification_id) if notification_id else None):
            raise InvalidRequestError(f"There is a connection called {checked['name']} already")
        columns = {'Name': checked['name'], 'Implementation': checked['implementation'],
                   'Settings': json.dumps(checked['settings'])}
        columns.update({column: int(checked[key]) for column, key in TRIGGERS.items()})
        if notification_id:
            db.action(f"UPDATE notifications SET {', '.join(f'{c}=?' for c in columns)} WHERE NotificationID=?",
                      (*columns.values(), notification_id))
        else:
            db.action(f"INSERT INTO notifications ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                      tuple(columns.values()))
            notification_id = db.match('SELECT NotificationID FROM notifications WHERE Name=?',
                                       (checked['name'],))['NotificationID']
    finally:
        db.close()
    _clear_failure(int(notification_id))
    logging.getLogger(__name__).info(f"Saved the connection {checked['name']}")
    return get(notification_id)


def delete(notification_id):
    db = database.DBConnection()
    try:
        row = _row(db, notification_id)
        db.action('DELETE FROM notifications WHERE NotificationID=?', (notification_id,))
    finally:
        db.close()
    _clear_failure(int(notification_id))
    logging.getLogger(__name__).info(f"Deleted the connection {row['Name']}")


def test(definition: dict, notification_id=None):
    """ Send a test event to a connection as it is filled in. Raises InvalidRequestError with why
    it couldn't be sent """
    db = database.DBConnection()
    try:
        checked = _checked(definition, _stored(db, notification_id) if notification_id else None)
    finally:
        db.close()
    why = _send(checked, _test_payload())
    if why:
        raise InvalidRequestError(f'Unable to send the test notification: {why}')


# --- sending


def _send(notification: dict, payload: dict) -> str:
    """ Send a payload to a webhook. Returns why it failed, nothing when it was sent """
    settings = notification['settings']
    headers = {'Content-Type': 'application/json',
               'User-Agent': f"LazyLibrarian/{(CONFIG['CURRENT_VERSION'] or 'unknown')[:8]}"}
    headers.update({header['key']: header['value'] for header in settings.get('headers') or []})
    auth = (settings['username'], settings['password']) if settings.get('username') or settings.get('password') \
        else None
    verify = CONFIG['SSL_CERTS'] if CONFIG['SSL_CERTS'] else CONFIG.get_bool('SSL_VERIFY')
    try:
        response = requests.request(settings.get('method') or 'POST', settings['url'], data=json.dumps(payload),
                                    headers=headers, auth=auth, timeout=TIMEOUT, verify=verify)
    except requests.RequestException as e:
        return f'{type(e).__name__}: {e}'
    if response.status_code >= 400:
        return f'{response.status_code} {response.reason}'.strip()
    return ''


def _deliver(notification: dict, payload: dict):
    logger = logging.getLogger(__name__)
    why = _send(notification, payload)
    if why:
        logger.warning(f"Unable to send {payload['eventType']} to the connection {notification['name']}: {why}")
        with _failures_lock:
            _failures[notification['id']] = (notification['name'], why)
    else:
        logger.debug(f"Sent {payload['eventType']} to the connection {notification['name']}")
        _clear_failure(notification['id'])


def _clear_failure(notification_id: int):
    with _failures_lock:
        _failures.pop(notification_id, None)


def failures() -> list[tuple[str, str]]:
    """ (name, why) of each connection whose last send failed """
    with _failures_lock:
        return sorted(_failures.values())


def _wanted(notification: dict, event: dict) -> bool:
    kind = event['Event']
    if kind == 'Grab':
        return notification['on_grab']
    if kind == 'Download':
        return notification['on_upgrade'] if event['Upgrade'] else notification['on_download']
    if kind in ('Health', 'HealthRestored'):
        level = json.loads(event['Data'] or '{}').get('level')
        on = notification['on_health_issue'] if kind == 'Health' else notification['on_health_restored']
        return on and (level == 'error' or (level == 'warning' and notification['include_health_warnings']))
    return notification.get(EVENT_TRIGGERS.get(kind, ''), False)


def deliver_pending():
    """ Send the events waiting, to each connection that wants them """
    db = database.DBConnection()
    try:
        events = db.select('SELECT * FROM notificationevents WHERE Sent IS NULL ORDER BY EventID LIMIT 50')
        if not events:
            return
        connections = [_definition(row, masked=False) for row in db.select('SELECT * FROM notifications')]
        late = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - STALE_HOURS * 3600))
        for event in events:
            targets = [n for n in connections if _wanted(n, event)]
            if targets and (event['Created'] or '') >= late:
                payload = _payload(db, event)
                if payload:
                    for notification in targets:
                        _deliver(notification, payload)
            db.action(f"UPDATE notificationevents SET Sent={NOW} WHERE EventID=?", (event['EventID'],))
        db.action(f"DELETE FROM notificationevents WHERE Sent<datetime('now','localtime','-{KEEP_DAYS} days')")
    finally:
        db.close()


def wants(*columns: str, db=None) -> bool:
    """ Whether any connection wants one of these events """
    own = db is None
    db = db or database.DBConnection()
    try:
        return bool(db.match(f"SELECT 1 FROM notifications WHERE {' OR '.join(columns)} LIMIT 1"))
    finally:
        if own:
            db.close()


def enqueue(event: str, data: dict, db=None):
    """ Queue an event that isn't a download's to send """
    own = db is None
    db = db or database.DBConnection()
    try:
        db.action(f"INSERT INTO notificationevents (Event, Data, Created) VALUES (?, ?, {NOW})",
                  (event, json.dumps(data)))
    finally:
        if own:
            db.close()
    _wake.set()


# --- payloads, as Readarr's webhooks send them


def _media(db, book_id, auxinfo) -> dict:
    """ What an event is about: the author and book, or the magazine or comic and its issue """
    kind = history.media_type(auxinfo)
    found = {'mediaType': kind}
    if kind in ('ebook', 'audiobook'):
        book = db.match('SELECT books.*,AuthorName FROM books LEFT JOIN authors ON books.AuthorID=authors.AuthorID '
                        'WHERE BookID=?', (book_id,))
        if not book:
            found['books'] = [{'id': book_id, 'title': book_id}]
            return found
        found['author'] = {'id': book['AuthorID'], 'name': book['AuthorName'] or ''}
        found['books'] = [{'id': book['BookID'], 'title': book['BookName'] or '', 'isbn': book['BookIsbn'] or '',
                           'releaseDate': book['BookDate'] or '', 'series': book['SeriesDisplay'] or ''}]
        if kind == 'audiobook':
            found['books'][0]['narrator'] = book['Narrator'] or ''
    elif kind == 'magazine':
        found['magazine'] = {'title': book_id}
        found['issues'] = [{'issueDate': auxinfo}]
    else:
        comic_id, issue = (book_id or '').split('_', 1) if '_' in (book_id or '') else (book_id, '')
        comic = db.match('SELECT Title FROM comics WHERE ComicID=?', (comic_id,))
        found['comic'] = {'id': comic_id, 'title': comic['Title'] if comic else comic_id}
        found['issues'] = [{'issueNumber': issue}]
    return found


def _release(db, wanted, kind: str) -> dict:
    title = wanted['NZBtitle'] or ''
    profile = profiles.for_media(kind, db) if kind in quality.MEDIA_TYPES else None
    key = profiles.release_quality(profile, quality.of_release(title, kind)) if profile else quality.UNKNOWN
    return {'releaseTitle': title, 'indexer': history.indexer_name(wanted['NZBprov']),
            'size': history.size_bytes(wanted['NZBsize']), 'quality': quality.name(key),
            'protocol': history.PROTOCOLS.get(wanted['NZBmode'] or '', wanted['NZBmode'] or '')}


def _files(db, found: dict, book_id, auxinfo) -> dict:
    """ The files an import brought: the book's, or the issue's """
    kind = found['mediaType']
    path = ''
    if kind in ('ebook', 'audiobook'):
        row = db.match('SELECT BookFile,AudioFile FROM books WHERE BookID=?', (book_id,))
        path = (row['AudioFile'] if kind == 'audiobook' else row['BookFile']) if row else ''
    elif kind == 'magazine':
        row = db.match('SELECT IssueFile FROM issues WHERE Title=? AND IssueDate=?', (book_id, auxinfo))
        path = row['IssueFile'] if row else ''
    elif '_' in (book_id or ''):
        comic_id, issue = book_id.split('_', 1)
        row = db.match('SELECT IssueFile FROM comicissues WHERE ComicID=? AND IssueID=?', (comic_id, issue))
        path = row['IssueFile'] if row else ''
    if not path:
        return {}
    size = 0
    with contextlib.suppress(OSError):
        size = os.path.getsize(path)
    files = [{'path': path, 'quality': quality.name(quality.of_file(path, kind)), 'size': size}]
    return {'bookFiles' if kind in ('ebook', 'audiobook') else 'issueFiles': files}


def _payload(db, event) -> dict | None:
    """ The JSON for an event, from what the database has now """
    kind = event['Event']
    payload = {'eventType': kind, 'instanceName': INSTANCE}
    data = json.loads(event['Data'] or '{}')
    if kind in ('Health', 'HealthRestored'):
        payload.update(level=data.get('level', ''), message=data.get('message', ''), type=data.get('type', ''))
        return payload
    if kind == 'ApplicationUpdate':
        payload.update(message=f"LazyLibrarian updated from {data.get('previousVersion')} to "
                               f"{data.get('newVersion')}", **data)
        return payload
    wanted = db.match('SELECT * FROM wanted WHERE rowid=?', (event['WantedID'],)) if event['WantedID'] else None
    if not wanted or wanted['NZBurl'] != event['NZBurl']:
        wanted = db.match('SELECT * FROM wanted WHERE NZBurl=? AND BookID IS ?', (event['NZBurl'], event['BookID']))
    if not wanted:
        return None
    # a manual import's row is made for it, nothing was grabbed
    if kind == 'Grab' and wanted['Source'] == 'MANUAL':
        return None
    payload.update(_media(db, event['BookID'], event['AuxInfo']))
    payload['release'] = _release(db, wanted, payload['mediaType'])
    payload.update(downloadClient=history.client_name(wanted['Source']), downloadId=wanted['DownloadID'] or '')
    if kind == 'Download':
        payload.update(_files(db, payload, event['BookID'], event['AuxInfo']), isUpgrade=bool(event['Upgrade']))
    elif kind == 'DownloadFailure':
        payload['message'] = event['Message'] or ''
    elif kind == 'ManualInteractionRequired':
        why = (event['Message'] or '').removeprefix('Import blocked:').strip()
        payload.update(message=why, downloadStatus='warning',
                       downloadStatusMessages=[{'title': wanted['NZBtitle'] or '', 'messages': [why]}])
    return payload


def _test_payload() -> dict:
    return {'eventType': 'Test', 'instanceName': INSTANCE, 'mediaType': 'ebook',
            'author': {'id': '1', 'name': 'Test Author'},
            'books': [{'id': '1', 'title': 'Test Title', 'isbn': '', 'releaseDate': '', 'series': ''}],
            'release': {'releaseTitle': 'Test Author - Test Title (epub)', 'indexer': 'Test Indexer', 'size': 0,
                        'quality': 'EPUB', 'protocol': 'usenet'}}


# --- health and updates


def _state(db, key: str) -> str:
    row = db.match('SELECT Value FROM appstate WHERE Key=?', (key,))
    return row['Value'] if row else ''


def _set_state(db, key: str, value: str):
    db.action('INSERT OR REPLACE INTO appstate (Key, Value) VALUES (?, ?)', (key, value))


def _health_key(check: dict) -> str:
    """ The same issue says how many it's about, the count changing makes it no new issue """
    return f"{check['source']}:{re.sub(r'[0-9]+', '#', check['message'])}"


def check_health():
    """ Tell of each health issue that is new, an error or a warning, and each one that has gone """
    from lazylibrarian.services import health  # noqa: PLC0415, health shows this module's failures
    db = database.DBConnection()
    try:
        if not wants('OnHealthIssue', 'OnHealthRestored', db=db):
            return
        now = {_health_key(check): {'level': check['type'], 'message': check['message'], 'type': check['source']}
               for check in health.checks() if check['type'] in ('error', 'warning')}
        try:
            before = json.loads(_state(db, 'HealthIssues') or '{}')
        except ValueError:
            before = {}
        for key, issue in now.items():
            if key not in before:
                enqueue('Health', issue, db)
        for key, issue in before.items():
            if key not in now:
                enqueue('HealthRestored', issue, db)
        _set_state(db, 'HealthIssues', json.dumps(now))
    finally:
        db.close()


def check_version():
    """ Tell of an update, a version that isn't the one there was last time """
    current = CONFIG['CURRENT_VERSION']
    if not current:
        return
    db = database.DBConnection()
    try:
        previous = _state(db, 'Version')
        if previous and previous != current and wants('OnApplicationUpdate', db=db):
            enqueue('ApplicationUpdate', {'previousVersion': previous, 'newVersion': current}, db)
        if previous != current:
            _set_state(db, 'Version', current)
    finally:
        db.close()


def health_checks() -> list[dict]:
    """ For System, Status: the connections that can't be sent to """
    failed = failures()
    if not failed:
        return []
    names = ', '.join(name for name, _why in failed)
    return [{'source': 'NotificationStatusCheck', 'type': 'warning',
             'message': f"{plural(len(failed), 'Notification')} unavailable due to failures: {names}",
             'link': '/settings/connect'}]


# --- the sending thread


def _run():
    logger = logging.getLogger(__name__)
    next_health = time.monotonic() + HEALTH_FIRST
    while not _stop.is_set():
        try:
            deliver_pending()
            if time.monotonic() >= next_health:
                next_health = time.monotonic() + HEALTH_EVERY
                check_health()
        except Exception as e:
            logger.error(f'Notifications: {type(e).__name__} {e}')
        _wake.wait(POLL)
        _wake.clear()


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    try:
        check_version()
    except Exception as e:
        logging.getLogger(__name__).error(f'Notifications: {type(e).__name__} {e}')
    _stop.clear()
    _thread = threading.Thread(target=_run, name='NOTIFICATIONS', daemon=True)
    _thread.start()


def stop():
    _stop.set()
    _wake.set()
    if _thread and _thread.is_alive() and _thread is not threading.current_thread():
        _thread.join(timeout=5)
