#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/authors.py

import datetime
from unittest import mock

import lazylibrarian
from lazylibrarian import ROLE
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import InvalidRequestError, NotFoundError, ServiceError, authors
from lazylibrarian.startup import StartupLazyLibrarian
from unittests.unittesthelpers import LLTestCaseWithDB

INSERT = ("INSERT INTO authors (AuthorID,AuthorName,LastBook,Status,Reason,PrimarySource,ol_id,gr_id,HaveBooks,"
          "UnignoredBooks,AuthorBorn,AuthorDeath,About,AKA,Manual,AuthorImg,AuthorLink) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'0','img','http://link')")


class AuthorServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, lazylibrarian, 'INFOSOURCES', lazylibrarian.INFOSOURCES)
        lazylibrarian.INFOSOURCES = StartupLazyLibrarian.build_sources()
        saved = {k: CONFIG[k] for k in ('SORT_SURNAME', 'SORT_DEFINITE', 'IGNORE_PAUSED', 'BOOK_API')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(k, v) for k, v in saved.items()])
        CONFIG.set_bool('SORT_SURNAME', False)
        CONFIG.set_bool('SORT_DEFINITE', False)
        CONFIG.set_bool('IGNORE_PAUSED', False)
        CONFIG.set_str('BOOK_API', 'OpenLibrary')
        for row in (
                ('A1', 'Anne Rice', 'The Witching Hour', 'Active', 'WEBSERVER x', '', '', 'GR1', 3, 4, '1941-10-04',
                 '2021-12-11', '<i>Librarian Note: Two of them</i><br/>Bio', ''),
                ('A2', 'Émile Zola', 'Germinal', 'Paused', 'wishlist goodreads', 'OpenLibrary', 'OL2A', '', 5, 2,
                 '1840', None, 'About', ''),
                ('A3', 'Ignored Person', None, 'Ignored', None, '', '', '', 0, 0, None, None, '', '')):
            self.sql(INSERT, row)

    def owner(self):
        return self.sql('SELECT UserID FROM users')[0]['UserID']

    def ids(self, page):
        return [a['AuthorID'] for a in page.items]

    def test_added_reason(self):
        self.assertEqual(authors.added_reason('WEBSERVER add'), 'Manual search')
        self.assertEqual(authors.added_reason('wishlist goodreads list'), 'Wishlist search goodreads list')
        self.assertEqual(authors.added_reason('add book by Someone'), 'Import author of Someone')
        self.assertEqual(authors.added_reason(None), '')

    def test_list_authors(self):
        page = authors.list_authors()
        self.assertEqual(self.ids(page), ['A1', 'A2'])
        rice, zola = page.items
        self.assertEqual((rice['Percent'], zola['Percent']), (75, 100))
        self.assertEqual((rice['AddedReason'], zola['AddedReason']), ('Manual search', 'Wishlist search goodreads'))
        self.assertEqual(rice['BadgeSource'], 'GoodReads', 'The only linked source')
        self.assertEqual(zola['BadgeSource'], 'OpenLibrary', 'The primary source')

    def test_list_ignored_and_paused(self):
        self.assertEqual(self.ids(authors.list_authors(ignored=True)), ['A3'])
        CONFIG.set_bool('IGNORE_PAUSED', True)
        self.assertEqual(self.ids(authors.list_authors()), ['A1'])
        self.assertEqual(self.ids(authors.list_authors(ignored=True)), ['A3', 'A2'], 'É sorts after I')

    def test_list_search_sort_and_surname(self):
        self.assertEqual(self.ids(authors.list_authors(search='emile')), ['A2'])
        self.assertEqual(self.ids(authors.list_authors(sort='Percent', descending=True)), ['A2', 'A1'])
        CONFIG.set_bool('SORT_SURNAME', True)
        page = authors.list_authors(sort='NameSort')
        self.assertEqual([a['NameSort'] for a in page.items], ['Rice, Anne', 'Zola, Émile'])
        self.assertEqual(page.items[0]['AuthorName'], 'Anne Rice')

    def test_list_primary_and_subscribed(self):
        self.sql("INSERT INTO books (BookID,AuthorID,BookName) VALUES ('B1','A2','Germinal')")
        self.sql("INSERT INTO bookauthors (AuthorID,BookID,Role) VALUES ('A2','B1',?)", (ROLE['PRIMARY'],))
        self.assertEqual(self.ids(authors.list_authors(primary_only=True)), ['A2'])
        self.sql("INSERT INTO subscribers (UserID,Type,WantID) VALUES (?,'author','A1')", (self.owner(),))
        self.assertEqual(self.ids(authors.list_authors(subscriber=self.owner())), ['A1'])

    def test_get_author(self):
        self.assertEqual(authors.get_author('A1')['AuthorName'], 'Anne Rice')
        self.assertEqual(authors.get_author('OL2A', any_source_id=True)['AuthorID'], 'A2')
        with self.assertRaises(NotFoundError):
            authors.get_author('OL2A')

    def test_author_details(self):
        details = authors.author_details('A1')
        self.assertEqual(details['librarian_note'], 'Two of them')
        self.assertEqual(details['author']['About'], 'Bio')
        self.assertEqual(details['age'], 80)
        with self.assertRaises(NotFoundError):
            authors.author_details('nosuch')

    def test_author_age(self):
        today = datetime.date.today()
        self.assertEqual(authors.author_age({'AuthorBorn': f'{today.year - 30}'}), 30)
        self.assertIsNone(authors.author_age({'AuthorBorn': 'unknown'}))

    def test_search_links(self):
        self.assertEqual(authors.amazon_search_link('Anne Rice'),
                         'https://www.amazon.com/s?i=stripbooks&rh=p_27%3AAnne%20Rice')
        self.assertEqual(authors.amazon_search_link(''), '')

    def test_set_status(self):
        authors.set_status('A1', 'Wanted')
        self.assertEqual(self.sql("SELECT Status FROM authors WHERE AuthorID='A1'")[0]['Status'], 'Wanted')
        with self.assertRaises(InvalidRequestError):
            authors.set_status('A1', 'Exploded')
        with self.assertRaises(NotFoundError):
            authors.set_status('nosuch', 'Active')

    def test_remove_author_removes_their_only_series(self):
        self.sql("INSERT INTO series (SeriesID,SeriesName) VALUES ('S1','Theirs'),('S2','Shared')")
        self.sql("INSERT INTO seriesauthors (SeriesID,AuthorID) VALUES ('S1','A1'),('S2','A1'),('S2','A2')")
        authors.remove_author('A1')
        self.assertEqual(self.sql("SELECT * FROM authors WHERE AuthorID='A1'"), [])
        self.assertEqual([s['SeriesID'] for s in self.sql('SELECT SeriesID FROM series')], ['S2'])
        with self.assertRaises(NotFoundError):
            authors.remove_author('A1')

    def test_follow_author(self):
        with mock.patch.object(authors.grsync, 'grfollow', return_value='Followed followid=99') as grfollow:
            authors.follow_author('A1')
            self.assertEqual(self.sql("SELECT GRfollow FROM authors WHERE AuthorID='A1'")[0]['GRfollow'], '99')
            self.assertIn('Already Following', authors.follow_author('A1'))
            grfollow.return_value = 'Unfollowed'
            authors.follow_author('A1', follow=False)
            self.assertEqual(grfollow.call_count, 2)
        self.assertEqual(self.sql("SELECT GRfollow FROM authors WHERE AuthorID='A1'")[0]['GRfollow'], '0')
        with self.assertRaises(NotFoundError):
            authors.follow_author('nosuch')

    def test_mark_authors(self):
        self.assertEqual(authors.mark_authors('Paused', ['A1', 'nosuch']), (1, 1))
        owner = self.owner()
        self.assertEqual(authors.mark_authors('Subscribe', ['A1'], owner), (1, 0))
        self.assertEqual(authors.mark_authors('Subscribe', ['A1'], owner), (0, 1), 'Already subscribed')
        self.assertEqual(authors.mark_authors('Subscribe', ['A1']), (0, 0), 'Nobody to subscribe')
        self.assertEqual(authors.mark_authors('Unsubscribe', ['A1'], owner), (1, 0))
        self.assertEqual(self.sql('SELECT * FROM subscribers'), [])
        self.assertEqual(authors.mark_authors('Remove', ['A3']), (1, 0))
        self.assertEqual(authors.mark_authors('', ['A1']), (0, 0))

    def test_mark_delete_and_ignore(self):
        self.sql("INSERT INTO books (BookID,AuthorID,BookName,Status,BookFile) VALUES ('B1','A1','x','Open','')")
        with mock.patch.object(authors, 'update_totals'):
            self.assertEqual(authors.mark_authors('Delete+Ignore', ['A1']), (1, 0))
        self.assertEqual(self.sql("SELECT Status FROM books WHERE BookID='B1'")[0]['Status'], 'Ignored')
        self.assertEqual(self.sql("SELECT Status FROM authors WHERE AuthorID='A1'")[0]['Status'], 'Ignored')
        self.assertEqual(authors.mark_authors('Delete', ['A2']), (1, 0))
        self.assertEqual(self.sql("SELECT * FROM authors WHERE AuthorID='A2'"), [])

    def author(self, authorid='A1'):
        return self.sql('SELECT * FROM authors WHERE AuthorID=?', (authorid,))[0]

    def test_update_author(self):
        edited = authors.update_author('A1', 'Anne Rice', born='1941-10-05', died='2021-12-11', about='New bio')
        self.assertIn('Born', edited)
        self.assertIn('Description', edited)
        author = self.author()
        self.assertEqual((author['AuthorBorn'], author['About'], author['AuthorImg']), ('1941-10-05', 'New bio', 'img'))
        self.assertEqual(authors.update_author('A1', 'Anne Rice', born='1941-10-05', died='2021-12-11',
                                               about='New bio'), '', 'Nothing changed')
        with self.assertRaises(NotFoundError):
            authors.update_author('nosuch', 'x', born=None, died=None)

    def test_update_author_keeps_bad_dates_and_taken_names(self):
        # only the length is checked, so it has to be a length a date can't have
        edited = authors.update_author('A1', 'Émile Zola', born='someday', died='2021-12-11',
                                       about=self.author()['About'])
        self.assertNotIn('Name', edited)
        self.assertNotIn('Born', edited)
        self.assertEqual((self.author()['AuthorName'], self.author()['AuthorBorn']), ('Anne Rice', '1941-10-04'))

    def test_update_author_rejects_a_missing_image(self):
        authors.update_author('A1', 'Anne Rice', born='1941-10-04', died='2021-12-11', image='/no/such/file.jpg',
                              about='changed', cover='manual')
        self.assertEqual(self.author()['AuthorImg'], 'img')

    def test_source_links(self):
        with self.assertRaises(InvalidRequestError):
            authors.link_source('A1', 'NoSource', 'x')
        with self.assertRaises(InvalidRequestError):
            authors.link_source('A1', 'OpenLibrary', '')
        api = mock.MagicMock()
        api.return_value.get_author_info.return_value = {'authorlink': 'http://ol/OL9A'}
        with mock.patch.dict(lazylibrarian.INFOSOURCES['OpenLibrary'], {'api': api}):
            self.assertEqual(authors.link_source('A1', 'OpenLibrary', 'OL9A'), ('ol_id', 'OL9A'))
            self.assertEqual(authors.set_primary_source('A1', 'OpenLibrary'), 'http://ol/OL9A')
        author = self.author()
        self.assertEqual((author['ol_id'], author['PrimarySource'], author['AuthorLink']),
                         ('OL9A', 'OpenLibrary', 'http://ol/OL9A'))
        authors.unlink_source('A1', 'OpenLibrary')
        author = self.author()
        self.assertEqual((author['ol_id'], author['PrimarySource'], author['AuthorLink']), ('', '', ''))
        with self.assertRaises(InvalidRequestError):
            authors.set_primary_source('A1', 'OpenLibrary')

    def test_search_source(self):
        api = mock.MagicMock()
        api.return_value.find_author_id.return_value = {'authorid': 'OL7A', 'authorname': 'Anne Rice',
                                                        'authorlink': 'http://ol/OL7A'}
        self.addCleanup(CONFIG.set_from_ui, 'OL_API', CONFIG['OL_API'])
        CONFIG.set_bool('OL_API', True)
        with mock.patch.dict(lazylibrarian.INFOSOURCES['OpenLibrary'], {'api': api}):
            self.assertEqual(authors.search_source('A1', 'OpenLibrary')['authorid'], 'OL7A')
            api.return_value.find_author_id.return_value = None
            self.assertIsNone(authors.search_source('A1', 'OpenLibrary'))
            api.return_value.find_author_id.side_effect = Exception('down')
            with self.assertRaises(ServiceError):
                authors.search_source('A1', 'OpenLibrary')
            with self.assertRaises(NotFoundError):
                authors.search_source('nosuch', 'OpenLibrary')
        CONFIG.set_bool('OL_API', False)
        with self.assertRaises(InvalidRequestError):
            authors.search_source('A1', 'OpenLibrary')

    def test_search_sources(self):
        self.addCleanup(setattr, lazylibrarian, 'SEARCHING', lazylibrarian.SEARCHING)
        results = [{'highest_fuzz': 80, 'bookrate_count': 1, 'id': 'low'},
                   {'highest_fuzz': 95, 'bookrate_count': 1, 'id': 'high'}]
        with mock.patch.object(authors, 'search_for', return_value=results), \
                mock.patch.object(CONFIG, 'get_bool', return_value=False):
            found = authors.search_sources('anne')
        self.assertEqual([r['id'] for r in found['results']], ['high', 'low'])
        self.assertEqual(sorted(found['authorlist']), ['A1', 'A2', 'A3'])
        self.assertEqual(lazylibrarian.SEARCHING, 0)
