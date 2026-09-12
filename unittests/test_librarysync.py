#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing functionality in librarysync.py

import os

from lazylibrarian import librarysync
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import get_directory
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


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
