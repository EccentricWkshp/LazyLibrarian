#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test editing an author, book, magazine, issue, comic and series for the new pages' edit dialogs
#   (services/editing.py)

from unittest import mock

from lazylibrarian.database import DBConnection
from lazylibrarian.services import InvalidRequestError, NotFoundError, editing, magazines
from unittests.unittesthelpers import LLTestCaseWithStartup


class EditingTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        with DBConnection() as db:
            for table in ('books', 'authors', 'bookauthors', 'series', 'member', 'seriesauthors', 'magazines',
                          'issues', 'comics', 'comicissues'):
                db.action(f"DELETE FROM {table}")
            db.action("INSERT INTO authors (AuthorID, AuthorName, AuthorBorn, Status, Manual, ol_id, About, Reason) "
                      "VALUES ('a1', 'Lee Child', '1954/10/29', 'Active', '0', 'OL1A', 'Jack Reacher', 'Library scan')")
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status) VALUES ('a2', 'Andrew Child', 'Active')")
            db.action("INSERT INTO books (BookID, AuthorID, BookName, BookDate, BookLang, Status, AudioStatus, "
                      "Narrator, Manual) VALUES ('b1', 'a1', 'Killing Floor', '1997-03-17', 'en', 'Open', 'Skipped', "
                      "'Dick Hill', '0')")
            db.action("INSERT INTO series (SeriesID, SeriesName, Status, Reason) VALUES "
                      "('OL1', 'Jack Reacher', 'Paused', 'b1')")
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('OL1', 'b1', '1')")
            db.action("INSERT INTO seriesauthors (SeriesID, AuthorID) VALUES ('OL1', 'a1')")
            db.action("INSERT INTO magazines (Title, Reject, DateType, CoverPage, Language) VALUES "
                      "('Wired', 'uk', 'YM', 1, 'en')")
            db.action("INSERT INTO comics (ComicID, Title, Publisher, aka, Description, Genre) VALUES "
                      "('CV1', 'Saga', 'Image', '', 'Space opera', 'sf')")

    def test_an_author(self):
        author = editing.author_for_edit('a1')
        self.assertEqual((author['name'], author['born'], author['locked'], author['reason']),
                         ('Lee Child', '1954/10/29', False, 'Library scan'))
        openlibrary = next(source for source in author['sources'] if source['source'] == 'OpenLibrary')
        self.assertEqual((openlibrary['id'], openlibrary['primary']), ('OL1A', True),
                         'The first source linked is the one used, without one chosen')
        message = editing.save_author('a1', {'aka': 'Jim Grant', 'locked': True, 'died': ''})
        self.assertIn('AKA', message)
        edited = editing.author_for_edit('a1')
        self.assertEqual((edited['aka'], edited['locked'], edited['born']), ('Jim Grant', True, '1954-10-29'),
                         'What was left out is unchanged, the date as update_author stores them')
        with self.assertRaises(InvalidRequestError):
            editing.save_author('a1', {'name': 'Andrew Child'})
        with self.assertRaises(InvalidRequestError):
            editing.save_author('a1', {'name': 'Lee <Child>'})
        with self.assertRaises(NotFoundError):
            editing.author_for_edit('nobody')

    def test_a_book(self):
        book = editing.book_for_edit('b1')
        self.assertEqual((book['title'], book['author'], book['narrator'], book['series']),
                         ('Killing Floor', 'Lee Child', 'Dick Hill', [{'name': 'Jack Reacher', 'number': '1'}]))
        self.assertIn('Andrew Child', book['authors'])
        self.assertEqual(book['author_series'], ['Jack Reacher'])
        message = editing.save_book('b1', {'subtitle': 'Reacher 1', 'narrator': 'Jeff Harding',
                                           'series': [{'name': 'Jack Reacher', 'number': '1.5'}]})
        self.assertIn('Subtitle', message)
        self.assertIn('Narrator', message)
        edited = editing.book_for_edit('b1')
        self.assertEqual((edited['subtitle'], edited['narrator']), ('Reacher 1', 'Jeff Harding'))
        self.assertEqual(edited['series'], [{'name': 'Jack Reacher', 'number': '1.5'}])
        with self.assertRaises(InvalidRequestError):
            editing.save_book('b1', {'series': [{'name': 'Reacher Shorts', 'number': '1'}]})
        editing.save_book('b1', {'author': 'Andrew Child'})
        self.assertEqual(editing.book_for_edit('b1')['author'], 'Andrew Child', 'Moved to another author')
        with self.assertRaises(InvalidRequestError):
            editing.save_book('b1', {'release_date': 'last year'})
        with self.assertRaises(InvalidRequestError):
            editing.save_book('b1', {'author': 'Nobody We Know'})
        with self.assertRaises(InvalidRequestError):
            editing.save_book('b1', {'cover': 'somewhere'})

    def test_fix_match(self):
        from lazylibrarian.config2 import CONFIG
        for key in ('OL_API', 'HC_API', 'BOOK_API'):
            self.addCleanup(CONFIG.set_from_ui, key, CONFIG[key])
        CONFIG.set_from_ui('OL_API', True)
        CONFIG.set_from_ui('HC_API', True)
        CONFIG.set_from_ui('BOOK_API', 'HardCover')
        with DBConnection() as db:
            db.action("UPDATE books SET hc_id='b1', ol_id='OL9W' WHERE BookID='b1'")
            db.action("INSERT INTO books (BookID, AuthorID, BookName, ol_id) VALUES ('b2', 'a1', 'Die Trying', 'OL2W')")
        book = editing.book_for_edit('b1')
        self.assertEqual((book['own_source'], book['source_ids']['OpenLibrary']), ('HardCover', 'OL9W'))
        self.assertEqual(book['match_sources'][:2], ['HardCover', 'OpenLibrary'], 'The one searched first first')
        found = [{'bookid': 'OL1W', 'bookname': 'Killing Floor', 'booksub': 'Jack Reacher 1', 'authorname': 'Lee Child',
                  'bookdate': '1997-03-17', 'bookpub': 'Putnam', 'bookisbn': '0399142509', 'booklang': 'en',
                  'bookpages': 524, 'bookgenre': 'Thriller', 'bookdesc': 'Reacher is arrested', 'bookimg':
                  'http://covers/1.jpg', 'booklink': 'http://ol/OL1W'},
                 {'bookid': 'OL2W', 'bookname': 'Die Trying', 'authorname': 'Lee Child'}]
        with mock.patch('lazylibrarian.importer.search_for', return_value=found) as search:
            matches = editing.book_source_search('b1', 'OpenLibrary')
        search.assert_called_once_with('Lee Child Killing Floor', 'OpenLibrary', max_pages=2)
        self.assertEqual([(m['id'], m['publisher'], m['pages']) for m in matches], [('OL1W', 'Putnam', 524),
                                                                                    ('OL2W', '', 0)])
        with mock.patch('lazylibrarian.cache.cache_img', return_value=('cache/book/' + 'a' * 32 + '.jpg', True, False)):
            message = editing.match_book('b1', 'OpenLibrary', 'OL1W')
        self.assertIn('is OL1W at OpenLibrary now', message)
        with DBConnection() as db:
            row = db.match("SELECT ol_id, BookSub, BookPub, BookPages, BookImg, Manual FROM books WHERE BookID='b1'")
        self.assertEqual((row['ol_id'], row['BookSub'], row['BookPub'], row['BookPages'], row['BookImg']),
                         ('OL1W', 'Jack Reacher 1', 'Putnam', 524, 'cache/book/' + 'a' * 32 + '.jpg'))
        self.assertNotEqual(row['Manual'], '1', "Another source's match leaves it unlocked")
        with self.assertRaisesRegex(InvalidRequestError, "Die Trying is OL2W"):
            editing.match_book('b1', 'OpenLibrary', 'OL2W')
        with self.assertRaisesRegex(NotFoundError, 'search again'):
            editing.match_book('b1', 'OpenLibrary', 'OL3W')
        with mock.patch('lazylibrarian.importer.search_for', return_value=[{'bookid': '777', 'bookname': 'Killing Floor'}]):
            editing.book_source_search('b1', 'HardCover', 'killing floor')
        message = editing.match_book('b1', 'HardCover', '777', details=False, cover=False)
        self.assertIn('locked so a refresh keeps it', message)
        with DBConnection() as db:
            self.assertEqual(db.match("SELECT hc_id, Manual FROM books WHERE BookID='b1'")['hc_id'], '777')
        self.assertTrue(editing.book_for_edit('b1')['locked'], "A match at its own source locks it")

    def test_no_cover(self):
        message = editing.save_book('b1', {'cover': 'none'})
        self.assertIn('Cover (none)', message)
        image = editing.book_for_edit('b1')['image']
        from lazylibrarian.images import chosen_cover
        self.assertTrue(chosen_cover(image), 'A cover chosen, so a refresh keeps it')

    def test_a_magazine(self):
        magazine = editing.magazine_for_edit('wired')
        self.assertEqual((magazine['title'], magazine['reject'], magazine['date_type']), ('Wired', 'uk', 'YM'))
        saved = editing.save_magazine('Wired', {'reject': 'uk, au', 'cover_page': 2})
        self.assertEqual(saved['title'], 'Wired')
        edited = editing.magazine_for_edit('Wired')
        self.assertEqual((edited['reject'], edited['cover_page'], edited['date_type']), ('uk, au', 2, 'YM'))
        with mock.patch.object(magazines, 'rename_magazine', return_value=(3, 0)) as rename:
            saved = editing.save_magazine('Wired', {'title': 'Wired UK'})
        rename.assert_called_once_with('Wired', 'Wired UK')
        self.assertEqual(saved['title'], 'Wired UK')
        self.assertIn('3 issue files moved', saved['message'])

    def test_covers_for_issues_without_one(self):
        """ Saving a magazine with the same cover page makes covers for its issues that have none """
        with DBConnection() as db:
            db.action("INSERT INTO issues (Title, IssueID, IssueDate, IssueFile, Cover) VALUES "
                      "('Wired', 'i1', '2025-01-01', 'a.pdf', ''), ('Wired', 'i2', '2025-02-01', 'b.pdf', "
                      "'data/images/nocover.jpg'), ('Wired', 'i3', '2025-03-01', 'c.pdf', 'cache/magazine/c.jpg')")
        with mock.patch('lazylibrarian.services.commands.start') as start:
            saved = editing.save_magazine('Wired', {'cover_page': 1})
        start.assert_called_once_with('IssueCovers', {'ids': ['i1', 'i2'], 'page': 1})
        self.assertIn('covers are being made for the 2 issues without one', saved['message'])

    def test_an_issue(self):
        with DBConnection() as db:
            db.action("INSERT INTO issues (Title, IssueID, IssueDate, IssueFile) VALUES "
                      "('Wired', 'i1', '2025-01', 'wired.pdf')")
        with mock.patch.object(magazines, 'read_pdf_tags', return_value={'/Title': 'Wired January'}):
            issue = editing.issue_for_edit('i1')
            self.assertEqual(issue['tags'], [{'name': '/Title', 'value': 'Wired January'}])
            with self.assertRaises(InvalidRequestError):
                editing.save_issue('i1', {'issue_date': 'sometime'})
        with mock.patch.object(magazines, 'update_issue', return_value=('Wired', 'changed')) as update, \
                mock.patch.object(magazines, 'read_pdf_tags', return_value={'/Title': 'Wired January'}):
            editing.save_issue('i1', {'tags': [{'name': '/Title', 'value': 'Wired Jan'},
                                               {'name': '/Unknown', 'value': 'x'}]})
        self.assertEqual(update.call_args.args[3], {'/Title': 'Wired Jan'}, "A tag the file doesn't have isn't added")

    def test_a_comic(self):
        self.assertEqual(editing.comic_for_edit('CV1')['genre'], 'sf')
        saved = editing.save_comic('CV1', {'genre': 'science fiction', 'id': 'CV2'})
        self.assertEqual(saved['id'], 'CV2')
        self.assertEqual(editing.comic_for_edit('CV2')['genre'], 'science fiction')
        with DBConnection() as db:
            db.action("INSERT INTO comics (ComicID, Title) VALUES ('CV3', 'Paper Girls')")
        with self.assertRaises(InvalidRequestError):
            editing.save_comic('CV2', {'id': 'CV3'})

    def test_a_series(self):
        found = editing.series_for_edit('OL1')
        self.assertEqual(found['members'], [{'number': '1', 'title': 'Killing Floor'}])
        self.assertIn('Killing Floor', found['reason'])
        saved = editing.save_series('OL1', {'name': 'Reacher', 'id': 'OL9'})
        self.assertEqual(saved['id'], 'OL9')
        self.assertEqual(editing.series_for_edit('OL9')['name'], 'Reacher')
        self.assertEqual(editing.book_for_edit('b1')['series'], [{'name': 'Reacher', 'number': '1'}],
                         'Its members went with it')
