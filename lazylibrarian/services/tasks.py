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

""" The scheduled tasks, like Sonarr's System, Tasks: how often each runs, when it last ran and
for how long, when it runs next, and running one now. A task's runs are in the jobs table, under
its run name, which is also the name of the thread that runs it """

import datetime
import logging
import threading

from lazylibrarian import database, scheduling
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import thread_name
from lazylibrarian.services import InvalidRequestError, NotFoundError


def _when(seconds) -> str | None:
    """ A time in the jobs table, seconds since the epoch, as an ISO date with its offset """
    if not seconds:
        return None
    return datetime.datetime.fromtimestamp(seconds).astimezone().isoformat(timespec='seconds')


def _scheduled() -> dict:
    """ The scheduler's jobs by name, the ones that are switched on """
    if not scheduling.SCHED:
        return {}
    return {job.id: job for job in scheduling.SCHED.get_jobs()}


def _why_not(scheduler) -> str:
    """ Why a task can't run, '' when it can """
    if scheduler.get_int() <= 0:
        return f"{scheduler.friendly_name} is switched off in Settings"
    if not CONFIG.scheduler_can_run(scheduler):
        if scheduler.needs_provider and not CONFIG.use_any():
            return f"{scheduler.friendly_name} needs a download provider, add one in Settings, Providers"
        return f"{scheduler.friendly_name} is switched off in Settings"
    return ''


def _running(run_name: str, row) -> bool:
    return bool(row and (row['Start'] or 0) > (row['Finish'] or 0)) or \
        any(t.name == run_name for t in threading.enumerate())


def list_tasks() -> list[dict]:
    """ Every scheduled task, by its name in Settings """
    jobs = _scheduled()
    db = database.DBConnection()
    try:
        runs = {row['Name']: row for row in db.select('SELECT Name,Start,Finish FROM jobs')}
    finally:
        db.close()
    tasks = []
    for _key, scheduler in CONFIG.get_schedulers():
        name = scheduler.get_schedule_name()
        job = jobs.get(name)
        if job:
            # the interval it really runs at, the author and series updates work theirs out
            interval = int(job.trigger.interval.total_seconds() // 60)
        else:
            hours, minutes = scheduler.get_hour_min_interval()
            interval = hours * 60 + minutes
        row = runs.get(scheduler.run_name)
        start = row['Start'] if row else None
        finish = row['Finish'] if row else None
        running = _running(scheduler.run_name, row)
        tasks.append({'name': name, 'task_name': scheduler.friendly_name, 'interval': interval,
                      'last_start_time': _when(start), 'last_execution': _when(finish),
                      'last_duration': round(finish - start, 1) if start and finish and finish >= start else None,
                      'next_execution': job.next_run_time.isoformat(timespec='seconds')
                      if job and job.next_run_time else None,
                      'is_running': running, 'disabled_reason': _why_not(scheduler)})
    return sorted(tasks, key=lambda task: task['task_name'].lower())


def _scheduler(name: str):
    for _key, scheduler in CONFIG.get_schedulers():
        if scheduler.get_schedule_name() == name:
            return scheduler
    raise NotFoundError(f'No task {name}')


def task_name(name: str) -> str:
    return _scheduler(name).friendly_name


def run(name: str) -> str:
    """ Run a task now, in this thread, and put its next run a whole interval from now, as Sonarr
    does. Returns what it said it did """
    logger = logging.getLogger(__name__)
    scheduler = _scheduler(name)
    reason = _why_not(scheduler)
    if reason:
        raise InvalidRequestError(reason)
    db = database.DBConnection()
    try:
        row = db.match('SELECT Start,Finish FROM jobs WHERE Name=?', (scheduler.run_name,))
    finally:
        db.close()
    if _running(scheduler.run_name, row):
        raise InvalidRequestError(f"{scheduler.friendly_name} is already running")
    method = scheduler.get_method()
    if not method:
        raise InvalidRequestError(f"{scheduler.friendly_name} can't be found to run")
    logger.info(f"Running {scheduler.friendly_name} now")
    previous = thread_name()
    # the task records its run under its thread's name, and its other runs check for it
    thread_name(scheduler.run_name)
    try:
        result = method()
    finally:
        thread_name(previous)
    job = _scheduled().get(name)
    if job:
        job.modify(next_run_time=datetime.datetime.now().astimezone() + job.trigger.interval)
    return result if isinstance(result, str) and result else f"{scheduler.friendly_name} completed"
