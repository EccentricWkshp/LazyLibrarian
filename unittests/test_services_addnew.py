#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test Add New (services/addnew.py): looking authors, books, magazines and comics up, and adding
#   them, with the info sources and the download search mocked

import time
from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.services import InvalidRequestError, addnew, commands, magazines
from unittests.unittesthelpers import LLTestCaseWithStartup


def _result(bookid, title, authorid='ol1', author='Lee Child', fuzz=90.0):
    return {'authorname': author, 'bookid': bookid, 'authorid': authorid, 'bookname': title, 'booksub': '',
            'bookisbn': '', 'bookpub': '', 'bookdate': '2004', 'booklang': 'en', 'booklink': '', 'bookrate': 4.1,
            'bookrate_count': 10, 'bookimg': 'http://covers/x.jpg', 'bookpages': 300, 'bookgenre': '',
            'bookdesc': '', 'workid': '', 'author_fuzz': fuzz, 'book_fuzz': fuzz, 'isbn_fuzz': 0,
            'highest_fuzz': fuzz, 'source': 'OpenLibrary'}


class AddNewTestCase(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        for setting in ('EBOOK_TAB', 'AUDIO_TAB'):
            saved = CONFIG.get_bool(setting)
            self.addCleanup(CONFIG.set_bool, setting, saved)
            CONFIG.set_bool(setting, True)
        with DBConnection() as db:
            for table in ('books', 'authors', 'magazines', 'comics'):
                db.action(f"DELETE FROM {table}")

    def author_loads(self, *args):
        """ What add_author_to_db does: the author and their books, as the settings want them """
        with DBConnection() as db:
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status) VALUES ('ol1', 'Lee Child', 'Active')")
            for bookid, name, status in (('b1', 'Killing Floor', 'Skipped'), ('b2', 'Die Trying', 'Skipped'),
                                         ('b3', 'Tripwire', 'Open')):
                db.action("INSERT INTO books (BookID, AuthorID, BookName, Status, AudioStatus) VALUES "
                          "(?, 'ol1', ?, ?, 'Skipped')", (bookid, name, status))
        return 'ol1'

    def statuses(self) -> dict:
        with DBConnection() as db:
            return {row['BookID']: (row['Status'], row['AudioStatus'])
                    for row in db.select('SELECT BookID, Status, AudioStatus FROM books')}


class LookupTest(AddNewTestCase):

    def test_authors_and_books(self):
        self.author_loads()
        found = {'results': [_result('b1', 'Killing Floor'), _result('x9', 'Jack Reacher', 'ol2', 'Andrew Child', 70),
                             _result('b9', 'Persuader')],
                 'authorlist': ['ol1'], 'loadlist': [], 'booklist': ['b1'],
                 'booksearch': [{'BookID': 'b1', 'Status': 'Skipped', 'AudioStatus': 'Skipped'}]}
        with mock.patch.object(addnew.authors, 'search_sources', return_value=found):
            looked = addnew.lookup('lee child')
        self.assertEqual([(a['id'], a['name'], a['books'], a['in_library']) for a in looked['authors']],
                         [('ol1', 'Lee Child', 2, True), ('ol2', 'Andrew Child', 1, False)])
        self.assertEqual([(b['id'], b['in_library'], b['status']) for b in looked['books']],
                         [('b1', True, 'Skipped'), ('x9', False, ''), ('b9', False, '')])
        self.assertEqual(looked['books'][0]['cover'], 'http://covers/x.jpg')
        # OpenLibrary gives the year it was first published as the publisher
        year = {**_result('b5', 'Echo Burning'), 'bookpub': 2001, 'bookdate': '', 'bookisbn': None}
        with mock.patch.object(addnew.authors, 'search_sources', return_value={**found, 'results': [year]}):
            book = addnew.lookup('echo burning')['books'][0]
        self.assertEqual((book['publisher'], book['release_date'], book['isbn']), ('', '2001', ''))
        with self.assertRaises(InvalidRequestError):
            addnew.lookup('  ')


class AddAuthorTest(AddNewTestCase):

    def add(self, monitor, **kwargs):
        with mock.patch.object(addnew, 'add_author_to_db', side_effect=self.author_loads):
            return addnew.add_author('ol1', 'Lee Child', monitor, **kwargs)

    def test_new_books_only(self):
        message, added = self.add('new')
        self.assertEqual(message, 'Added Lee Child, 3 books')
        self.assertEqual(added, {'author_id': 'ol1', 'author_name': 'Lee Child'})
        self.assertEqual(self.statuses()['b1'], ('Skipped', 'Skipped'), 'As the settings said')

    def test_all_books(self):
        self.add('all', kinds=['ebook'])
        self.assertEqual(self.statuses(), {'b1': ('Wanted', 'Skipped'), 'b2': ('Wanted', 'Skipped'),
                                           'b3': ('Open', 'Skipped')})

    def test_none_pauses_the_author(self):
        self.add('none')
        with DBConnection() as db:
            self.assertEqual(db.match("SELECT Status FROM authors WHERE AuthorID='ol1'")['Status'], 'Paused')

    def test_search_for_the_wanted_books(self):
        with mock.patch.object(addnew.wanted, 'search_books', return_value=(1, 'Found 1')) as search:
            message, _ = self.add('all', kinds=['audiobook'], search=True)
        self.assertEqual(sorted(b['book_id'] for b in search.call_args.args[0]), ['b1', 'b2', 'b3'])
        self.assertTrue(message.endswith('. Found 1'), message)
        with mock.patch.object(addnew.wanted, 'search_books', side_effect=InvalidRequestError('No providers')):
            with DBConnection() as db:
                db.action('DELETE FROM books')
                db.action('DELETE FROM authors')
            message, _ = self.add('all', search=True)
        self.assertIn('Not searched: No providers', message)

    def test_one_there_already(self):
        self.author_loads()
        with self.assertRaisesRegex(InvalidRequestError, 'Lee Child is in the library already'):
            self.add('new')
        with self.assertRaisesRegex(InvalidRequestError, 'Monitor is one of'):
            addnew.add_author('ol9', '', 'some')


class AddBookTest(AddNewTestCase):

    def test_a_format_we_have_stays(self):
        self.author_loads()
        with DBConnection() as db:
            db.action("UPDATE books SET AudioStatus='Open' WHERE BookID='b1'")
        message, added = addnew.add_book('b1', kinds=['ebook'])
        self.assertEqual(message, 'Added Killing Floor')
        self.assertEqual(added['author_id'], 'ol1')
        self.assertEqual(self.statuses()['b1'], ('Wanted', 'Open'))
        addnew.add_book('b3', kinds=['ebook', 'audiobook'])
        self.assertEqual(self.statuses()['b3'], ('Open', 'Wanted'), 'An owned eBook stays owned')

    def test_search(self):
        self.author_loads()
        with mock.patch.object(addnew.wanted, 'search_books', return_value=(0, 'Nothing found')) as search:
            addnew.add_book('b2', kinds=['audiobook'], search=True)
        self.assertEqual(search.call_args.args[0], [{'book_id': 'b2', 'media_type': 'audiobook'}])


class AuthorLookupTest(AddNewTestCase):

    def test_their_books_at_the_sources(self):
        from lazylibrarian.services import library
        self.author_loads()

        def book(book_id, title, author_id='ol1', author='Lee Child', date='', in_library=False):
            return {'id': book_id, 'title': title, 'author_id': author_id, 'author_name': author,
                    'release_date': date, 'in_library': in_library, 'status': '', 'audio_status': ''}

        found = {'authors': [], 'books': [
            book('b1', 'Killing Floor', date='1997', in_library=True),
            book('x1', 'Killing Floor!', 'hc9', date='1997'),
            book('x2', 'Die Trying', 'hc9', 'lee child', '1998'),
            book('x3', 'Persuader', 'hc9', 'Lee Child', '2003'),
            book('x4', 'Make Me', 'ol1', 'Lee Child'),
            book('x5', 'Gone Tomorrow', 'ol5', 'Someone Else', '2009')]}
        with mock.patch.object(addnew, 'lookup', return_value=found) as lookup:
            books = library.author_lookup('ol1')
        lookup.assert_called_once_with('Lee Child', max_pages=library.AUTHOR_LOOKUP_PAGES)
        self.assertEqual([(b['id'], b['title'], b['in_library']) for b in books],
                         [('x3', 'Persuader', False), ('x4', 'Make Me', False), ('b2', 'Die Trying', True),
                          ('b1', 'Killing Floor', True)],
                         "Theirs by id or name, once per title, the ones the library hasn't got first, newest first")
        self.assertEqual(books[2]['status'], 'Skipped', "Another source's copy is the library's own")


class MagazineTest(AddNewTestCase):

    def test_lookup_and_add(self):
        magazines.add_magazine('Wired Magazine', search=False)
        with mock.patch.object(addnew.wikidata, 'search', return_value=[]):
            found = addnew.lookup_magazine('Wired')
            self.assertEqual([(m['title'], m['in_library']) for m in found],
                             [('Wired', False), ('Wired Magazine', True)])
            self.assertEqual(addnew.lookup_magazine('wired magazine'),
                             [{'title': 'Wired Magazine', 'reject_words': '', 'in_library': True, 'issues': 0,
                               'wikidata_id': '', 'description': '', 'started': ''}])
            self.assertEqual(addnew.lookup_magazine('Wired ~ uk, kids')[0]['reject_words'], 'uk, kids')
        with mock.patch('lazylibrarian.services.commands.start') as start:
            self.assertEqual(addnew.add_magazine('Wired', 'uk, kids', wikidata_id='Q520154'), {'title': 'Wired'})
        start.assert_called_once_with('RefreshMagazine', {'title': 'Wired', 'wikidata_id': 'Q520154'})
        with DBConnection() as db:
            self.assertEqual(db.match("SELECT Reject FROM magazines WHERE Title='Wired'")['Reject'], 'uk, kids')
        with self.assertRaisesRegex(InvalidRequestError, 'in the library already'):
            addnew.add_magazine('wired')

    def test_wikidata_matches(self):
        magazines.add_magazine('Wired', search=False)
        with DBConnection() as db:
            db.action("UPDATE magazines SET WikidataID='Q520154' WHERE Title='Wired'")
        matches = [{'id': 'Q520154', 'label': 'Wired', 'description': 'American magazine', 'started': '1993'},
                   {'id': 'Q8026784', 'label': 'Wired UK', 'description': 'British edition', 'started': '2009'}]
        with mock.patch.object(addnew.wikidata, 'search', return_value=matches):
            found = addnew.lookup_magazine('wired')
        self.assertEqual([(m['title'], m['in_library'], m['wikidata_id']) for m in found],
                         [('Wired', True, 'Q520154'), ('Wired UK', False, 'Q8026784')],
                         'One linked already is the library one, the others can be added')
        self.assertEqual(found[1]['description'], 'British edition')


class ComicTest(AddNewTestCase):

    def test_lookup_and_add(self):
        found = [{'seriesid': 'CV123', 'title': 'Saga', 'publisher': 'Image', 'start': '2012', 'first': 1,
                  'last': 54, 'count': 54, 'description': 'Space opera', 'link': 'http://cv/123',
                  'searchterm': 'saga', 'fuzz': 100}]
        with mock.patch.object(addnew.comics, 'find_comics', return_value=found):
            looked = addnew.lookup_comic('Saga')
        self.assertEqual((looked[0]['id'], looked[0]['issues'], looked[0]['in_library']), ('CV123', 54, False))
        with mock.patch.object(addnew.comics, 'add_comic', return_value=True), DBConnection() as db:
            db.action("INSERT INTO comics (ComicID, Title, Status) VALUES ('CV123', 'Saga', 'Active')")
            self.assertEqual(addnew.add_comic('CV123'), {'id': 'CV123', 'title': 'Saga'})


class CommandTest(AddNewTestCase):

    def test_refresh_a_book_that_isnt_there(self):
        command = commands.start('RefreshBook', {'book_id': 'nothere'})
        for _ in range(50):
            command = commands.get(command['id'])
            if command['status'] in ('completed', 'failed'):
                break
            time.sleep(0.1)
        self.assertEqual((command['status'], command['title']), ('failed', 'Refresh Book'))
        self.assertIn('nothere', command['message'])

    def test_progress_names_what_it_is_for(self):
        self.author_loads()
        with DBConnection() as db:
            db.action("UPDATE books SET Status='Wanted' WHERE BookID='b1'")
        told = []

        def search(books, progress):
            progress('Searching for 1 eBook')
            return 0, 'Search for Killing Floor completed, nothing found'

        with mock.patch.object(commands, '_update', side_effect=lambda command, **changes: told.append(
                changes['message'])):
            with mock.patch.object(addnew.books, 'refresh_book', return_value='OpenLibrary'):
                self.assertEqual(commands._refresh_book({}, {'book_id': 'b1'}),
                                 'Refreshed Killing Floor from OpenLibrary')
            with mock.patch.object(addnew.books, 'add_book', return_value=('ol1', False, False)):
                commands._add_book({}, {'book_id': 'b2', 'title': 'Die Trying', 'media_types': ['ebook']})
            with mock.patch.object(commands.wanted, 'search_books', side_effect=search):
                message = commands._author_search({}, {'author_id': 'ol1'})
        self.assertEqual(told, ['Refreshing Killing Floor', 'Adding Die Trying', "Finding Lee Child's wanted books",
                                'Searching for 1 eBook by Lee Child'])
        self.assertEqual(message, 'Lee Child: Search for Killing Floor completed, nothing found')
