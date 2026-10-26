#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/wall.py

from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import wall
from unittests.unittesthelpers import LLTestCaseWithDB


class WallServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.addCleanup(CONFIG.set_from_ui, 'MAX_WALL', CONFIG['MAX_WALL'])
        self.addCleanup(CONFIG.set_from_ui, 'WALL_COLUMNS', CONFIG['WALL_COLUMNS'])
        CONFIG.set_int('MAX_WALL', 0)
        self.sql("INSERT INTO authors (AuthorID,AuthorName,Status) VALUES ('A1','Anne','Active'),('A2','Bob','Paused')")
        for i, status in enumerate(('Open', 'Skipped', 'Open')):
            self.sql("INSERT INTO books (BookID,AuthorID,BookName,Status,AudioStatus,BookLink,BookAdded,BookLibrary) "
                     "VALUES (?,'A1',?,?,'Open','/works/OL1W',?,?)",
                     (f'B{i}', f'Book {i}', status, f'2026-01-0{i + 1}', f'2026-02-0{i + 1}'))

    def test_thumbnail(self):
        self.assertEqual(wall.thumbnail(None), wall.NO_COVER)
        self.assertEqual(wall.thumbnail('images/x.jpg'), wall.NO_COVER)
        with mock.patch.object(wall, 'cover_thumbnail', return_value=('cache/x_w200.jpg', 'cache/x.jpg')):
            self.assertEqual(wall.thumbnail('cache/x.jpg'), 'cache/x_w200.jpg')

    def test_book_wall(self):
        books, more = wall.book_wall()
        self.assertEqual(([b['BookID'] for b in books], more), (['B2', 'B1', 'B0'], False))
        self.assertTrue(books[0]['BookLink'].endswith('/works/OL1W'))
        self.assertEqual([b['BookID'] for b in wall.book_wall(downloaded=True)[0]], ['B2', 'B0'])

    def test_max_wall(self):
        CONFIG.set_int('MAX_WALL', 2)
        books, more = wall.book_wall()
        self.assertEqual((len(books), more), (2, True))
        self.assertEqual(wall.audio_wall()[1], True)
        CONFIG.set_int('MAX_WALL', 3)
        self.assertEqual(wall.book_wall()[1], False, 'Exactly the maximum')

    def test_author_wall(self):
        self.assertEqual([a['AuthorID'] for a in wall.author_wall()], ['A1'])
        self.assertEqual([a['AuthorID'] for a in wall.author_wall(active=False)], ['A2'])

    def test_change_columns(self):
        CONFIG.set_int('WALL_COLUMNS', 13)
        self.assertEqual(wall.change_columns('up'), 13)
        self.assertEqual(wall.change_columns('down'), 12)
        CONFIG.set_int('WALL_COLUMNS', 1)
        self.assertEqual(wall.change_columns('down'), 1)
