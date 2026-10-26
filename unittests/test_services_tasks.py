#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test System, Tasks (services/tasks.py) and running a task with the RunTask command

import datetime
import time
from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.formatter import thread_name
from lazylibrarian.services import InvalidRequestError, NotFoundError, commands, tasks
from unittests.unittesthelpers import LLTestCaseWithStartup


class TasksTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        saved = CONFIG.get_int('VERSIONCHECK_INTERVAL')
        self.addCleanup(CONFIG.set_int, 'VERSIONCHECK_INTERVAL', saved)
        CONFIG.set_int('VERSIONCHECK_INTERVAL', 24)
        with DBConnection() as db:
            db.action("DELETE FROM jobs")

    def scheduler(self, name='check_for_updates'):
        return tasks._scheduler(name)

    def test_list(self):
        with DBConnection() as db:
            db.action("INSERT INTO jobs (Name, Start, Finish) VALUES ('VERSIONCHECK', ?, ?)",
                      (time.time() - 70, time.time() - 60))
        found = {task['name']: task for task in tasks.list_tasks()}
        self.assertIn('search_book', found)
        check = found['check_for_updates']
        self.assertEqual((check['task_name'], check['interval'], check['last_duration'], check['is_running']),
                         ('Check for updates', 24 * 60, 10.0, False))
        self.assertTrue(check['last_execution'], 'When it last ran')
        self.assertEqual(check['disabled_reason'], '')
        names = [task['task_name'].lower() for task in found.values()]
        self.assertEqual(names, sorted(names))

        CONFIG.set_int('VERSIONCHECK_INTERVAL', 0)
        check = next(task for task in tasks.list_tasks() if task['name'] == 'check_for_updates')
        self.assertEqual(check['disabled_reason'], 'Check for updates is switched off in Settings')

    def test_run(self):
        ran = []

        def task():
            ran.append(thread_name())
            return 'Checked, up to date'

        job = mock.Mock(**{'trigger.interval': datetime.timedelta(hours=24)})
        with mock.patch.object(self.scheduler(), 'get_method', return_value=task), \
                mock.patch.object(tasks, '_scheduled', return_value={'check_for_updates': job}):
            self.assertEqual(tasks.run('check_for_updates'), 'Checked, up to date')
        self.assertEqual(ran, ['VERSIONCHECK'], 'In a thread of its name, which it records its run under')
        self.assertNotEqual(thread_name(), 'VERSIONCHECK', 'And named back')
        next_run = job.modify.call_args.kwargs['next_run_time']
        self.assertAlmostEqual((next_run - datetime.datetime.now().astimezone()).total_seconds(), 24 * 3600, delta=60,
                               msg='Its next run a whole interval from now, as Sonarr does')

    def test_not_run(self):
        with self.assertRaises(NotFoundError):
            tasks.run('nosuch')
        with DBConnection() as db:
            db.action("INSERT INTO jobs (Name, Start, Finish) VALUES ('VERSIONCHECK', ?, 0)", (time.time(),))
        with self.assertRaises(InvalidRequestError) as cm:
            tasks.run('check_for_updates')
        self.assertEqual(str(cm.exception), 'Check for updates is already running')
        CONFIG.set_int('VERSIONCHECK_INTERVAL', 0)
        with self.assertRaises(InvalidRequestError):
            tasks.run('check_for_updates')

    def test_the_command(self):
        with mock.patch.object(self.scheduler(), 'get_method', return_value=lambda: None), \
                mock.patch.object(tasks, '_scheduled', return_value={}):
            command = commands.start('RunTask', {'task': 'check_for_updates'})
            self.assertEqual(command['title'], 'Check for updates')
            for _ in range(100):
                command = commands.get(command['id'])
                if command['status'] in ('completed', 'failed'):
                    break
                time.sleep(0.05)
        self.assertEqual((command['status'], command['message']), ('completed', 'Check for updates completed'))
        with self.assertRaises(NotFoundError):
            commands.start('RunTask', {'task': 'nosuch'})
