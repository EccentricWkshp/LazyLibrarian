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

""" The calendar, like Sonarr's: the books out on each day, with what's wanted of each format, and the
magazines' issues, the ones there are and the ones missing or due. And the same as an iCal feed """

import datetime

from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int
from lazylibrarian.services import InvalidRequestError, magazines

# an entry's state, Sonarr's: had, being downloaded, out and not had, not out yet, or not looked for
DOWNLOADED = 'downloaded'
DOWNLOADING = 'downloading'
MISSING = 'missing'
UNRELEASED = 'unreleased'
UNMONITORED = 'unmonitored'
# when a book with several formats shows one state: the one that most needs doing
STATE_ORDER = (MISSING, DOWNLOADING, UNRELEASED, DOWNLOADED, UNMONITORED)
MAX_DAYS = 400
FORMATS = {'ebook': 'Status', 'audiobook': 'AudioStatus'}
FORMAT_NAMES = {'ebook': 'eBook', 'audiobook': 'Audiobook'}


def _day(text: str, default: datetime.date) -> datetime.date:
    if not text:
        return default
    try:
        return datetime.date.fromisoformat(str(text)[:10])
    except ValueError as why:
        raise InvalidRequestError(f"{text} isn't a date, yyyy-mm-dd") from why


def _state(status: str, day: str, today: str) -> str:
    if status in ('Have', 'Open'):
        return DOWNLOADED
    if status == 'Snatched':
        return DOWNLOADING
    if status == 'Wanted':
        return MISSING if day <= today else UNRELEASED
    return UNMONITORED


def _formats() -> list[str]:
    """ The formats the library shows: eBooks, and audiobooks when they have a tab """
    return ['ebook', 'audiobook'] if CONFIG.get_bool('AUDIO_TAB') else ['ebook']


def _books(db, start: str, end: str, today: str) -> list[dict]:
    """ The books out between start and end: those with a whole date, by authors not ignored """
    rows = db.select("SELECT books.BookID,BookName,BookSub,BookDate,BookImg,books.Status,AudioStatus,"
                     "books.AuthorID,AuthorName from books JOIN authors ON books.AuthorID=authors.AuthorID "
                     "WHERE length(BookDate)=10 AND BookDate BETWEEN ? AND ? AND authors.Status != 'Ignored'",
                     (start, end))
    series = {}
    for row in db.select("SELECT BookID,SeriesName,SeriesNum from member JOIN series ON "
                         "member.SeriesID=series.SeriesID WHERE BookID IN (SELECT BookID from books WHERE "
                         "length(BookDate)=10 AND BookDate BETWEEN ? AND ?) ORDER BY member.rowid", (start, end)):
        series.setdefault(row['BookID'], f"{row['SeriesName']}{' #' + row['SeriesNum'] if row['SeriesNum'] else ''}")
    entries = []
    for row in rows:
        formats = [{'format': name, 'status': row[FORMATS[name]] or 'Skipped',
                    'state': _state(row[FORMATS[name]] or 'Skipped', row['BookDate'], today)} for name in _formats()]
        states = [found['state'] for found in formats]
        entries.append({'id': f"book-{row['BookID']}", 'kind': 'book', 'item_id': row['BookID'],
                        'date': row['BookDate'], 'title': row['BookName'] or '', 'subtitle': row['BookSub'] or '',
                        'parent_id': row['AuthorID'] or '', 'parent': row['AuthorName'] or '',
                        'series': series.get(row['BookID'], ''), 'image': row['BookImg'] or '', 'formats': formats,
                        'state': min(states, key=STATE_ORDER.index),
                        'monitored': any(state != UNMONITORED for state in states)})
    return entries


def _issues(db, start: str, end: str, today: str) -> list[dict]:
    """ The magazines' issues dated between start and end that there are, and for the magazines
    looked for, those between the ones there are that it hasn't and the next one due """
    entries = []
    for row in db.select("SELECT issues.Title,IssueID,issues.IssueDate,Cover,magazines.Status from issues JOIN "
                         "magazines ON issues.Title=magazines.Title WHERE issues.IssueDate GLOB "
                         "'[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]' AND issues.IssueDate BETWEEN ? AND ?",
                         (start, end)):
        entries.append({'id': f"issue-{row['IssueID']}", 'kind': 'issue', 'item_id': row['IssueID'],
                        'date': row['IssueDate'], 'title': row['Title'], 'subtitle': '', 'parent_id': row['Title'],
                        'parent': row['Title'], 'series': '', 'image': row['Cover'] or '', 'formats': [],
                        'state': DOWNLOADED, 'monitored': row['Status'] == 'Active'})
    snatched = {(row['BookID'], row['AuxInfo']) for row in db.select(
        "SELECT BookID,AuxInfo from wanted WHERE Status='Snatched'")}
    for magazine in db.select("SELECT Title,Frequency,Started,LatestCover from magazines WHERE Status='Active'"):
        dates = [row['IssueDate'] for row in db.select('SELECT IssueDate from issues WHERE Title=?',
                                                       (magazine['Title'],))]
        schedule = magazines.issue_schedule(dates, check_int(magazine['Frequency'], 0), started=magazine['Started'] or '')
        if not schedule['frequency']:
            continue  # known by number, or too few issues to tell when they come out
        for day in schedule['missing'] + ([schedule['next']] if schedule['next'] else []):
            if len(day) != 10 or not start <= day <= end:
                continue
            state = DOWNLOADING if (magazine['Title'], day) in snatched else MISSING if day <= today else UNRELEASED
            entries.append({'id': f"due-{magazine['Title']}-{day}", 'kind': 'due', 'item_id': '', 'date': day,
                            'title': magazine['Title'], 'subtitle': '', 'parent_id': magazine['Title'],
                            'parent': magazine['Title'], 'series': '',
                            'image': magazine['LatestCover'] or '', 'formats': [],
                            'state': state, 'monitored': True})
    return entries


def entries(start: str = '', end: str = '', unmonitored: bool = False,
            today: datetime.date | None = None) -> list[dict]:
    """ What's on the calendar from start to end (today and the four weeks after it unless they're
    given), the ones not looked for too when unmonitored, by day """
    today = today or datetime.date.today()
    first = _day(start, today)
    last = _day(end, first + datetime.timedelta(days=28))
    if last < first:
        raise InvalidRequestError('The end is before the start')
    if (last - first).days > MAX_DAYS:
        raise InvalidRequestError(f'The calendar shows {MAX_DAYS} days at most')
    db = database.DBConnection()
    try:
        found = _books(db, first.isoformat(), last.isoformat(), today.isoformat())
        if CONFIG.get_bool('MAG_TAB'):
            found += _issues(db, first.isoformat(), last.isoformat(), today.isoformat())
    finally:
        db.close()
    if not unmonitored:
        found = [entry for entry in found if entry['monitored']]
    return sorted(found, key=lambda entry: (entry['date'], entry['kind'] != 'book', entry['parent'], entry['title']))


# --- the iCal feed, for calendar apps


def _text(value: str) -> str:
    return str(value).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _fold(line: str) -> str:
    """ A content line in pieces of at most 75 octets, as iCal has them """
    pieces, current = [], ''
    for char in line:
        if len((current + char).encode('utf-8')) > (75 if not pieces else 74):
            pieces.append(current)
            current = ''
        current += char
    pieces.append(current)
    return '\r\n '.join(pieces)


def _summary(entry: dict) -> str:
    if entry['kind'] == 'book':
        return f"{entry['parent']} - {entry['title']}"
    if entry['kind'] == 'due':
        return f"{entry['title']} ({'missing' if entry['state'] == MISSING else 'issue due'})"
    return f"{entry['title']} (issue)"


def _description(entry: dict) -> str:
    parts = [entry['series']] if entry['series'] else []
    parts += [f"{FORMAT_NAMES[found['format']]}: {found['status']}" for found in entry['formats']]
    if not entry['formats']:
        parts.append(entry['state'].capitalize())
    return '\n'.join(parts)


def ical(past_days: int = 7, future_days: int = 28, unmonitored: bool = False,
         today: datetime.date | None = None) -> str:
    """ The calendar from so many days ago to so many days ahead, as an iCal feed """
    today = today or datetime.date.today()
    past_days = max(0, min(past_days, MAX_DAYS))
    future_days = max(0, min(future_days, MAX_DAYS - past_days))
    found = entries((today - datetime.timedelta(days=past_days)).isoformat(),
                    (today + datetime.timedelta(days=future_days)).isoformat(), unmonitored, today)
    stamp = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//LazyLibrarian//Calendar//EN', 'CALSCALE:GREGORIAN',
             'X-WR-CALNAME:LazyLibrarian']
    for entry in found:
        day = datetime.date.fromisoformat(entry['date'])
        lines += ['BEGIN:VEVENT', f"UID:lazylibrarian-{_text(entry['id'])}", f'DTSTAMP:{stamp}',
                  f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(day + datetime.timedelta(days=1)).strftime('%Y%m%d')}",
                  f'SUMMARY:{_text(_summary(entry))}', f'DESCRIPTION:{_text(_description(entry))}',
                  f"CATEGORIES:{'Book' if entry['kind'] == 'book' else 'Magazine'}", 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'
