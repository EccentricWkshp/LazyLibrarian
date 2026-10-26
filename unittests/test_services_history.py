#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/history.py and the history page rows built from it

from unittest import mock

from lazylibrarian.services import NotFoundError, history
from lazylibrarian.web.history import HistoryPages
from unittests.unittesthelpers import LLTestCaseWithDB

WANTED = ("INSERT INTO wanted (BookID,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,Source,DownloadID,"
          "DLResult,NZBurl) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")


class HistoryServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.sql("INSERT INTO authors (AuthorID,AuthorName) VALUES ('a1','Anne Author')")
        for bookid, status, audiostatus in (('b1', 'Snatched', 'Skipped'), ('b2', 'Skipped', 'Snatched'),
                                            ('b3', 'Snatched', 'Skipped')):
            self.sql("INSERT INTO books (BookID,AuthorID,BookName,Status,AudioStatus,ScanResult) "
                     "VALUES (?,'a1',?,?,?,'Invalid language')", (bookid, f'Book {bookid}', status, audiostatus))
        self.rows = [
            ('b1', 'First.Book', '2026-01-01 10:00:00', 'prov/', 'Snatched', '10', 'eBook', 'torrent', 'SABNZBD',
             'id1', '', 'http://one'),
            ('b2', 'Second Book', '2026-01-02 10:00:00', 'prov', 'Snatched', '2', 'AudioBook', 'nzb', 'SABNZBD',
             'id2', '', 'http://two'),
            ('Mag', 'Mag Issue', '2026-01-03 10:00:00', 'prov', 'Processed', '100', '2026-01', 'nzb', 'SABNZBD',
             'id3', '/books/mag.pdf', 'http://three'),
            ('b3', 'Émile Third', '2026-01-04 10:00:00', 'prov', 'Matched', '5', 'eBook', 'nzb', 'SABNZBD',
             'id4', '', 'http://four'),
            ('b4', 'No Type', '2026-01-05 10:00:00', 'prov', 'Failed', '1', None, 'nzb', 'SABNZBD', 'id5', 'bad',
             'http://five'),
        ]
        for row in self.rows:
            self.sql(WANTED, row)
        patch = mock.patch.object(history, 'get_download_progress', return_value=(42, False))
        self.progress = patch.start()
        self.addCleanup(patch.stop)

    def rowid(self, title):
        return self.sql('SELECT rowid FROM wanted WHERE NZBtitle=?', (title,))[0]['rowid']

    def test_list_newest_first_without_rows_missing_a_type(self):
        page = history.list_history()
        self.assertEqual([i['NZBtitle'] for i in page.items], ['Émile Third', 'Mag Issue', 'Second Book', 'First.Book'])
        self.assertEqual((page.total, page.matched), (4, 4))

    def test_list_search_sort_and_page(self):
        page = history.list_history(search='emile')
        self.assertEqual([i['BookID'] for i in page.items], ['b3'])
        self.assertEqual((page.total, page.matched), (4, 1))
        page = history.list_history(sort='NZBsize', descending=False)
        self.assertEqual([i['NZBsize'] for i in page.items], ['2', '5', '10', '100'])
        page = history.list_history(sort='NZBsize', descending=False, offset=1, limit=2)
        self.assertEqual([i['NZBsize'] for i in page.items], ['5', '10'])
        self.assertEqual(page.matched, 4)

    def test_list_adds_author_and_progress(self):
        items = {i['BookID']: i for i in history.list_history().items}
        self.assertEqual(items['b1']['AuthorID'], 'a1')
        self.assertIsNone(items['Mag']['AuthorID'])
        self.assertEqual(items['b1']['Progress'], 42)
        self.assertEqual(items['b2']['Progress'], 42)
        self.assertIsNone(items['b3']['Progress'], 'Only snatched downloads have progress')
        self.progress.assert_any_call('SABNZBD', 'id1')

    def test_progress_only_for_the_first_snatched(self):
        items = history.list_history(progress_limit=1).items
        self.assertEqual([i['Progress'] for i in items if i['Status'] == 'Snatched'], [42, None])
        self.assertEqual(self.progress.call_count, 1)

    def test_item_type(self):
        self.assertEqual([history.item_type(t) for t in ('eBook', 'AudioBook', '2026-01', None, '')],
                         ['eBook', 'AudioBook', 'Magazine', 'eBook', 'eBook'])

    def test_get_history_item(self):
        item = history.get_history_item(self.rowid('Mag Issue'))
        self.assertEqual((item['DLResult'], item['NZBurl']), ('/books/mag.pdf', 'http://three'))
        with self.assertRaises(NotFoundError):
            history.get_history_item(999)

    def test_ignored_reason(self):
        self.assertEqual(history.ignored_reason('b1'), 'Invalid language')
        with self.assertRaises(NotFoundError):
            history.ignored_reason('nosuchbook')

    def test_delete_history_item(self):
        history.delete_history_item(self.rowid('Mag Issue'))
        self.assertEqual(self.sql("SELECT * FROM wanted WHERE NZBtitle='Mag Issue'"), [])
        with self.assertRaises(NotFoundError):
            history.delete_history_item(999)

    def test_mark_failed_wants_the_book_again(self):
        history.mark_failed(self.rowid('First.Book'))
        history.mark_failed(self.rowid('Second Book'))
        self.assertEqual(self.sql("SELECT Status FROM wanted WHERE BookID='b1'")[0]['Status'], 'Failed')
        books = {b['BookID']: b for b in self.sql('SELECT BookID,Status,AudioStatus FROM books')}
        self.assertEqual(books['b1']['Status'], 'Wanted')
        self.assertEqual(books['b2']['AudioStatus'], 'Wanted')
        self.assertEqual(books['b2']['Status'], 'Skipped')
        with self.assertRaises(NotFoundError):
            history.mark_failed(999)

    def test_clear_all_wants_snatched_books_again(self):
        history.clear_history('all')
        self.assertEqual(self.sql('SELECT * FROM wanted'), [])
        books = {b['BookID']: b for b in self.sql('SELECT BookID,Status,AudioStatus FROM books')}
        self.assertEqual((books['b1']['Status'], books['b2']['AudioStatus']), ('Wanted', 'Wanted'))
        self.assertEqual(books['b3']['Status'], 'Snatched', 'Its download was only Matched')

    def test_clear_snatched_clears_matched_too(self):
        history.clear_history('Snatched')
        self.assertEqual([r['Status'] for r in self.sql('SELECT Status FROM wanted ORDER BY rowid')],
                         ['Processed', 'Failed'])
        books = {b['BookID']: b for b in self.sql('SELECT BookID,Status,AudioStatus FROM books')}
        self.assertEqual((books['b1']['Status'], books['b2']['AudioStatus']), ('Wanted', 'Wanted'))
        self.assertEqual(books['b3']['Status'], 'Wanted')

    def test_clear_one_status(self):
        history.clear_history('Failed')
        self.assertEqual(len(self.sql('SELECT * FROM wanted')), 4)
        self.assertEqual(self.sql("SELECT * FROM wanted WHERE Status='Failed'"), [])
        self.assertEqual(self.sql("SELECT Status FROM books WHERE BookID='b1'")[0]['Status'], 'Snatched')

    def test_download_counts(self):
        self.sql("INSERT INTO downloads (Count,Provider) VALUES (3,'small'),(7,'big')")
        self.assertEqual(history.download_counts(), [{'Count': 7, 'Provider': 'big'}, {'Count': 3, 'Provider': 'small'}])
        self.assertEqual(history.clear_download_counts(), 2)
        self.assertEqual(history.download_counts(), [])
        self.assertEqual(history.clear_download_counts(), 0)

    def test_blocked_providers(self):
        with mock.patch.object(history, 'BLOCKHANDLER') as blockhandler:
            blockhandler.clear_all.return_value = 2
            blockhandler.get_text_list_of_blocks.return_value = 'No blocked providers'
            self.assertEqual(history.clear_blocked(), 2)
            self.assertEqual(history.blocked_text(), 'No blocked providers')

    def test_history_page_rows(self):
        result = HistoryPages().get_history(iDisplayStart=0, iDisplayLength=10, iSortCol_0=6, sSortDir_0='asc')
        self.assertEqual((result['iTotalRecords'], result['iTotalDisplayRecords']), (4, 4))
        first, second, mag, third = result['aaData']
        self.assertEqual(first[0], 'First Book', 'Dots become spaces')
        self.assertEqual(first[3], 'prov', 'Provider without the slash')
        self.assertIn("bookinfo('b1')", first[1])
        self.assertIn("author_page?authorid=a1", first[2])
        self.assertEqual(first[9:12], [42, self.rowid('First.Book'), '2026-01-01 10:00:00'])
        self.assertIn('open_mag?bookid=Mag', mag[2])
        self.assertEqual(third[9], -1, 'No progress for a matched download')
        self.assertEqual(len(first), 12)

    def test_history_page_search(self):
        result = HistoryPages().get_history(iDisplayStart=0, iDisplayLength=10, iSortCol_0=0, sSortDir_0='desc',
                                            sSearch='mag issue')
        self.assertEqual((result['iTotalRecords'], result['iTotalDisplayRecords']), (4, 1))
