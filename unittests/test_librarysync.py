#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing functionality in librarysync.py

import os
import shutil
import tempfile

from lazylibrarian import database, librarysync
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import get_directory
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS, LLTestCaseWithStartup


class LibrarySyncTest(LLTestCaseWithConfigandDIRS):

    # Initialisation code that needs to run only once
    @classmethod
    def setUpClass(cls) -> None:
        return super().setUpClass()

    def testGetBookInfo_NoExtension(self):
        # Test reading metadata from book files
        self.assertEqual(librarysync.get_book_info("BookWithNoExtension"), {})

    @staticmethod
    def getTestBook(name):
        return get_directory("Testdata") + os.path.sep + name

    def testGetBookInfo_Epub(self):
        expected_meta = {'type': 'epub', 'title': 'Test Title', 'publisher': 'Testing, Inc', 'language': 'en',
                         'isbn': '9782123456803', 'gb_id': '9876542', 'creator': 'Bob Builder', 'authors': ['Bob Builder']}
        bookfile = self.getTestBook('Test Title - Bob Builder.epub')
        self.assertEqual(librarysync.get_book_info(bookfile), expected_meta)

    def testGetBookInfo_Mobi(self):
        bookfile = self.getTestBook('Test Title - Bob Builder.mobi')
        expected_meta = {'type': 'mobi', 'title': 'Test Title', 'creator': 'Bob Builder',
                         'language': 'en', 'isbn': '9782123456803'}
        self.assertEqual(librarysync.get_book_info(bookfile), expected_meta)

    def testGetBookInfo_Azw3(self):
        bookfile = self.getTestBook('Test Title - Bob Builder.azw3')
        expected_meta = {'type': 'azw3', 'title': 'Test Title', 'creator': 'Bob Builder',
                         'language': 'en', 'isbn': '9782123456803'}
        self.assertEqual(librarysync.get_book_info(bookfile), expected_meta)

    def testGetBookInfo_Opf(self):
        bookfile = self.getTestBook('metadata.opf')
        expected_meta = {'type': 'opf', 'title': 'Test Title', 'publisher': 'Testing, Inc', 'language': 'eng',
                         'isbn': '9782123456803', 'gb_id': '9876542', 'creator': 'Bob Builder', 'authors': ['Bob Builder']}
        self.assertEqual(librarysync.get_book_info(bookfile), expected_meta)

    def testLibraryScan(self):
        # Test library_scan, first with an invalid dir:
        self.assertEqual(librarysync.library_scan("Invalid Start Dir"), 0)

    def test_skip_already_scanned_directory_respects_imp_singlebook(self):
        # Regression coverage: _skip_already_scanned_directory() used to be inlined in
        # library_scan() as `library == 'eBook' and IMP_SINGLEBOOK and already_processed) or
        # (library == 'AudioBook' and already_processed)` -- so AudioBook always skipped an
        # already-processed subdirectory unconditionally, with no way to opt out, unlike
        # eBook which only skips when the user ticks "Import one book per directory"
        # (IMP_SINGLEBOOK). The extracted helper takes no `library` argument at all now:
        # both library types share the exact same IMP_SINGLEBOOK-gated behavior.
        original = CONFIG.get_bool('IMP_SINGLEBOOK')
        try:
            processed = ['/library/SomeAuthor/SomeBook']
            not_yet_processed = '/library/SomeAuthor/AnotherBook'
            already_processed = '/library/SomeAuthor/SomeBook'

            # A subdirectory not yet in processed_subdirectories is never skipped,
            # regardless of IMP_SINGLEBOOK.
            for imp_singlebook in (False, True):
                CONFIG.set_bool('IMP_SINGLEBOOK', imp_singlebook)
                self.assertFalse(
                    librarysync._skip_already_scanned_directory(not_yet_processed, processed))

            # An already-processed subdirectory: skip iff IMP_SINGLEBOOK is set -- this is
            # the actual bug. Previously an AudioBook scan had no way to reach "don't skip"
            # for an already-processed subdirectory at all; this helper has no library
            # parameter precisely because the fix makes both types behave identically.
            CONFIG.set_bool('IMP_SINGLEBOOK', False)
            self.assertFalse(
                librarysync._skip_already_scanned_directory(already_processed, processed))

            CONFIG.set_bool('IMP_SINGLEBOOK', True)
            self.assertTrue(
                librarysync._skip_already_scanned_directory(already_processed, processed))
        finally:
            CONFIG.set_bool('IMP_SINGLEBOOK', original)


class DeriveFallbackAuthornameTest(LLTestCaseWithStartup):
    # _derive_fallback_authorname() always looks authors up in the database now (see below),
    # so these need the heavier LLTestCaseWithStartup fixture rather than the plain
    # LLTestCaseWithConfigandDIRS the rest of this file uses -- same split as
    # ImporterTest/MoveBookToAuthorTest in test_importer.py.

    def _add_author(self, name):
        db = database.DBConnection()
        try:
            db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES (?, ?, ?)",
                      (name, name, 'Active'))
        finally:
            db.close()

    def test_matches_existing_author_over_positional_guess(self):
        # Regression coverage, reproducing the exact scenario that created a bogus author
        # entity live: "William Gibson" is already a known author, but the previous fix
        # (destdir-based, still purely positional) would have derived "Aidoru (1078)" here
        # since that's the first segment under destdir -- a title folder, not an author.
        # Checking segments against known authors instead of guessing by position/shape
        # finds "William Gibson" correctly regardless of which segment position it's in.
        self._add_author('William Gibson')
        destdir = os.path.join('library')
        rootdir = os.path.join('library', 'William Gibson', 'Aidoru (1078)')
        files = 'Aidoru - William Gibson.epub'
        self.assertEqual(
            librarysync._derive_fallback_authorname(rootdir, files, destdir), 'William Gibson')

    def test_uses_library_root_not_scan_startdir(self):
        # Regression coverage: an earlier version of this function took its offset from
        # library_scan()'s own startdir, which only equals the library root (destdir) for a
        # full-library scan. forceLibraryScan's documented dir= parameter lets a scan be
        # scoped to a subdirectory instead (e.g. a single author's folder, to avoid the cost
        # of a full scan) -- in that case startdir is itself the author folder, so an
        # offset taken from it would start from the title folder instead. This case has no
        # matching author in the database, so it falls through to the positional guess --
        # which must still be relative to destdir, not startdir, to land on "Some Author"
        # regardless of how deep into the tree a scan started.
        destdir = os.path.join('library')
        rootdir = os.path.join('library', 'Some Author', 'Some Title (123)')
        files = 'Some Title - Some Author.epub'
        self.assertEqual(
            librarysync._derive_fallback_authorname(rootdir, files, destdir), 'Some Author')

    def test_no_match_falls_back_to_first_segment(self):
        # No segment matches a known author (a genuinely new author, not yet in the
        # database) -- falls back to the first segment under destdir, same as the normal
        # <library root>/<Author>/<Title> convention.
        destdir = os.path.join('library')
        rootdir = os.path.join('library', 'Brand New Author', 'Some Title (123)')
        files = 'Some Title - Brand New Author.epub'
        self.assertEqual(
            librarysync._derive_fallback_authorname(rootdir, files, destdir),
            'Brand New Author')

    def test_calibre_trailing_underscore_restored_on_fallback(self):
        # calibre replaces a trailing period in a folder name with an underscore
        # (e.g. "Smith Jr." -> "Smith Jr_"); restore the period. Only applies on the
        # positional-guess fallback path -- an exact database match is returned as-is.
        destdir = os.path.join('library')
        rootdir = os.path.join('library', 'Smith Jr_', 'Some Title (123)')
        files = 'Some Title - Smith Jr_.epub'
        self.assertEqual(
            librarysync._derive_fallback_authorname(rootdir, files, destdir), 'Smith Jr.')


class LibraryScanBookFileTest(LLTestCaseWithStartup):

    def test_bookfile_stored_without_opf_or_rename(self):
        # book_filename used to be set only when IMP_EBOOKOPF or IMP_RENAME was on, so with
        # both off the scan raised TypeError and left the book Open with no BookFile
        saved = {key: CONFIG.get_bool(key) for key in ('IMP_EBOOKOPF', 'IMP_RENAME')}
        saved_dir = CONFIG['EBOOK_DIR']
        db = database.DBConnection()
        try:
            CONFIG.set_bool('IMP_EBOOKOPF', False)
            CONFIG.set_bool('IMP_RENAME', False)
            db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES (?, ?, ?)",
                      ('BB1', 'Bob Builder', 'Active'))
            db.action("INSERT OR REPLACE INTO books (BookID, AuthorID, BookName, Status, gb_id, BookIsbn) "
                      "VALUES (?, ?, ?, ?, ?, ?)",
                      ('9876542', 'BB1', 'Test Title', 'Wanted', '9876542', '9782123456803'))
            with tempfile.TemporaryDirectory() as library:
                folder = os.path.join(library, 'Bob Builder', 'Test Title')
                os.makedirs(folder)
                shutil.copy(os.path.join(get_directory('Testdata'), 'Test Title - Bob Builder.epub'), folder)
                CONFIG['EBOOK_DIR'] = library
                librarysync.library_scan(startdir=library, library='eBook', remove=False)
                book = db.match("SELECT Status, BookFile FROM books WHERE BookID=?", ('9876542',))
                self.assertEqual(book['Status'], 'Open')
                self.assertEqual(book['BookFile'], os.path.join(folder, 'Test Title - Bob Builder.epub'))
        finally:
            db.action("DELETE FROM books WHERE BookID=?", ('9876542',))
            db.action("DELETE FROM authors WHERE AuthorID=?", ('BB1',))
            db.close()
            for key, value in saved.items():
                CONFIG.set_bool(key, value)
            CONFIG['EBOOK_DIR'] = saved_dir
