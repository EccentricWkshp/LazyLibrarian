#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test what keeps a book's files and series its own: a file found by a library scan stays the
#   book's it is the file of (librarysync.file_owner), an audiobook is all its parts
#   (library.audio_parts), and a source's series are added to a book's, not put in their place
#   (bookwork.set_series)

import os
import shutil
import tempfile

from lazylibrarian.bookwork import set_series
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.librarysync import file_owner, known_file
from lazylibrarian.services import library
from unittests.unittesthelpers import LLTestCaseWithStartup


class BookFilesTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.secret = os.path.join(self.root, 'Lee Child', 'The Secret')
        os.makedirs(self.secret)
        for name in ('02 The Secret - Chapter 01.mp3', '02 The Secret - Chapter 10.mp3',
                     '02 The Secret - Chapter 2.mp3', 'cover.jpg'):
            with open(os.path.join(self.secret, name), 'wb') as f:
                f.write(b'x' * 10)
        self.first = os.path.join(self.secret, '02 The Secret - Chapter 01.mp3')
        self.epub = os.path.join(self.root, 'Lee Child - Persuader.epub')
        with DBConnection() as db:
            for table in ('books', 'authors', 'series', 'member'):
                db.action(f"DELETE FROM {table}")
            db.action("INSERT INTO authors (AuthorID, AuthorName) VALUES ('a1', 'Lee Child')")
            for book_id, name, added, audio, status, bookfile, ebook in (
                    ('62983544', 'The Secret', '2026-10-04', self.first, 'Open', self.epub, 'Open'),
                    # the same book added again by a later scan, from another source, with the same files
                    ('1978764', 'Jack Reacher', '2026-10-25', self.first, 'Open', self.epub, 'Open')):
                db.action("INSERT INTO books (BookID, AuthorID, BookName, BookAdded, AudioFile, AudioStatus, BookFile, "
                          "Status) VALUES (?, 'a1', ?, ?, ?, ?, ?, ?)", (book_id, name, added, audio, status, bookfile,
                                                                        ebook))

    @staticmethod
    def rows(sql, args=()):
        with DBConnection() as db:
            return [tuple(row) for row in db.select(sql, args)]

    def test_an_audiobook_is_the_first_added_books(self):
        saved = CONFIG.get_bool('IMP_SINGLEBOOK')
        self.addCleanup(CONFIG.set_from_ui, 'IMP_SINGLEBOOK', saved)
        CONFIG.set_from_ui('IMP_SINGLEBOOK', True)
        with DBConnection() as db:
            owner = file_owner(db, 'AudioBook', self.secret, '02 The Secret - Chapter 10.mp3')
        self.assertEqual(owner['BookID'], '62983544', 'By its folder, any part')
        self.assertEqual(self.rows("SELECT AudioFile, AudioStatus FROM books WHERE BookID='1978764'"),
                         [('', CONFIG['NOTFOUND_STATUS'])], 'The other lets go of it')
        self.assertEqual(self.rows("SELECT BookFile FROM books WHERE BookID='1978764'"), [(self.epub,)],
                         'Its ebook is another file')

    def test_an_ebook_by_any_of_its_formats(self):
        with DBConnection() as db:
            owner = file_owner(db, 'eBook', self.root, 'Lee Child - Persuader.mobi')
            self.assertEqual(owner['BookID'], '62983544')
            self.assertIsNone(file_owner(db, 'eBook', self.root, 'Somebody Else.epub'))
        self.assertEqual(self.rows("SELECT BookFile, Status FROM books WHERE BookID='1978764'"),
                         [('', CONFIG['NOTFOUND_STATUS'])])

    def test_a_known_file_is_left(self):
        """ A scan leaves a file the library has as it is, unless it's a format preferred to the
        book's, its author is unknown, or the book isn't in the library """
        saved = CONFIG['EBOOK_TYPE']
        self.addCleanup(CONFIG.set_from_ui, 'EBOOK_TYPE', saved)
        CONFIG.set_from_ui('EBOOK_TYPE', 'epub, mobi')
        with DBConnection() as db:
            db.action("DELETE FROM books WHERE BookID='1978764'")
            self.assertEqual(known_file(db, 'eBook', self.root, 'Lee Child - Persuader.epub'), '62983544')
            self.assertEqual(known_file(db, 'eBook', self.root, 'Lee Child - Persuader.mobi'), '62983544')
            db.action("UPDATE books SET BookFile=? WHERE BookID='62983544'", (self.epub.replace('.epub', '.mobi'),))
            self.assertEqual(known_file(db, 'eBook', self.root, 'Lee Child - Persuader.epub'), '',
                             'The epub is preferred to the mobi it has')
            db.action("UPDATE books SET Status='Skipped' WHERE BookID='62983544'")
            self.assertEqual(known_file(db, 'eBook', self.root, 'Lee Child - Persuader.mobi'), '')
            self.assertEqual(known_file(db, 'AudioBook', self.secret, '02 The Secret - Chapter 01.mp3'), '62983544')
            db.action("UPDATE authors SET AuthorName='Unknown Author'")
            self.assertEqual(known_file(db, 'AudioBook', self.secret, '02 The Secret - Chapter 01.mp3'), '')

    def test_an_audiobooks_parts(self):
        self.assertEqual([os.path.basename(part) for part in library.audio_parts(self.first)],
                         ['02 The Secret - Chapter 01.mp3', '02 The Secret - Chapter 2.mp3',
                          '02 The Secret - Chapter 10.mp3'], 'Its audio files, part 2 before part 10')

    def test_a_sources_series_are_added(self):
        # the reported one: a refresh from GoodReads took away a series from another source
        with DBConnection() as db:
            for series_id, name in (('HC1', 'Jack Reacher Chronological Order'), ('GR2', 'Jack Reacher')):
                db.action("INSERT INTO series (SeriesID, SeriesName, Status) VALUES (?, ?, 'Paused')", (series_id, name))
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('HC1', '62983544', '12')")
        set_series([('GR2', '28', 'Jack Reacher')], '62983544')
        self.assertEqual(self.rows("SELECT SeriesID, SeriesNum FROM member ORDER BY SeriesID"),
                         [('GR2', '28'), ('HC1', '12')])
        set_series([], '62983544')
        self.assertEqual(len(self.rows("SELECT * FROM member")), 2, 'None found is no reason to lose them')
        set_series([('GR2', '27', 'Jack Reacher')], '62983544', replace=True)
        self.assertEqual(self.rows("SELECT SeriesID, SeriesNum FROM member"), [('GR2', '27')], 'As edited')
