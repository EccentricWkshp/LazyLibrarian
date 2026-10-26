#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test live updates: services/events.py, the database watcher, commands publishing themselves and
#   the /api/v1/events stream

import asyncio
import json
import threading
import time
from unittest import mock

from lazylibrarian.apiv1 import events as events_api
from lazylibrarian.database import DBConnection
from lazylibrarian.services import commands, events
from unittests.unittesthelpers import LLTestCaseWithStartup


async def _next(queue, timeout=10):
    return await asyncio.wait_for(queue.get(), timeout)


class EventsTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(events, 'WATCH', 0.05)
        patch.start()
        self.addCleanup(patch.stop)

    def listen(self, test):
        """ Run test(queue) with a subscription on a loop of its own """
        async def run():
            loop = asyncio.get_running_loop()
            queue = events.subscribe(loop)
            try:
                return await test(queue)
            finally:
                events.unsubscribe(loop, queue)
        return asyncio.run(run())

    def test_publish_from_any_thread(self):
        async def test(queue):
            threading.Thread(target=events.publish, args=('changed', {'keys': ['queue']})).start()
            return await _next(queue)
        self.assertEqual(self.listen(test), ('changed', {'keys': ['queue']}))

    def test_close_ends_the_streams(self):
        async def test(queue):
            events.close()
            return await _next(queue)
        self.assertIsNone(self.listen(test))

    def test_database_changes(self):
        with DBConnection() as db:
            db.action("DELETE FROM wanted")

        async def test(queue):
            await asyncio.sleep(0.3)  # the watcher has looked once

            def change():
                with DBConnection() as db:
                    db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,Status,AuxInfo) VALUES "
                              "('ev1','http://x/ev1','Event Book','Snatched','eBook')")
            threading.Thread(target=change).start()
            while True:
                name, body = await _next(queue)
                if name == 'changed':
                    return body
        body = self.listen(test)
        self.assertIn('queue', body['keys'])
        self.assertIn('history', body['keys'])
        self.assertNotIn('blocklist', body['keys'])
        for _ in range(100):
            if events._watcher is None:
                break
            time.sleep(0.05)
        self.assertIsNone(events._watcher, 'It stops watching when nobody listens')

    def test_commands_say_how_they_go(self):
        async def test(queue):
            command = await asyncio.to_thread(commands.start, 'ClearBlocklist', {})
            seen = []
            while not seen or seen[-1]['status'] not in ('completed', 'failed'):
                name, body = await _next(queue)
                if name == 'command' and body['id'] == command['id']:
                    seen.append(body)
            return seen
        seen = self.listen(test)
        self.assertEqual([body['status'] for body in seen], ['queued', 'started', 'completed'])
        self.assertTrue(seen[-1]['message'].startswith('Cleared'))

    def test_the_stream(self):
        command = {'id': 1, 'name': 'ClearBlocklist', 'title': 'Clear Blocklist', 'status': 'completed',
                   'message': 'Cleared 0 releases', 'queued': 'q', 'started': 's', 'ended': 'e', 'result': None}

        async def run():
            loop = asyncio.get_running_loop()
            queue = events.subscribe(loop)
            request = mock.Mock(is_disconnected=mock.AsyncMock(return_value=False))
            stream = events_api._stream(request, queue, loop)
            first = await anext(stream)
            events.publish('command', command)
            message = await anext(stream)
            events.close()
            rest = [part async for part in stream]
            return first, message, rest
        first, message, rest = asyncio.run(run())
        self.assertEqual(first, 'retry: 5000\n\n')
        name, data = message.split('\n')[:2]
        self.assertEqual(name, 'event: command')
        self.assertEqual(json.loads(data.removeprefix('data: ')), command, 'As /command shows it')
        self.assertEqual(rest, [], 'Closed, it ends')
