#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/series.py

from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import NotFoundError, books, series
from unittests.unittesthelpers import LLTestCaseWithDB


class SeriesServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.addCleanup(CONFIG.set_from_ui, 'SORT_SURNAME', CONFIG['SORT_SURNAME'])
        CONFIG.set_bool('SORT_SURNAME', False)
        self.sql("INSERT INTO authors (AuthorID,AuthorName,Status) VALUES ('A1','Anne Rice','Active'),"
                 "('A2','Émile Zola','Paused')")
        for sid, name, status, have, total, reason in (
                ('OL1S', 'Mayfair', 'Active', 2, 4, 'B1'), ('GR2S', 'Rougon', 'Paused', 0, 20, 'x'),
                ('OL3S', 'Vampire', 'Wanted', 5, 5, None), ('OL4S', 'Short', 'Skipped', 1, 2, '')):
            self.sql("INSERT INTO series (SeriesID,SeriesName,Status,Have,Total,Reason) VALUES (?,?,?,?,?,?)",
                     (sid, name, status, have, total, reason))
        for sid, aid in (('OL1S', 'A1'), ('GR2S', 'A2'), ('OL3S', 'A1'), ('OL4S', 'A1'), ('OL4S', 'A2')):
            self.sql("INSERT INTO seriesauthors (SeriesID,AuthorID) VALUES (?,?)", (sid, aid))
        for bid, aid, name, status in (('B1', 'A1', 'Witching', 'Have'), ('B2', 'A1', 'Lasher', 'Ignored'),
                                       ('B3', 'A2', 'Germinal', 'Wanted')):
            self.sql("INSERT INTO books (BookID,AuthorID,BookName,Status,AudioStatus) VALUES (?,?,?,?,'Skipped')",
                     (bid, aid, name, status))
        for sid, bid, num in (('OL1S', 'B1', '10'), ('OL1S', 'B2', '2'), ('GR2S', 'B3', '1'), ('OL3S', 'B1', '3'),
                              ('OL4S', 'B1', '1'), ('OL4S', 'B3', '2')):
            self.sql("INSERT INTO member (SeriesID,BookID,SeriesNum) VALUES (?,?,?)", (sid, bid, num))
        self.owner = self.sql('SELECT UserID FROM users')[0]['UserID']

    def ids(self, page):
        return [s['SeriesID'] for s in page.items]

    def test_list_series(self):
        page = series.list_series()
        self.assertEqual(self.ids(page), ['OL1S', 'OL4S', 'OL3S', 'GR2S'])
        items = {s['SeriesID']: s for s in page.items}
        self.assertEqual((items['OL1S']['Percent'], items['OL1S']['Source']), (50, 'OL'))

    def test_list_filters(self):
        self.assertEqual(self.ids(series.list_series(status='Empty')), ['GR2S'])
        self.assertEqual(self.ids(series.list_series(status='Complete')), ['OL3S'])
        self.assertEqual(self.ids(series.list_series(status='Partial')), ['OL1S', 'OL4S', 'OL3S'])
        self.assertEqual(self.ids(series.list_series(status='Paused')), ['GR2S'])
        self.assertEqual(self.ids(series.list_series(authorid='A2')), ['GR2S', 'OL4S'])
        self.assertNotIn('GR2S', self.ids(series.list_series(active_only=True)), 'Its author is paused')
        self.assertEqual(self.ids(series.list_series(search='rougon')), ['GR2S'])

    def test_list_subscribed(self):
        self.sql("INSERT INTO subscribers (UserID,Type,WantID) VALUES (?,'series','OL3S'),(?,'series','GR2S')",
                 (self.owner, self.owner))
        self.assertEqual(self.ids(series.list_series(subscriber=self.owner)), ['OL3S', 'GR2S'])

    def test_percent_sort_breaks_ties_on_total_the_other_way(self):
        # OL1S and OL4S are both 50%, OL1S has more books
        page = series.list_series(sort='Percent', descending=True)
        self.assertEqual(self.ids(page), ['OL3S', 'OL4S', 'OL1S', 'GR2S'])
        page = series.list_series(sort='Percent')
        self.assertEqual(self.ids(page), ['GR2S', 'OL1S', 'OL4S', 'OL3S'])

    def test_series_for_edit(self):
        edit = series.series_for_edit('OL1S')
        self.assertEqual(edit['series']['Reason'], 'B1: Witching')
        self.assertEqual([m['SeriesNum'] for m in edit['members']], ['2', '10'])
        with self.assertRaises(NotFoundError):
            series.series_for_edit('nosuch')

    def test_update_series(self):
        self.assertFalse(series.update_series('OL1S'))
        self.assertTrue(series.update_series('OL1S', new_id='OL9S', new_name='Mayfair Witches'))
        self.assertEqual(self.sql("SELECT SeriesName FROM series WHERE SeriesID='OL9S'")[0]['SeriesName'],
                         'Mayfair Witches')
        self.assertEqual(len(self.sql("SELECT * FROM member WHERE SeriesID='OL9S'")), 2)
        with self.assertRaises(NotFoundError):
            series.update_series('OL1S')

    def test_remove_series(self):
        series.remove_series('GR2S')
        self.assertEqual(self.sql("SELECT * FROM series WHERE SeriesID='GR2S'"), [])
        with self.assertRaises(NotFoundError):
            series.remove_series('GR2S')

    def test_series_page(self):
        page = series.series_page('OL4S', userid=self.owner)
        self.assertEqual([m['BookID'] for m in page['members']], ['B1', 'B3'])
        self.assertTrue(page['multi'])
        page = series.series_page('OL1S', ignored=True)
        self.assertEqual([m['BookID'] for m in page['members']], ['B2'])
        self.assertFalse(page['multi'])
        with self.assertRaises(NotFoundError):
            series.series_page('nosuch')

    def test_mark_status(self):
        with mock.patch.object(series, 'start_task') as start, mock.patch.object(series, 'ensure_running'):
            self.assertEqual(series.mark_series('Wanted', ['GR2S', 'nosuch']), (1, 1))
            start.assert_called_once()
        series.mark_series('Paused', ['OL1S'])
        self.assertEqual(self.sql("SELECT Status,Updated FROM series WHERE SeriesID='OL1S'")[0],
                         {'Status': 'Paused', 'Updated': 0})

    def test_mark_reading_lists(self):
        self.assertEqual(series.mark_series('Read', ['OL4S'], self.owner), (2, 0))
        self.assertEqual(books.reading_lists(self.owner)['HaveRead'], {'B1', 'B3'})
        series.mark_series('Unread', ['OL4S'], self.owner)
        self.assertEqual(books.reading_lists(self.owner)['HaveRead'], set())
        self.assertEqual(series.mark_series('Read', ['OL4S']), (0, 0), 'No user')

    def test_mark_subscribe(self):
        self.assertEqual(series.mark_series('Subscribe', ['OL3S', 'nosuch'], self.owner), (1, 1))
        self.assertEqual(series.mark_series('Subscribe', ['OL3S'], self.owner), (0, 1), 'Already subscribed')
        self.assertEqual(series.mark_series('Subscribe', ['OL3S']), (0, 1), 'No user')
        self.assertEqual(series.mark_series('Unsubscribe', ['OL3S'], self.owner), (1, 0))
        self.assertEqual(self.sql('SELECT * FROM subscribers'), [])
