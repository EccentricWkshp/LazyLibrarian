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

""" Commands, like Sonarr's: work that takes a while runs in the background, and the web page
asks how it is going and how it ended, with a message to show for it. They are kept in memory,
the most recent first, until LazyLibrarian restarts """

import itertools
import logging
import threading
import traceback
from collections.abc import Callable
from datetime import UTC, datetime

from lazylibrarian.formatter import plural
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    blocklist,
    manualimport,
    wanted,
)

KEEP = 100
_commands: dict[int, dict] = {}
_ids = itertools.count(1)
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def _manual_import(command: dict, body: dict) -> str:
    def progress(message):
        command['message'] = message

    results = manualimport.import_items(body.get('files') or [], progress=progress)
    command['result'] = results
    imported = sum(1 for result in results if result['imported'])
    failed = [result['message'] for result in results if not result['imported']]
    message = f"Imported {imported} of {len(results)}"
    if failed:
        message += f". {'; '.join(failed)}"
    if not imported:
        raise InvalidRequestError(message)
    return message


def _book_search(command: dict, body: dict) -> str:
    def progress(message):
        command['message'] = message

    found, message = wanted.search_books(body.get('books') or [], progress=progress)
    command['result'] = {'found': found}
    return message


def _missing_book_search(command: dict, body: dict) -> str:
    def progress(message):
        command['message'] = message

    found, message = wanted.search_books([], progress=progress)
    command['result'] = {'found': found}
    return message


def _clear_blocklist(command: dict, body: dict) -> str:
    cleared = blocklist.clear()
    command['result'] = {'cleared': cleared}
    return f"Cleared {cleared} {plural(cleared, 'release')} from the blocklist"


HANDLERS: dict[str, Callable[[dict, dict], str]] = {'ManualImport': _manual_import, 'BookSearch': _book_search,
                                                    'MissingBookSearch': _missing_book_search,
                                                    'ClearBlocklist': _clear_blocklist}


def _run(command: dict, body: dict):
    logger = logging.getLogger(__name__)
    command.update(status='started', started=_now())
    try:
        command['message'] = HANDLERS[command['name']](command, body)
        command['status'] = 'completed'
    except (InvalidRequestError, NotFoundError) as why:
        command.update(status='failed', message=str(why))
    except Exception as why:
        logger.error(f"{command['name']} failed: {traceback.format_exc()}")
        command.update(status='failed', message=f"{type(why).__name__}: {why}")
    command['ended'] = _now()


def start(name: str, body: dict) -> dict:
    """ Start a command in the background, returns it as it is now """
    if name not in HANDLERS:
        raise InvalidRequestError(f"There is no command {name}, there is {', '.join(HANDLERS)}")
    command = {'id': next(_ids), 'name': name, 'status': 'queued', 'message': '', 'queued': _now(),
               'started': None, 'ended': None, 'result': None}
    with _lock:
        _commands[command['id']] = command
        for old in sorted(_commands)[:-KEEP]:
            del _commands[old]
    threading.Thread(target=_run, args=(command, body), name=f"COMMAND-{name.upper()}", daemon=True).start()
    return dict(command)


def get(command_id) -> dict:
    with _lock:
        command = _commands.get(int(command_id))
    if not command:
        raise NotFoundError(f'No command {command_id}')
    return dict(command)


def list_commands() -> list[dict]:
    with _lock:
        return [dict(command) for command in sorted(_commands.values(), key=lambda c: -c['id'])]
