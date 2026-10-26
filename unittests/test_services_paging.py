#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/paging.py and the fold and natural_sort helpers it uses

import unittest

from lazylibrarian.formatter import fold, natural_sort
from lazylibrarian.services.paging import page_of

RECORDS = [
    {'Title': 'Book 10', 'Author': 'Émile Zola', 'Size': '10'},
    {'Title': 'Book 2', 'Author': 'Anne Rice', 'Size': '2'},
    {'Title': 'book 1', 'Author': None, 'Size': '1'},
]


class FoldTest(unittest.TestCase):

    def test_ignores_case_and_accents(self):
        self.assertEqual(fold('Émile ZOLA'), 'emile zola')

    def test_folds_any_value(self):
        self.assertEqual(fold(['A', None, 3]), "['a', none, 3]")


class NaturalSortTest(unittest.TestCase):

    def test_numbers_sort_by_value(self):
        titles = ['Book 10', 'Book 2', 'Book 1']
        natural_sort(titles)
        self.assertEqual(titles, ['Book 1', 'Book 2', 'Book 10'])

    def test_key_and_reverse(self):
        records = [{'n': 'v9'}, {'n': 'v10'}]
        natural_sort(records, key=lambda r: r['n'], reverse=True)
        self.assertEqual([r['n'] for r in records], ['v10', 'v9'])


class PageOfTest(unittest.TestCase):

    def test_no_arguments_returns_everything_unchanged(self):
        page = page_of(RECORDS)
        self.assertEqual(page.items, RECORDS)
        self.assertEqual((page.total, page.matched), (3, 3))

    def test_does_not_reorder_the_callers_list(self):
        records = list(RECORDS)
        page_of(records, sort='Title')
        self.assertEqual(records, RECORDS)

    def test_search_ignores_case_and_accents_in_the_search_fields(self):
        page = page_of(RECORDS, search='emile', search_fields=('Title', 'Author'))
        self.assertEqual([r['Title'] for r in page.items], ['Book 10'])
        self.assertEqual((page.total, page.matched), (3, 1))
        self.assertEqual(page_of(RECORDS, search='emile', search_fields=('Title',)).matched, 0)

    def test_sort_puts_missing_values_first(self):
        page = page_of(RECORDS, sort='Author')
        self.assertEqual([r['Author'] for r in page.items], [None, 'Anne Rice', 'Émile Zola'])
        page = page_of(RECORDS, sort='Author', descending=True)
        self.assertEqual(page.items[-1]['Author'], None)

    def test_natural_sort(self):
        plain = page_of(RECORDS, sort='Size')
        self.assertEqual([r['Size'] for r in plain.items], ['1', '10', '2'])
        natural = page_of(RECORDS, sort='Size', natural=True)
        self.assertEqual([r['Size'] for r in natural.items], ['1', '2', '10'])

    def test_sort_key(self):
        page = page_of(RECORDS, sort_key=lambda r: r['Title'].lower(), natural=True, descending=True)
        self.assertEqual([r['Title'] for r in page.items], ['Book 10', 'Book 2', 'book 1'])

    def test_offset_and_limit(self):
        page = page_of(RECORDS, sort='Size', natural=True, offset=1, limit=1)
        self.assertEqual([r['Size'] for r in page.items], ['2'])
        self.assertEqual((page.total, page.matched), (3, 3))

    def test_no_limit_or_below_zero_means_the_rest(self):
        self.assertEqual(len(page_of(RECORDS, offset=1).items), 2)
        self.assertEqual(len(page_of(RECORDS, offset=1, limit=-1).items), 2)
        self.assertEqual(page_of(RECORDS, offset=5, limit=10).items, [])


if __name__ == '__main__':
    unittest.main()
