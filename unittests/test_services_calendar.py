#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/calendar.py, the books and the magazines' issues on each day, and the iCal feed

import datetime
from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import InvalidRequestError, calendar
from unittests.unittesthelpers import LLTestCaseWithDB

TODAY = datetime.date(2026, 10, 27)
SCHEDULE = calendar.magazines.issue_schedule


class CalendarTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        for key, value in (('AUDIO_TAB', True), ('MAG_TAB', True)):
            self.addCleanup(CONFIG.set_bool, key, CONFIG.get_bool(key))
            CONFIG.set_bool(key, value)
        self.sql("INSERT INTO authors (AuthorID, AuthorName, Status) VALUES ('a1', 'Matt Dinniman', 'Active'), "
                 "('a2', 'Nobody Wanted', 'Ignored')")
        for book_id, author, date, status, audio in (
                ('b1', 'a1', '2026-10-20', 'Wanted', 'Have'),  # out, the eBook not had
                ('b2', 'a1', '2026-11-03', 'Wanted', 'Skipped'),  # not out yet
                ('b3', 'a1', '2026-10-27', 'Skipped', 'Skipped'),  # not looked for
                ('b4', 'a1', '2026', 'Wanted', 'Wanted'),  # no day, not on the calendar
                ('b5', 'a2', '2026-10-28', 'Wanted', 'Wanted'),  # an ignored author's
                ('b6', 'a1', '2026-10-22', 'Snatched', 'Open')):
            self.sql("INSERT INTO books (BookID, AuthorID, BookName, BookDate, Status, AudioStatus) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (book_id, author, f'Book {book_id}', date, status, audio))
        self.sql("INSERT INTO series (SeriesID, SeriesName) VALUES ('s1', 'Dungeon Crawler Carl')")
        self.sql("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('s1', 'b1', '8')")

    def entries(self, **kwargs):
        return calendar.entries('2026-10-01', '2026-11-30', today=TODAY, **kwargs)

    def test_books(self):
        found = {entry['item_id']: entry for entry in self.entries() if entry['kind'] == 'book'}
        self.assertEqual(sorted(found), ['b1', 'b2', 'b6'], 'Not the one not looked for, undated or ignored')
        self.assertEqual(found['b1']['state'], calendar.MISSING, 'Out and an eBook wanted')
        self.assertEqual([f['state'] for f in found['b1']['formats']], [calendar.MISSING, calendar.DOWNLOADED])
        self.assertEqual(found['b1']['series'], 'Dungeon Crawler Carl #8')
        self.assertEqual((found['b1']['parent'], found['b1']['parent_id']), ('Matt Dinniman', 'a1'))
        self.assertEqual(found['b2']['state'], calendar.UNRELEASED)
        self.assertEqual(found['b6']['state'], calendar.DOWNLOADING)
        everything = {entry['item_id'] for entry in self.entries(unmonitored=True)}
        self.assertIn('b3', everything)
        self.assertNotIn('b5', everything)
        CONFIG.set_bool('AUDIO_TAB', False)
        found = {entry['item_id']: entry for entry in self.entries()}
        self.assertEqual(len(found['b1']['formats']), 1, 'Audiobooks only when they have a tab')

    def test_issues(self):
        self.sql("INSERT INTO magazines (Title, Status, IssueDate, Frequency, LatestCover) "
                 "VALUES ('Wood', 'Active', '2026-09-01', 30, 'cache/wood.jpg'), ('Paused', 'Paused', '', 0, '')")
        for issue_id, date in (('i1', '2026-06-01'), ('i2', '2026-07-01'), ('i3', '2026-09-01')):
            self.sql("INSERT INTO issues (Title, IssueID, IssueDate) VALUES ('Wood', ?, ?)", (issue_id, date))
        self.sql("INSERT INTO issues (Title, IssueID, IssueDate) VALUES ('Paused', 'p1', '2026-10-05'), "
                 "('Paused', 'p2', '20260012')")
        self.sql("INSERT INTO wanted (BookID, AuxInfo, Status) VALUES ('Wood', '2026-10-01', 'Snatched')")
        with mock.patch.object(calendar.magazines, 'issue_schedule',
                               side_effect=lambda dates, frequency, **kwargs: SCHEDULE(dates, frequency, today=TODAY, **kwargs)):
            found = [entry for entry in calendar.entries('2026-06-01', '2026-11-30', today=TODAY)
                     if entry['kind'] != 'book']
        self.assertEqual([(entry['kind'], entry['date'], entry['state']) for entry in found], [
            ('issue', '2026-06-01', calendar.DOWNLOADED), ('issue', '2026-07-01', calendar.DOWNLOADED),
            ('due', '2026-08-01', calendar.MISSING), ('issue', '2026-09-01', calendar.DOWNLOADED),
            ('due', '2026-10-01', calendar.DOWNLOADING)])
        self.assertEqual(found[-1]['image'], 'cache/wood.jpg')
        paused = [entry for entry in calendar.entries('2026-06-01', '2026-11-30', unmonitored=True, today=TODAY)
                  if entry['parent'] == 'Paused']
        self.assertEqual([entry['item_id'] for entry in paused], ['p1'], 'Shown when asked for, by date only')

    def test_range(self):
        self.assertRaises(InvalidRequestError, calendar.entries, '2026-10-10', '2026-10-01')
        self.assertRaises(InvalidRequestError, calendar.entries, 'soon')
        self.assertRaises(InvalidRequestError, calendar.entries, '2020-01-01', '2026-01-01')
        self.assertEqual([entry['item_id'] for entry in calendar.entries(today=TODAY)], ['b2'],
                         'Today and four weeks after')

    def test_ical(self):
        feed = calendar.ical(past_days=10, future_days=5, today=TODAY)
        self.assertTrue(feed.startswith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'))
        self.assertTrue(feed.endswith('END:VCALENDAR\r\n'))
        self.assertIn('SUMMARY:Matt Dinniman - Book b1\r\n', feed)
        self.assertIn('DTSTART;VALUE=DATE:20261020\r\nDTEND;VALUE=DATE:20261021\r\n', feed)
        self.assertIn('DESCRIPTION:Dungeon Crawler Carl #8\\neBook: Wanted\\nAudiobook: Have\r\n', feed)
        self.assertEqual(feed.count('BEGIN:VEVENT'), 2, 'b1 and b6, b2 is too far ahead')
        self.assertTrue(all(len(line.encode()) <= 75 for line in feed.split('\r\n')), 'Folded')
        self.assertEqual(calendar._fold('x' * 80), 'x' * 75 + '\r\n ' + 'x' * 5)
