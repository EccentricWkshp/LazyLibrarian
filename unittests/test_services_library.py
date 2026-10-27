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
