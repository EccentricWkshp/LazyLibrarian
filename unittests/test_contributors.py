#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test a book's other authors: linked when they are in the library, nobody added for contributing
#   (importer.link_contributor), and merging and removing the authors that used to be added
#   (services/library.py)

from lazylibrarian.database import DBConnection
from lazylibrarian.importer import author_name_key, link_contributor
from lazylibrarian.services import library
from unittests.unittesthelpers import LLTestCaseWithStartup

CONTRIBUTED = 'Contributor to Unbroken'


class ContributorTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        with DBConnection() as db:
            for table in ('books', 'authors', 'bookauthors', 'seriesauthors'):
                db.action(f"DELETE FROM {table}")
            for author_id, name, status, reason in (
                    ('a1', 'Matt Dinniman', 'Active', 'Import author of Dungeon Crawler Carl'),
                    ('a2', 'Brandon Sanderson', 'Paused', 'Import author of The Mistborn Trilogy'),
                    # what adding a contributor made of one with another source's id
                    ('a3', 'Brandon. Sanderson', 'Paused', CONTRIBUTED),
                    ('a4', 'J.A. Andrews', 'Paused', CONTRIBUTED),
                    ('a5', 'J. A. Andrews', 'Paused', 'Contributor to Grimoire'),
                    ('a6', 'Owned Contributor', 'Paused', CONTRIBUTED),
                    ('a7', 'Kept Contributor', 'Active', CONTRIBUTED),
                    ('a8', 'Main Contributor', 'Paused', CONTRIBUTED)):
                db.action("INSERT INTO authors (AuthorID, AuthorName, Status, Reason) VALUES (?, ?, ?, ?)",
                          (author_id, name, status, reason))
            for book_id, author_id, name, status in (('u', 'a1', 'Unbroken', 'Skipped'), ('g', 'a1', 'Grimoire', 'Skipped'),
                                                     ('o', 'a1', 'An Owned Anthology', 'Open'),
                                                     ('m', 'a8', 'Their Own Book', 'Skipped')):
                db.action("INSERT INTO books (BookID, AuthorID, BookName, Status, AudioStatus) VALUES (?, ?, ?, ?, "
                          "'Skipped')", (book_id, author_id, name, status))
                db.action("INSERT INTO bookauthors (AuthorID, BookID, Role) VALUES (?, ?, 1)", (author_id, book_id))
            for author_id, book_id in (('a3', 'u'), ('a4', 'u'), ('a5', 'g'), ('a6', 'o'), ('a7', 'u'), ('a8', 'u')):
                db.action("INSERT INTO bookauthors (AuthorID, BookID, Role) VALUES (?, ?, 2)", (author_id, book_id))
            db.action("INSERT INTO seriesauthors (SeriesID, AuthorID) VALUES ('s1', 'a3')")

    @staticmethod
    def rows(sql, args=()):
        with DBConnection() as db:
            return [tuple(row) for row in db.select(sql, args)]

    def test_names_written_differently(self):
        self.assertEqual(author_name_key('J.A. Andrews'), author_name_key('J. A. Andrews'))
        self.assertEqual(author_name_key('Miran Lipovača'), author_name_key('Miran Lipovaca'))
        self.assertNotEqual(author_name_key('Brandon Sanderson'), author_name_key('Brandon Sandersen'))

    def test_a_contributor_in_the_library_is_linked(self):
        with DBConnection() as db:
            self.assertEqual(link_contributor(db, 'g', 'Brandon  Sanderson'), 'a2', 'By their name written differently')
            self.assertEqual(link_contributor(db, 'g', 'Matt Dinniman'), 'a1', 'The book\'s own author')
        self.assertIn(('a2', 'g'), self.rows("SELECT AuthorID, BookID FROM bookauthors"))
        self.assertEqual(self.rows("SELECT Role FROM bookauthors WHERE AuthorID='a1' AND BookID='g'"), [(1,)],
                         'Still the main author')

    def test_nobody_is_added_for_contributing(self):
        authors = len(self.rows("SELECT * FROM authors"))
        with DBConnection() as db:
            self.assertEqual(link_contributor(db, 'u', 'Somebody New', '12345'), '')
        self.assertEqual(len(self.rows("SELECT * FROM authors")), authors)

    def test_what_removing_them_does(self):
        found = library.contributor_authors()
        self.assertEqual([(m['id'], m['into_id']) for m in found['merge']], [('a3', 'a2'), ('a4', 'a5')],
                         'Into the one added on purpose, else the one with the most books')
        self.assertEqual([a['id'] for a in found['remove']], ['a5'],
                         'Not one with a book in the library, set Active, or the main author of a book')

    def test_merging_and_removing_them(self):
        self.assertEqual(library.remove_contributor_authors(), {'merged': 2, 'removed': 1})
        self.assertEqual(self.rows("SELECT AuthorID FROM authors ORDER BY AuthorID"),
                         [('a1',), ('a2',), ('a6',), ('a7',), ('a8',)])
        self.assertIn(('a2', 'u', 2), self.rows("SELECT AuthorID, BookID, Role FROM bookauthors"), 'Their books moved')
        self.assertEqual(self.rows("SELECT AKA FROM authors WHERE AuthorID='a2'"), [('Brandon. Sanderson',)])
        self.assertEqual(self.rows("SELECT AuthorID FROM seriesauthors"), [('a2',)])
        self.assertEqual(len(self.rows("SELECT * FROM books")), 4, 'Every book stays')
        self.assertFalse(self.rows("SELECT * FROM bookauthors WHERE AuthorID IN ('a3','a4','a5')"))
        self.assertEqual(library.contributor_authors(), {'merge': [], 'remove': []}, 'Done')
