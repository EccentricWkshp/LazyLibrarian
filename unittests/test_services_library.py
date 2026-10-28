#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the library as the front end's pages show it (services/library.py): the authors, one
#   author with their books, and changing what's wanted

from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.services import InvalidRequestError, NotFoundError, library
from unittests.unittesthelpers import LLTestCaseWithStartup


class LibraryTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        saved = CONFIG.get_int('SEARCH_BOOKINTERVAL')
        self.addCleanup(CONFIG.set_int, 'SEARCH_BOOKINTERVAL', saved)
        CONFIG.set_int('SEARCH_BOOKINTERVAL', 0)  # wanting a book doesn't start a search here
        with DBConnection() as db:
            for table in ('books', 'authors', 'bookauthors', 'series', 'member'):
                db.action(f"DELETE FROM {table}")
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status, HaveBooks, UnignoredBooks, TotalBooks, "
                      "LastBook, LastBookID, LastDate, DateAdded, ol_link, About) VALUES "
                      "('a1', 'Lee Child', 'Active', 1, 4, 4, 'Persuader', 'b3', '2003-04-01', '2026-10-01', "
                      "'https://openlibrary.org/authors/OL1A', 'Jack Reacher')")
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status, HaveBooks, UnignoredBooks, TotalBooks) "
                      "VALUES ('a2', 'Andrew Child', 'Ignored', 0, 0, 1)")
            for bookid, author, name, date, status, audio, bookfile in (
                    ('b1', 'a1', 'Killing Floor', '1997-03-17', 'Open', 'Skipped', '/books/Killing Floor.epub'),
                    ('b2', 'a1', 'Die Trying', '1998-07-01', 'Skipped', 'Wanted', ''),
                    ('b3', 'a1', 'Persuader', '2003-04-01', 'Skipped', 'Skipped', ''),
                    ('b4', 'a2', 'The Sentinel', '2020-10-27', 'Wanted', 'Skipped', '')):
                db.action("INSERT INTO books (BookID, AuthorID, BookName, BookDate, Status, AudioStatus, BookFile) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)", (bookid, author, name, date, status, audio, bookfile))
                db.action("INSERT INTO bookauthors (AuthorID, BookID, Role) VALUES (?, ?, 1)", (author, bookid))
            # written together
            db.action("INSERT INTO bookauthors (AuthorID, BookID, Role) VALUES ('a1', 'b4', 1)")
            db.action("INSERT INTO series (SeriesID, SeriesName, Status) VALUES ('OL1', 'Jack Reacher', 'Active')")
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('OL1', 'b1', '1')")

    def statuses(self) -> dict:
        with DBConnection() as db:
            return {row['BookID']: (row['Status'], row['AudioStatus'])
                    for row in db.select('SELECT BookID, Status, AudioStatus FROM books')}

    def test_the_authors(self):
        found = library.list_authors()
        self.assertEqual([(a['id'], a['status'], a['have'], a['total'], a['percent']) for a in found],
                         [('a2', 'Ignored', 0, 0, 0), ('a1', 'Active', 1, 4, 25)], 'Ignored ones too, by name')
        self.assertEqual(found[1]['last_book'], {'id': 'b3', 'title': 'Persuader', 'date': found[1]['last_book']['date']})

    def test_an_author(self):
        author = library.get_author('a1')
        self.assertEqual((author['name'], author['about'], author['percent']), ('Lee Child', 'Jack Reacher', 25))
        self.assertEqual(author['links'], [{'source': 'OpenLibrary', 'url': 'https://openlibrary.org/authors/OL1A'}])
        self.assertEqual(author['ebook_counts'], {'Open': 1, 'Skipped': 2})
        with self.assertRaises(NotFoundError):
            library.get_author('nobody')

    def test_their_books(self):
        found = library.author_books('a1')
        self.assertEqual([b['id'] for b in found], ['b4', 'b3', 'b2', 'b1'], 'Newest first, written with others too')
        self.assertFalse(found[0]['is_primary'])
        self.assertEqual((found[3]['ebook_format'], found[3]['series']),
                         ('EPUB', [{'id': 'OL1', 'name': 'Jack Reacher', 'number': '1'}]))
        self.assertEqual(library.wanted_books('a1'), [{'book_id': 'b4', 'media_type': 'ebook'},
                                                      {'book_id': 'b2', 'media_type': 'audiobook'}])

    def test_wanting_books(self):
        library.set_book_status(['b1', 'b3'], ['ebook'], 'Wanted')
        self.assertEqual(self.statuses()['b1'], ('Open', 'Skipped'), 'One the library has stays')
        self.assertEqual(self.statuses()['b3'], ('Wanted', 'Skipped'))
        library.set_book_status(['b3'], ['ebook', 'audiobook'], 'Ignored')
        self.assertEqual(self.statuses()['b3'], ('Ignored', 'Ignored'))
        for status, kinds in (('Snatched', ['ebook']), ('Wanted', []), ('Wanted', ['comic'])):
            with self.subTest(status=status, kinds=kinds), self.assertRaises(InvalidRequestError):
                library.set_book_status(['b3'], kinds, status)

    def test_the_book_lists(self):
        found = library.list_books('ebook')
        self.assertEqual([(b['id'], b['status'], b['format']) for b in found.items],
                         [('b1', 'Open', 'EPUB'), ('b4', 'Wanted', '')], 'Wanted, snatched or had, by title')
        self.assertEqual(found.items[0]['series'], [{'id': 'OL1', 'name': 'Jack Reacher', 'number': '1'}])
        self.assertEqual([b['id'] for b in library.list_books('audiobook').items], ['b2'])
        self.assertEqual([b['id'] for b in library.list_books('ebook', status='Skipped').items], ['b2', 'b3'])
        self.assertEqual([b['id'] for b in library.list_books('ebook', search='killing').items], ['b1'])
        self.assertEqual([b['id'] for b in library.list_books('ebook', sort='released', descending=True).items],
                         ['b4', 'b1'])
        for args in (('comic',), ('ebook', 'Gone'), ('ebook', '', '', 'pages')):
            with self.subTest(args), self.assertRaises(InvalidRequestError):
                library.list_books(*args)

    def test_manage(self):
        self.assertEqual([b['id'] for b in library.list_books('ebook', status='All').items], ['b2', 'b1', 'b3', 'b4'])
        with mock.patch.object(library, '_owner', return_value='owner'):
            with DBConnection() as db:
                db.action("DELETE FROM users")
                db.action("INSERT INTO users (UserID, UserName) VALUES ('owner', 'owner')")
            self.assertEqual(library.mark_books(['b1'], 'ebook', 'Read')['passed'], 1)
            found = library.list_books('ebook', status='Read').items
            self.assertEqual([(b['id'], b['reading_list']) for b in found], [('b1', 'Read')])
            library.mark_books(['b3'], 'ebook', 'Skipped')
            self.assertEqual(self.statuses()['b3'], ('Skipped', 'Skipped'))
            with DBConnection() as db:
                db.action("INSERT INTO failedsearch (BookID, Library, Time, Interval, Count) VALUES "
                          "('b3', 'eBook', '2026-10-26', 24, 3)")
            row = next(b for b in library.list_books('ebook', status='Skipped').items if b['id'] == 'b3')
            self.assertEqual(row['search'], {'count': 3, 'last': '2026-10-26', 'interval': 24})
            library.mark_books(['b3'], 'ebook', 'NoDelay')
            row = next(b for b in library.list_books('ebook', status='Skipped').items if b['id'] == 'b3')
            self.assertIsNone(row['search'])
        with self.assertRaises(InvalidRequestError):
            library.mark_books(['b1'], 'ebook', 'Snatched')

    def test_a_book(self):
        book = library.get_book('b1')
        self.assertEqual((book['title'], book['author_name'], book['ebook_format']), ('Killing Floor', 'Lee Child', 'EPUB'))
        self.assertEqual(book['series'], [{'id': 'OL1', 'name': 'Jack Reacher', 'number': '1'}])
        self.assertEqual(book['ebook_file'], {'path': '/books/Killing Floor.epub', 'format': 'EPUB', 'size': 0,
                                              'exists': False, 'parts': []})
        self.assertIsNone(book['audio_file'])
        with DBConnection() as db:
            db.action("INSERT INTO wanted (BookID, NZBtitle, NZBprov, NZBdate, Status, AuxInfo, Source, DLResult) "
                      "VALUES ('b1', 'Lee Child - Killing Floor epub', 'Fake', '2026-10-01', 'Processed', 'eBook', "
                      "'SABNZBD', '/books/Killing Floor.epub')")
        self.assertEqual([(d['title'], d['status'], d['media_type']) for d in library.get_book('b1')['downloads']],
                         [('Lee Child - Killing Floor epub', 'Processed', 'ebook')])
        with self.assertRaises(NotFoundError):
            library.get_book('nothere')

    def test_magazines(self):
        with DBConnection() as db:
            db.action("DELETE FROM magazines")
            db.action("INSERT INTO magazines (Title, Status, IssueDate, MagazineAdded, Reject) VALUES "
                      "('Wired', 'Active', '2026-10', '2026-01-01', 'uk')")
            db.action("INSERT INTO issues (Title, IssueID, IssueDate, IssueFile, IssueAcquired) VALUES "
                      "('Wired', 'i1', '2026-10', '/mags/Wired 2026-10.pdf', '2026-10-05'), "
                      "('Wired', 'i2', '2026-09', '', '2026-09-05')")
        self.assertEqual([(m['title'], m['issues'], m['reject_words']) for m in library.list_magazines()],
                         [('Wired', 2, 'uk')])
        wired = library.get_magazine('wired')
        self.assertEqual([(i['id'], i['format']) for i in wired['issue_list']], [('i1', 'PDF'), ('i2', '')])
        self.assertEqual(library.set_magazine_status(['Wired'], 'Paused'), 1)
        self.assertEqual(library.list_magazines()[0]['status'], 'Paused')
        with self.assertRaises(InvalidRequestError):
            library.set_magazine_status(['Wired'], 'Wanted')
        self.assertEqual(library.delete_issues(['i2']), 1)
        self.assertEqual(len(library.get_magazine('Wired')['issue_list']), 1)
        library.delete_magazines(['Wired'])
        self.assertEqual(library.list_magazines(), [])

    def test_comics(self):
        with DBConnection() as db:
            db.action("DELETE FROM comics")
            db.action("INSERT INTO comics (ComicID, Title, Status, Publisher, Start, First, Last) VALUES "
                      "('CV1', 'Saga', 'Active', 'Image', '2012', 1, 54)")
            db.action("INSERT INTO comicissues (ComicID, IssueID, IssueFile, IssueAcquired) VALUES "
                      "('CV1', '1', '/comics/Saga 001.cbz', '2026-10-01'), ('CV1', '2', '', '2026-10-02')")
        self.assertEqual([(c['id'], c['issues'], c['publisher']) for c in library.list_comics()], [('CV1', 2, 'Image')])
        saga = library.get_comic('CV1')
        self.assertEqual(sorted((i['id'], i['format']) for i in saga['issue_list']), [('1', 'CBZ'), ('2', '')])
        self.assertEqual(library.set_comic_status(['CV1'], 'Paused'), 1)
        library.delete_comic_issues('CV1', ['2'])
        self.assertEqual(len(library.get_comic('CV1')['issue_list']), 1)

    def test_series(self):
        with DBConnection() as db:
            db.action("INSERT INTO seriesauthors (SeriesID, AuthorID) VALUES ('OL1', 'a1')")
            db.action("UPDATE series SET Have=1, Total=2 WHERE SeriesID='OL1'")
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('OL1', 'b2', '2')")
        found = library.list_series()
        self.assertEqual([(s['id'], s['name'], s['author_name'], s['percent']) for s in found],
                         [('OL1', 'Jack Reacher', 'Lee Child', 50)])
        reacher = library.get_series('OL1')
        self.assertEqual([(b['number'], b['title'], b['ebook_format']) for b in reacher['books']],
                         [('1', 'Killing Floor', 'EPUB'), ('2', 'Die Trying', '')])
        self.assertEqual(library.set_series_status(['OL1'], 'Paused'), 1)
        self.assertEqual(library.list_series('Paused')[0]['status'], 'Paused')
        with self.assertRaises(NotFoundError):
            library.get_series('nothere')

    def test_taking_a_book_out_of_a_series(self):
        # the reported one: a collection set and another language's edition listed in a series
        from lazylibrarian.bookwork import set_series
        with DBConnection() as db:
            db.action("INSERT INTO seriesauthors (SeriesID, AuthorID) VALUES ('OL1', 'a1')")
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('OL1', 'b2', '1')")
        self.assertEqual(library.remove_from_series('OL1', ['b2']), 1)
        found = library.get_series('OL1')
        self.assertEqual([b['id'] for b in found['books']], ['b1'])
        self.assertEqual(found['removed'], [{'id': 'b2', 'title': 'Die Trying', 'number': '1'}])
        self.assertEqual((found['have'], found['total']), (1, 1), 'Counted again')
        # a source, or a refresh, listing it in the series again
        set_series([('OL1', '1', 'Jack Reacher')], 'b2')
        with DBConnection() as db:
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('OL1', 'b2', '1')")
        self.assertEqual([b['id'] for b in library.get_series('OL1')['books']], ['b1'], 'It stays out')
        self.assertEqual(library.put_back_in_series('OL1', ['b2']), 1)
        found = library.get_series('OL1')
        self.assertEqual(([b['id'] for b in found['books']], found['removed']), (['b1', 'b2'], []))
        with self.assertRaises(InvalidRequestError):
            library.remove_from_series('OL1', [])

    def test_an_ignored_series_is_hidden(self):
        with DBConnection() as db:
            db.action("INSERT INTO seriesauthors (SeriesID, AuthorID) VALUES ('OL1', 'a1')")
        self.assertEqual([s['id'] for s in library.list_series('AllButIgnored')], ['OL1'])
        library.set_series_status(['OL1'], 'Ignored')
        self.assertEqual(library.list_series('AllButIgnored'), [])
        self.assertEqual([s['id'] for s in library.list_series('All')], ['OL1'], 'Shown when asked for')

    def test_a_series_at_its_source(self):
        with DBConnection() as db:
            db.action("INSERT INTO seriesauthors (SeriesID, AuthorID) VALUES ('OL1', 'a1')")
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('OL1', 'b2', '2')")
        # order, title, author, workid, authorid, year, month, day, the source's book id
        members = [['10', 'Running Blind', 'Lee Child', '', 'OL1A', '2000', '', '', ''],
                   ['3', 'Tripwire', 'Lee Child', '', 'OL1A', '1999', '', '', 'OL3W'],
                   ['1', 'Killing Floor', 'Lee Child', '', 'OL1A', '1997', '', '', 'OL1W'],
                   ['2', 'Die Trying', 'Lee Child', '', 'OL1A', '1998', '', '', 'b2']]
        with mock.patch('lazylibrarian.bookwork.get_series_members', return_value=(members, 0, 'OL')) as asked:
            found = library.series_lookup('OL1')
        asked.assert_called_once_with('OL1', 'Jack Reacher', refresh=True)
        self.assertEqual([(b['number'], b['title'], b['in_library'], b['library_id'], b['id'], b['source'])
                          for b in found],
                         [('1', 'Killing Floor', True, 'b1', 'OL1W', 'OpenLibrary'),
                          ('2', 'Die Trying', True, 'b2', 'b2', 'OpenLibrary'),
                          ('3', 'Tripwire', False, '', 'OL3W', 'OpenLibrary'),
                          ('10', 'Running Blind', False, '', '', '')],
                         'In order, by its title, by id, to add, or without an id to add it by')
        self.assertEqual((found[0]['status'], found[1]['audio_status']), ('Open', 'Wanted'))

        # a source that lists none, as GoodReads no longer does: HardCover's series of that name
        saved = CONFIG['HC_API']
        self.addCleanup(CONFIG.set_from_ui, 'HC_API', saved)
        CONFIG.set_from_ui('HC_API', True)
        hardcover = [[3, 'Tripwire', 'Lee Child', 99, 4567, '1999-07-01', 'en']]
        with mock.patch('lazylibrarian.bookwork.get_series_members', return_value=([], 0, 'OL')), \
                mock.patch('lazylibrarian.hc.HardCover.find_series', return_value='HC77') as find, \
                mock.patch('lazylibrarian.hc.HardCover.get_series_members', return_value=hardcover):
            found = library.series_lookup('OL1')
        find.assert_called_once_with('Jack Reacher', 'Lee Child')
        self.assertEqual([(b['number'], b['title'], b['id'], b['source'], b['year'], b['author_id']) for b in found],
                         [('3', 'Tripwire', '4567', 'HardCover', '1999', '99')])

    def test_a_hardcover_series_by_name(self):
        from lazylibrarian.hc import HardCover
        hits = {'data': {'search': {'results': {'hits': [
            {'document': {'id': 1, 'name': 'Temperance Brennan Short Stories', 'author_name': 'Kathy Reichs'}},
            {'document': {'id': 2, 'name': 'Temperance Brennan', 'author_name': 'Someone Else'}},
            {'document': {'id': 3, 'name': 'Temperance Brennan', 'author_name': 'Kathy Reichs'}}]}}}}
        hc = HardCover()
        with mock.patch.object(hc, 'result_from_cache', return_value=(hits, True)):
            self.assertEqual(hc.find_series('Temperance Brennan', 'Kathy Reichs'), 'HC3', 'The name and its author')
            self.assertEqual(hc.find_series('Bones'), '')
        with mock.patch.object(hc, 'result_from_cache', return_value=({'errors': ['no']}, False)):
            self.assertEqual(hc.find_series('Temperance Brennan'), '')

    def test_scan_now(self):
        from lazylibrarian.services import system
        with self.assertRaisesRegex(InvalidRequestError, 'The type is one of'):
            system.scan_now('film')
        saved = CONFIG.get_bool('AUDIO_TAB')
        self.addCleanup(CONFIG.set_bool, 'AUDIO_TAB', saved)
        CONFIG.set_bool('AUDIO_TAB', False)
        with self.assertRaisesRegex(InvalidRequestError, 'switched off'):
            system.scan_now('audiobook')
        told = []
        with mock.patch.object(system.magazinescan, 'magazine_scan') as scan:
            self.assertEqual(system.scan_now('magazine', title='Wired', progress=told.append), 'Wired scan finished')
            system.scan_now('magazine', progress=told.append)
        scan.assert_any_call('Wired')
        with mock.patch('lazylibrarian.comicscan.comic_scan'):
            self.assertEqual(system.scan_now('comic', comic_id='CV999', progress=told.append),
                             'comic CV999 scan finished')
        self.assertEqual(told, ['Scanning Wired', 'Scanning the Magazine library', 'Scanning comic CV999'],
                         'What is being scanned is said as it starts')

    def test_author_status_and_removing(self):
        self.assertEqual(library.set_author_status(['a1', 'a2'], 'Paused'), 2)
        with self.assertRaises(InvalidRequestError):
            library.set_author_status(['a1'], 'Monitored')
        with mock.patch.object(library.authors, 'delete_author_files', return_value=[]) as files:
            self.assertEqual(library.delete_authors(['a2']), 1)
            files.assert_not_called()
            self.assertEqual(library.delete_authors(['a1'], delete_files=True), 1)
            files.assert_called_once()
        self.assertEqual(library.list_authors(), [])
