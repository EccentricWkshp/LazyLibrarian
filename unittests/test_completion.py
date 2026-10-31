#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test completion.py, a book's and an author's missing details filled in from every info source,
#   with made-up sources: one that gives a whole book by its id, one that only has search results

import datetime
import json
from unittest import mock

import lazylibrarian
from lazylibrarian import completion
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import commands
from unittests.unittesthelpers import LLTestCaseWithDB

# before the test cases put it aside
_real_found_cover = completion._found_cover

# the books and authors the made-up sources have
WHOLE = {'hc1': {'bookid': 'hc1', 'bookname': 'Killing Floor', 'authorname': 'Lee Child', 'authorid': 'hca1',
                 'booksub': 'A Jack Reacher Novel', 'bookisbn': '9780515153651', 'bookpub': 'Jove',
                 'bookpages': 524, 'bookdate': '1997-03-17', 'booklang': 'English', 'bookgenre': 'Thriller, Crime',
                 'bookrate': 4.1, 'bookimg': 'https://hc.example/cover.jpg',
                 'bookdesc': 'Jack Reacher walks into Margrave, Georgia, and is arrested for murder.',
                 'series': [('Jack Reacher', 'HC9', '1')]},
         'hc2': {'bookid': 'hc2', 'bookname': 'Dune Messiah', 'authorname': 'Frank Herbert', 'bookpages': 256,
                 'bookisbn': '9780441013593',
                 'bookdesc': 'The second book of Dune, twelve years after Paul took the throne.'}}
FOUND = {'killing floor': ['hc1'], 'dune': ['hc2'], '0441013597': ['hc2']}
AUTHORS = {'hca1': {'authorid': 'hca1', 'authorname': 'Lee Child', 'authorborn': '1954-10-29',
                    'about': 'James Grant, known as Lee Child, is a British author of thrillers.',
                    'authorimg': 'https://hc.example/lee.jpg'},
           'hca2': {'authorid': 'hca2', 'authorname': 'Leigh Childs', 'about': 'Someone else entirely, a poet.'}}


class WholeSource:
    """ A source that gives a whole book by its id, and finds authors """
    asked = []

    def get_bookdict_for_bookid(self, bookid=None):
        WholeSource.asked.append(bookid)
        return dict(WHOLE[bookid]) if bookid in WHOLE else {}, False

    def find_author_id(self, authorname='', title='', refresh=False):
        return {'authorid': 'hca2' if authorname == 'Lee Childs' else 'hca1'}

    def get_author_info(self, authorid=None, authorname=None, refresh=False):
        return dict(AUTHORS.get(authorid, {}))


class SearchSource:
    """ A source with only search results, for its own books too """


def search_for(term, source=None, max_pages=0):
    """ What the made-up sources find for "title<ll>author" or an ISBN """
    if source != 'HardCover':
        return [{'bookid': 'ol9', 'bookname': 'Killing Floor', 'authorname': 'Lee Child', 'bookrate': 3.9,
                 'bookdate': '1997', 'highest_fuzz': 100}] if 'Killing Floor' in term else []
    title = term.split('<ll>')[0].lower()
    return [{**WHOLE[bookid], 'bookdesc': '', 'highest_fuzz': 90} for bookid in FOUND.get(title, [])]


class CompletionTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        sources = {'HardCover': {'src': 'HC', 'book_key': 'hc_id', 'author_key': 'hc_id', 'enabled': 'HC_API',
                                 'api': WholeSource},
                   'OpenLibrary': {'src': 'OL', 'book_key': 'ol_id', 'author_key': 'ol_id', 'enabled': 'OL_API',
                                   'api': SearchSource}}
        for patcher in (mock.patch.object(lazylibrarian, 'INFOSOURCES', sources),
                        mock.patch.object(completion, '_sources', lambda own='': [own] * bool(own) + [
                            name for name in ('HardCover', 'OpenLibrary') if name != own]),
                        mock.patch('lazylibrarian.importer.search_for', search_for),
                        mock.patch('lazylibrarian.images.cache_bookimg', lambda img, bookid, src: f'cache/book/{bookid}.jpg'),
                        mock.patch('lazylibrarian.cache.cache_img', lambda kind, name, img, **kw: (f'cache/author/{name}.jpg',
                                                                                                  True, False))):
            patcher.start()
            self.addCleanup(patcher.stop)
        WholeSource.asked = []
        self.sql("INSERT INTO authors (AuthorID, AuthorName, Status, AuthorImg) VALUES "
                 "('OL1A', 'Lee Child', 'Active', 'images/nophoto.png')")
        self.sql("INSERT INTO books (BookID, AuthorID, BookName, ol_id, BookDesc, BookPub, BookImg, BookLang, Status, "
                 "AudioStatus, BookAdded) VALUES ('OL1W', 'OL1A', 'Killing Floor', 'OL1W', 'Not available', "
                 "'Putnam', 'images/nocover.png', 'Unknown', 'Open', 'Skipped', '2026-01-01')")

    def book(self):
        return self.sql("SELECT * FROM books WHERE BookID='OL1W'")[0]

    def test_a_book_completed_from_the_others(self):
        filled = completion.complete_book('OL1W')
        book = self.book()
        self.assertEqual(book['BookDesc'], WHOLE['hc1']['bookdesc'], 'A placeholder is no description')
        self.assertEqual((book['BookIsbn'], book['BookPages'], book['BookDate'], book['BookLang'], book['BookSub']),
                         ('9780515153651', 524, '1997-03-17', 'English', 'A Jack Reacher Novel'))
        self.assertEqual(book['BookPub'], 'Putnam', 'What it has is never changed')
        self.assertEqual(book['BookImg'], 'cache/book/OL1W.jpg', 'The cover kept in the cache')
        self.assertEqual(book['BookGenre'], 'Thriller, Crime')
        self.assertEqual(book['hc_id'], 'hc1', 'Its id at the source that has it, for the next time')
        self.assertEqual(WholeSource.asked, ['hc1'], 'The whole book once it was found')
        self.assertEqual(book['Completed'], datetime.date.today().isoformat())
        self.assertEqual(json.loads(book['FilledFrom'])['BookDesc'], 'HardCover')
        self.assertEqual(filled['Series'], 'HardCover')
        self.assertEqual([row['SeriesName'] for row in self.sql("SELECT SeriesName FROM series,member WHERE "
                                                                 "series.SeriesID=member.SeriesID AND BookID='OL1W'")],
                         ['Jack Reacher'])
        self.assertEqual(self.sql("SELECT GenreName FROM genres ORDER BY GenreName"),
                         [{'GenreName': 'Crime'}, {'GenreName': 'Thriller'}])
        self.assertEqual(json.loads(book['FilledFrom'])['BookDate'], 'HardCover', "OpenLibrary's year gave way")
        self.assertEqual(completion.described({'BookDesc': 'HardCover', 'BookPages': 'HardCover',
                                               'BookImg': 'GoogleBooks'}),
                         'description and pages from HardCover, cover from GoogleBooks')

    def test_asked_again_only_when_due(self):
        completion.complete_book('OL1W')
        self.sql("UPDATE books SET BookPages=0 WHERE BookID='OL1W'")
        self.assertEqual(completion.complete_book('OL1W'), {}, 'Asked today')
        self.assertEqual(completion.complete_book('OL1W', force=True), {'BookPages': 'HardCover'})
        self.assertEqual(completion.due_books(), [])
        old = (datetime.date.today() - datetime.timedelta(days=CONFIG.get_int('CACHE_AGE') + 1)).isoformat()
        self.sql("UPDATE books SET Completed=?, BookPages=0 WHERE BookID='OL1W'", (old,))
        self.assertEqual(completion.due_books(), ['OL1W'])

    def test_a_book_edited_by_hand_is_left(self):
        self.sql("UPDATE books SET Manual='1' WHERE BookID='OL1W'")
        self.assertEqual(completion.complete_book('OL1W', force=True), {})
        self.assertEqual(self.book()['BookDesc'], 'Not available')
        self.assertEqual(completion.due_books(), [])

    def test_only_the_same_book(self):
        """ Another book of the same author whose title starts the same isn't this one; one with the
        same ISBN is, whatever its title """
        self.sql("INSERT INTO authors (AuthorID, AuthorName, Status) VALUES ('OL2A', 'Frank Herbert', 'Active')")
        self.sql("INSERT INTO books (BookID, AuthorID, BookName, ol_id, Status, AudioStatus) VALUES "
                 "('OL2W', 'OL2A', 'Dune', 'OL2W', 'Open', 'Skipped')")
        self.assertEqual(completion.complete_book('OL2W'), {}, 'Dune Messiah is not Dune')
        self.sql("UPDATE books SET BookIsbn='0441013597', Completed='' WHERE BookID='OL2W'")
        self.assertIn('BookPages', completion.complete_book('OL2W'), 'Its ISBN, as 13 digits, is the same')
        self.assertTrue(completion.same_book({'BookName': 'Killing Floor (Jack Reacher, #1)', 'BookIsbn': ''},
                                             'Lee Child', {'bookname': 'Killing Floor: A Novel',
                                                           'authorname': 'Child, Lee'}))
        self.assertFalse(completion.same_book({'BookName': 'Killing Floor', 'BookIsbn': ''}, 'Lee Child',
                                              {'bookname': 'Killing Floor', 'authorname': 'Lisa Childers'}))

    def test_a_cover_found_elsewhere(self):
        """ A book no source has a cover for gets one where covers are looked for, by the ISBN filled in """
        WHOLE['hc1']['bookimg'], saved = '', WHOLE['hc1']['bookimg']
        self.addCleanup(WHOLE['hc1'].__setitem__, 'bookimg', saved)
        looked = {}

        def get_book_cover(bookid):
            looked.update(self.sql("SELECT BookIsbn, hc_id FROM books WHERE BookID=?", (bookid,))[0])
            return 'cache/book/OL1W.jpg', 'openlibrary'

        with mock.patch.object(completion, '_found_cover', _real_found_cover), \
                mock.patch('lazylibrarian.images.get_book_cover', get_book_cover):
            filled = completion.complete_book('OL1W')
        self.assertEqual(looked, {'BookIsbn': '9780515153651', 'hc_id': 'hc1'}, 'With what was filled in')
        self.assertEqual((filled['BookImg'], self.book()['BookImg']), ('OpenLibrary', 'cache/book/OL1W.jpg'))

    def test_missing(self):
        for column, value in (('BookDesc', 'No Description'), ('BookDesc', ''), ('BookImg', 'images/nocover.png'),
                              ('BookPages', '0'), ('BookLang', 'Unknown'), ('BookDate', '0000'),
                              ('AuthorImg', 'images/nophoto.png'), ('BookRate', None)):
            self.assertTrue(completion.is_missing(column, value), (column, value))
        for column, value in (('BookDesc', 'A long enough description'), ('BookPages', 12), ('BookLang', 'en'),
                              ('BookDate', '1997')):
            self.assertFalse(completion.is_missing(column, value), (column, value))

    def test_an_author_completed(self):
        filled = completion.complete_author('OL1A')
        author = self.sql("SELECT * FROM authors WHERE AuthorID='OL1A'")[0]
        self.assertEqual(filled, {'About': 'HardCover', 'AuthorBorn': 'HardCover', 'AuthorImg': 'HardCover'})
        self.assertEqual((author['AuthorBorn'], author['hc_id']), ('1954-10-29', 'hca1'))
        self.assertTrue(author['AuthorImg'].startswith('cache/author/'))
        self.assertEqual(author['Completed'], datetime.date.today().isoformat())

    def test_another_sources_id_isnt_asked_for(self):
        """ An author from OpenLibrary, with Hardcover the main source, is found at Hardcover by name,
        their OpenLibrary id isn't asked for there """
        asked = []

        def get_author_info(_self, authorid=None, authorname=None, refresh=False):
            asked.append(authorid)
            return dict(AUTHORS.get(authorid, {}))

        saved = CONFIG['BOOK_API']
        self.addCleanup(CONFIG.__setitem__, 'BOOK_API', saved)
        CONFIG['BOOK_API'] = 'HardCover'
        self.sql("UPDATE authors SET PrimarySource='OpenLibrary' WHERE AuthorID='OL1A'")
        with mock.patch.object(WholeSource, 'get_author_info', get_author_info):
            self.assertIn('About', completion.complete_author('OL1A'))
        self.assertEqual(asked, ['hca1'])

    def test_not_an_author_of_another_name(self):
        self.sql("UPDATE authors SET AuthorName='Lee Childs' WHERE AuthorID='OL1A'")
        self.assertEqual(completion.complete_author('OL1A'), {}, 'Leigh Childs is someone else')
        self.assertIsNone(self.sql("SELECT hc_id FROM authors WHERE AuthorID='OL1A'")[0]['hc_id'])

    def test_the_command(self):
        with mock.patch.object(commands, '_update'):
            message = commands._complete_books({}, {'ids': ['OL1W']})
        self.assertEqual(message, 'Filled in details of 1 of 1 book')
        self.assertEqual(self.book()['hc_id'], 'hc1')
        with mock.patch.object(commands, '_update'):
            message = commands._complete_books({}, {})
        self.assertEqual(message, 'Filled in details of 0 of 0 books and 1 of 1 author')
