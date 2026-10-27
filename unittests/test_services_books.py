#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/books.py

from unittest import mock

import lazylibrarian
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import InvalidRequestError, NotFoundError, ServiceError, books
from lazylibrarian.startup import StartupLazyLibrarian
from unittests.unittesthelpers import LLTestCaseWithDB

BOOKS = [
    # BookID, AuthorID, BookName, BookRate, Status, AudioStatus, BookLang, SeriesDisplay, BookLibrary, BookGenre,
    # Manual, ol_id
    ('B1', 'A1', 'The Witching Hour', '4.4', 'Have', 'Wanted', 'en', 'Mayfair #1', '2026-01-02', 'Horror', '0', 'OL1W'),
    ('B2', 'A1', 'lasher', '3.9', 'Wanted', 'Skipped', 'en', 'Mayfair #10', '2026-01-10', 'Horror', '1', 'OL2W'),
    ('B3', 'A2', 'Germinal', '5', 'Skipped', 'Have', 'fr', 'Mayfair #2', '2026-01-04', None, '0', ''),
    ('B4', 'A2', 'Nana', None, 'Ignored', 'Ignored', 'fr', None, None, 'Novel', '0', ''),
]


class BookServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, lazylibrarian, 'INFOSOURCES', lazylibrarian.INFOSOURCES)
        lazylibrarian.INFOSOURCES = StartupLazyLibrarian.build_sources()
        saved = {k: CONFIG[k] for k in ('SORT_SURNAME', 'SORT_DEFINITE', 'EBOOK_TAB', 'AUDIO_TAB', 'IMP_AUTOSEARCH')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(k, v) for k, v in saved.items()])
        for key, value in (('SORT_SURNAME', False), ('SORT_DEFINITE', False), ('EBOOK_TAB', True),
                           ('AUDIO_TAB', True), ('IMP_AUTOSEARCH', False)):
            CONFIG.set_bool(key, value)
        self.sql("INSERT INTO authors (AuthorID,AuthorName,Status) VALUES ('A1','Anne Rice','Active'),"
                 "('A2','Émile Zola','Active')")
        for b in BOOKS:
            self.sql("INSERT INTO books (BookID,AuthorID,BookName,BookRate,Status,AudioStatus,BookLang,SeriesDisplay,"
                     "BookLibrary,BookGenre,Manual,ol_id,BookDesc,BookImg) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'desc','img')",
                     b)
            self.sql("INSERT INTO bookauthors (AuthorID,BookID,Role) VALUES (?,?,1)", (b[1], b[0]))
        self.owner = self.sql('SELECT UserID FROM users')[0]['UserID']
        update = mock.patch.object(books, 'update_totals')
        update.start()
        self.addCleanup(update.stop)

    def ids(self, page):
        return [b['BookID'] for b in page.items]

    def book(self, bookid):
        return self.sql('SELECT * FROM books WHERE BookID=?', (bookid,))[0]

    def test_list_views(self):
        self.assertEqual(self.ids(books.list_books('Books', 'eBook')), ['B2', 'B1'], 'Not skipped or ignored')
        self.assertEqual(self.ids(books.list_books('Audio', 'AudioBook', sort='BookID')), ['B1', 'B3'])
        self.assertEqual(self.ids(books.list_books('Author', 'eBook', authorid='A2')), ['B3'])
        self.assertEqual(self.ids(books.list_books('Author', 'eBook', authorid='A2', ignored=True)), ['B4'])
        self.assertEqual(self.ids(books.list_books('Manage', 'eBook', status='Wanted')), ['B2'])
        self.assertEqual(self.ids(books.list_books('Manage', 'AudioBook', status='Have')), ['B3'])
        self.assertEqual(len(books.list_books('Manage', 'eBook').items), 4)
        self.assertEqual(books.list_books('Books', None).items, [], 'No library switched on')
        with self.assertRaises(InvalidRequestError):
            books.list_books('Everything', 'eBook')

    def test_list_language_search_and_paging(self):
        self.assertEqual(self.ids(books.list_books('Author', 'eBook', authorid='A1', booklang='fr')), [])
        page = books.list_books('Manage', 'eBook', search='HORROR')
        self.assertEqual(self.ids(page), ['B2', 'B1'])
        self.assertEqual((page.total, page.matched), (4, 2))
        self.assertEqual(self.ids(books.list_books('Manage', 'AudioBook', search='wanted')), ['B1'],
                         'The search looks at the audiobook status')
        page = books.list_books('Manage', 'eBook', sort='BookID', offset=1, limit=2)
        self.assertEqual((self.ids(page), page.matched), (['B2', 'B3'], 4))

    def test_list_sorts(self):
        self.assertEqual(self.ids(books.list_books('Manage', 'eBook', sort='TitleSort')), ['B3', 'B2', 'B4', 'B1'],
                         'Titles ignore case')
        self.assertEqual(self.ids(books.list_books('Manage', 'eBook', sort='BookRate', descending=True)),
                         ['B3', 'B1', 'B2', 'B4'])
        self.assertEqual(self.ids(books.list_books('Manage', 'eBook', sort='SeriesDisplay'))[1:],
                         ['B1', 'B3', 'B2'], 'Series numbers sort by value')

    def test_list_surname_and_reading_lists(self):
        CONFIG.set_bool('SORT_SURNAME', True)
        books.mark_books('ToRead', ['B1'], userid=self.owner)
        page = books.list_books('Books', 'eBook', userid=self.owner, sort='BookID')
        self.assertEqual([b['AuthorSort'] for b in page.items], ['Rice, Anne', 'Rice, Anne'])
        self.assertEqual([b['ReadingList'] for b in page.items], ['ToRead', None])
        self.assertEqual(self.ids(books.list_books('Manage', 'eBook', status='ToRead', userid=self.owner)), ['B1'])

    def test_list_manage_has_failed_searches(self):
        self.sql("INSERT INTO failedsearch (BookID,Library,Time,Interval,Count) VALUES ('B2','eBook','1700000000',3,2)")
        items = {b['BookID']: b for b in books.list_books('Manage', 'eBook').items}
        self.assertEqual((items['B2']['FailedSearch']['Count'], items['B1']['FailedSearch']), (2, None))

    def test_list_subscribed_only(self):
        self.sql("INSERT INTO subscribers (UserID,Type,WantID) VALUES (?,'author','A2')", (self.owner,))
        self.assertEqual(self.ids(books.list_books('Audio', 'AudioBook', userid=self.owner, subscribed_only=True)),
                         ['B3'])

    def test_mark_reading_lists(self):
        self.assertEqual(books.mark_books('Read', ['B1', 'B2'], userid=self.owner)['passed'], 2)
        books.mark_books('ToRead', ['B2'], userid=self.owner)
        lists = books.reading_lists(self.owner)
        self.assertEqual((lists['HaveRead'], lists['ToRead']), ({'B1'}, {'B2'}))

    def test_mark_unread_takes_books_off_the_lists(self):
        books.mark_books('Reading', ['B1', 'B2'], userid=self.owner)
        self.sql("INSERT INTO readinglists (UserID,BookID,Status) VALUES (?,'B3',4)", (self.owner,))
        books.mark_books('Unread', ['B1', 'B3'], userid=self.owner)
        self.assertEqual(books.reading_lists(self.owner)['Reading'], {'B2'})
        self.assertEqual(self.sql("SELECT BookID FROM readinglists WHERE Status=4"), [{'BookID': 'B3'}],
                         'Owned is not a reading list')

    def test_mark_wanted(self):
        with mock.patch.object(CONFIG, 'use_any', return_value=False):
            result = books.mark_books('Wanted', ['B1', 'B3'], library='eBook')
            self.assertEqual((result['passed'], result['failed']), (1, 1), 'B1 is already Have')
            self.assertEqual((self.book('B3')['Status'], self.book('B3')['ScanResult']), ('Wanted', 'User Wanted'))
            result = books.mark_books('WantAudio', ['B4'])
            self.assertEqual((result['passed'], result['authorid']), (1, 'A2'))
            self.assertEqual(self.book('B4')['AudioStatus'], 'Wanted')

    def test_mark_wanted_starts_a_search(self):
        with mock.patch.object(CONFIG, 'use_any', return_value=True), \
                mock.patch.object(CONFIG, '__getitem__', side_effect=lambda key: '360'), \
                mock.patch.object(books.threading, 'Thread') as thread:
            books.mark_books('WantBoth', ['B4'])
        self.assertEqual([c.kwargs['args'][1] for c in thread.call_args_list], ['eBook', 'AudioBook'])

    def test_mark_status(self):
        books.mark_books('IgnoreBoth', ['B1'])
        self.assertEqual((self.book('B1')['Status'], self.book('B1')['AudioStatus']), ('Ignored', 'Ignored'))
        books.mark_books('Have', ['B3'], library='AudioBook')
        self.assertEqual((self.book('B3')['Status'], self.book('B3')['AudioStatus']), ('Skipped', 'Have'))
        self.assertEqual(books.mark_books('Have', ['nosuch'])['failed'], 1)

    def test_mark_nodelay_remove_and_delete(self):
        self.sql("INSERT INTO failedsearch (BookID,Library) VALUES ('B2','eBook'),('B2','AudioBook')")
        books.mark_books('NoDelay', ['B2'], library='AudioBook')
        self.assertEqual([r['Library'] for r in self.sql('SELECT Library FROM failedsearch')], ['eBook'])
        books.mark_books('Remove', ['B2'], library='eBook')
        self.assertEqual((self.book('B2')['Status'], self.book('B2')['ScanResult']), ('Ignored', 'User Removed ebook'))
        books.mark_books('Delete', ['B4'], library='eBook+AudioBook')
        self.assertEqual(self.sql("SELECT * FROM books WHERE BookID='B4'"), [], 'Gone when ignored in both')
        self.assertEqual(books.mark_books('', ['B1']), {'passed': 0, 'failed': 0, 'authorid': None})

    def test_add_book_already_known(self):
        self.assertEqual(books.add_book('B4', library='AudioBook'), ('A2', 'Skipped', 'Wanted'))
        self.assertEqual((self.book('B4')['Status'], self.book('B4')['AudioStatus']), ('Ignored', 'Wanted'),
                         'The eBook is left as it was')
        CONFIG.set_bool('AUDIO_TAB', False)
        self.assertEqual(books.add_book('B4')[1:], ('Wanted', 'Skipped'))

    def test_add_book_from_a_source(self):
        api = mock.MagicMock()
        with mock.patch.dict(lazylibrarian.INFOSOURCES['OpenLibrary'], {'api': api}), \
                mock.patch.object(CONFIG, '__getitem__', side_effect=lambda key: 'OpenLibrary'):
            self.assertEqual(books.add_book('OL9W', library='Both', source='Nowhere'), ('', 'Wanted', 'Wanted'))
        api.return_value.add_bookid_to_db.assert_called_once_with('OL9W', 'Wanted', 'Wanted', 'Added by user')

    def test_refresh_book(self):
        chosen = 'cache/book/0123456789abcdef0123456789abcdef.jpg'
        self.sql("INSERT INTO books (BookID,AuthorID,BookName,Status,AudioStatus,Manual,ol_id,BookAdded,BookImg) "
                 "VALUES ('OL5W','A1','Pandora','Open','Wanted','0','OL5W','2025-02-03',?)", (chosen,))

        def add_again(bookid, bookstatus, audiostatus, reason):
            # what a source does: its details over the book's, the statuses it's given
            self.sql("UPDATE books SET Status=?, AudioStatus=?, BookAdded='2099-01-01', "
                     "BookImg='cache/book/OL5W.jpg' WHERE BookID=?", (bookstatus, audiostatus, bookid))
            return True

        api = mock.MagicMock()
        api.return_value.add_bookid_to_db.side_effect = add_again
        with mock.patch.dict(lazylibrarian.INFOSOURCES['OpenLibrary'], {'api': api}):
            self.assertEqual(books.refresh_book('OL5W', wait=True), 'OpenLibrary')
            self.assertEqual(books.refresh_book('B1'), '', "Its id isn't OpenLibrary's, it'd be another book")
            self.assertEqual(books.refresh_book('B2'), '', 'Locked against changes')
            self.assertEqual(books.refresh_book('B3'), '', 'Not linked to a source')
            api.return_value.add_bookid_to_db.side_effect = None
            api.return_value.add_bookid_to_db.return_value = False
            with self.assertRaises(ServiceError):
                books.refresh_book('OL5W', wait=True)
        refreshed = self.book('OL5W')
        self.assertEqual((refreshed['Status'], refreshed['AudioStatus']), ('Open', 'Wanted'), 'Its statuses stay')
        self.assertEqual(refreshed['BookAdded'], '2025-02-03', 'So does when it was added')
        self.assertEqual(refreshed['BookImg'], chosen, 'And a cover chosen for it')
        with self.assertRaises(NotFoundError):
            books.refresh_book('nosuch')

    def test_kept_covers_and_statuses(self):
        from lazylibrarian.bookdict import kept_status
        from lazylibrarian.images import chosen_author_image, chosen_cover
        self.assertTrue(chosen_author_image('cache/author/chosen_Ab12Cd34Ef.jpg'))
        self.assertFalse(chosen_author_image('cache/author/Ab12Cd34Ef.jpg'), 'One a refresh cached')
        self.assertTrue(chosen_cover('cache/book/0123456789abcdef0123456789abcdef.jpg'))
        self.assertFalse(chosen_cover('cache/book/12605157.jpg'), "A source's cover, cached by the book's id")
        self.assertFalse(chosen_cover('cache/book/0123456789abcdef0123456789abcdef_gr.jpg'))
        self.assertEqual(kept_status('Open', 'Skipped'), 'Open', "Adding a book you have again doesn't skip it")
        self.assertEqual(kept_status('Snatched', 'Skipped'), 'Snatched')
        self.assertEqual(kept_status('Skipped', 'Wanted'), 'Wanted')

    def test_snatch(self):
        with mock.patch.object(books, 'nzb_dl_method', return_value=(False, 'no client')), \
                mock.patch.object(books, 'schedule_job'):
            self.assertEqual(books.snatch('B2', 'nzb', 'prov', 'http://x', '2097152', 'eBook'),
                             ('A1', False, 'no client'))
        wanted = self.sql('SELECT * FROM wanted')[0]
        self.assertEqual((wanted['Status'], wanted['NZBsize'], wanted['DLResult']), ('Failed', '2.0', 'no client'))
        with self.assertRaises(NotFoundError):
            books.snatch('nosuch', 'nzb', 'prov', 'http://y', 1, 'eBook')

    def test_search_for_book(self):
        with mock.patch.object(books, 'start_search') as start:
            self.assertEqual(books.search_for_book('B3', 'eBook'), 'A2')
        start.assert_called_once_with([{'bookid': 'B3'}], library='eBook', force=True)
        with self.assertRaises(NotFoundError):
            books.search_for_book('nosuch')

    def test_request_book(self):
        with self.assertRaises(InvalidRequestError):
            books.request_book(self.owner, 'B1', {}, '1.2.3.4')
        self.sql("UPDATE users SET Email='me@example.com'")
        with mock.patch.object(books.notifiers.email_notifier, 'notify_message', return_value=True) as send:
            self.assertEqual(books.request_book(self.owner, 'B1', {'library': 'eBook'}, '1.2.3.4'),
                             ('The Witching Hour', True))
        self.assertIn('IP: 1.2.3.4', send.call_args.args[1])
        with self.assertRaises(NotFoundError):
            books.request_book('nobody', 'B1', {}, '')

    def test_book_details(self):
        details = books.book_details('B1')
        self.assertEqual(details['book']['AuthorName'], 'Anne Rice')
        self.assertEqual(details['links'][0][:2], ('ol_id', 'OL1W'))
        self.assertEqual(details['amazon_link'], '')
        with self.assertRaises(NotFoundError):
            books.book_details('nosuch')

    def test_lookup_asin_needs_goodreads(self):
        with self.assertRaises(InvalidRequestError):
            books.lookup_asin('B1')

    def test_book_for_edit(self):
        edit = books.book_for_edit('B1', library='eBook')
        self.assertEqual((edit['book']['BookName'], edit['book']['library']), ('The Witching Hour', 'eBook'))
        self.assertNotIn('Narrator', edit['book'])
        self.assertIn('Narrator', books.book_for_edit('B1', library='AudioBook')['book'])
        with self.assertRaises(NotFoundError):
            books.book_for_edit('nosuch')

    def test_valid_book_date(self):
        for date, valid in (('1990', True), ('-412', True), ('1990-02', True), ('1990-13', False),
                            ('1990-02-30', False), ('1990-02-28', True), ('19900', False), ('', False)):
            self.assertEqual(books.valid_book_date(date), valid, date)

    def update(self, bookid='B1', **changes):
        book = self.book(bookid)
        values = {'name': book['BookName'], 'subtitle': book['BookSub'], 'genre': book['BookGenre'],
                  'lang': book['BookLang'], 'date': book['BookDate'], 'manual': False, 'author_name': 'Anne Rice',
                  'description': book['BookDesc'], 'isbn': book['BookIsbn'], 'workid': book['WorkID']}
        values.update(changes)
        return books.update_book(bookid, **values)

    def test_update_book(self):
        self.assertEqual(self.update(), '')
        self.assertIn('Title', self.update(name='The Witching Hour!', date='1990-13-01'))
        book = self.book('B1')
        self.assertEqual((book['BookName'], book['BookDate']), ('The Witching Hour!', None), 'Bad date left alone')
        self.sql("INSERT INTO series (SeriesID,SeriesName,Status) VALUES ('S1','Mayfair Witches','Paused')")
        self.assertIn('Series', self.update(series=[('Mayfair Witches', '1'), ('No Number', '')]))
        self.assertEqual(self.sql("SELECT SeriesID,SeriesNum FROM member"), [{'SeriesID': 'S1', 'SeriesNum': '1'}])
        with self.assertRaises(NotFoundError):
            books.update_book('nosuch', 'x', '', '', '', '', False, '', '', '', '')

    def test_update_book_moves_it_to_another_author(self):
        self.update(author_name='Émile Zola')
        self.assertEqual(self.book('B1')['AuthorID'], 'A2')

    def test_add_search_results(self):
        api = mock.MagicMock()
        api.return_value.add_bookid_to_db.side_effect = [True, False]
        with mock.patch.dict(lazylibrarian.INFOSOURCES['OpenLibrary'], {'api': api}), \
                mock.patch.object(CONFIG, '__getitem__', side_effect=lambda key: 'OpenLibrary'):
            self.assertEqual(books.add_search_results('AddAudio', ['X1', 'X2']), (1, 1))
        self.assertEqual(api.return_value.add_bookid_to_db.call_args.args[1:3], ('Skipped', 'Wanted'))
        self.assertEqual(books.add_search_results('Nothing', ['X1']), (0, 0))

    def test_description(self):
        self.assertEqual(books.description('B1'), {'img': 'img', 'title': 'The Witching Hour', 'text': 'desc',
                                                   'AuthorID': 'A1'})
        self.assertEqual(books.description('A_A1')['title'], 'Anne Rice')
        self.assertIsNone(books.description('nosuch'))

    def test_language_refresh(self):
        status = books.language_refresh_status()
        self.assertEqual(set(status), {'running', 'checked', 'updated', 'unignored', 'total'})
        with mock.patch.object(books, 'is_running', return_value=True), self.assertRaises(InvalidRequestError):
            books.start_language_refresh()
