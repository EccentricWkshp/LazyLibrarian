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

    def test_an_issue(self):
        with DBConnection() as db:
            db.action("INSERT INTO issues (Title, IssueID, IssueDate, IssueFile) VALUES "
                      "('Wired', 'i1', '2025-01', '')")
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
