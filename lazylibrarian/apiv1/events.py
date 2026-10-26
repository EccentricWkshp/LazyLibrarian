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

""" /api/v1/events, live updates as server-sent events, like Sonarr's SignalR messages """

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from lazylibrarian.apiv1.command import Command
from lazylibrarian.services import events

router = APIRouter(tags=['Events'])


def _message(name: str, body: dict) -> str:
    if name == 'command':
        body = Command.model_validate(body).model_dump(mode='json', by_alias=True)
    return f"event: {name}\ndata: {json.dumps(body)}\n\n"


async def _stream(request: Request, queue: asyncio.Queue, loop):
    try:
        # how long a browser waits before trying again when the stream drops, in milliseconds
        yield 'retry: 5000\n\n'
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), events.HEARTBEAT)
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ': still here\n\n'
                continue
            if message is None:  # LazyLibrarian is stopping
                return
            yield _message(*message)
    finally:
        events.unsubscribe(loop, queue)


@router.get('/events')
async def stream(request: Request):
    """ A text/event-stream that stays open. 'command' is a command as /command shows it, whenever
    it starts, says how it is going or ends. 'changed' has keys, which of queue, history,
    blocklist, wanted and tasks changed, to ask for again """
    loop = asyncio.get_running_loop()
    queue = events.subscribe(loop)
    return StreamingResponse(_stream(request, queue, loop), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
