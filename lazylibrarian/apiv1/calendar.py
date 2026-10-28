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

""" /api/v1/calendar, and the iCal feed at /feed/v1/calendar/LazyLibrarian.ics, like Sonarr's """

from fastapi import APIRouter, Query
from fastapi.responses import Response

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import calendar

router = APIRouter(tags=['Calendar'])
# below HTTP_ROOT beside /api/v1, with the same API key or login
feed = APIRouter(tags=['Calendar'])


class CalendarFormat(ApiModel):
    # ebook or audiobook
    format: str
    status: str
    state: str


class CalendarEntry(ApiModel):
    id: str
    # book, issue (one there is) or due (one missing or expected)
    kind: str
    # the book's or the issue's id
    item_id: str
    # yyyy-mm-dd
    date: str
    title: str
    subtitle: str
    # the author's id or the magazine's title, and the author's name or the magazine's title
    parent_id: str
    parent: str
    series: str
    image: str
    formats: list[CalendarFormat]
    # downloaded, downloading, missing, unreleased or unmonitored
    state: str
    monitored: bool


@router.get('/calendar', response_model=list[CalendarEntry])
def list_calendar(start: str = '', end: str = '', unmonitored: bool = False):
    """ The books out from start to end (yyyy-mm-dd, today and the four weeks after unless given) and
    the magazines' issues, those there are and those missing or due, the ones not looked for too
    when unmonitored """
    return calendar.entries(start, end, unmonitored)


@feed.get('/feed/v1/calendar/LazyLibrarian.ics', include_in_schema=False)
def ical_feed(past_days: int = Query(7, alias='pastDays'), future_days: int = Query(28, alias='futureDays'),
              unmonitored: bool = False):
    """ The calendar for calendar apps, from pastDays ago to futureDays ahead """
    return Response(calendar.ical(past_days, future_days, unmonitored), media_type='text/calendar; charset=utf-8',
                    headers={'Content-Disposition': 'inline; filename="LazyLibrarian.ics"'})
