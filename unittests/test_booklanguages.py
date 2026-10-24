#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the language picker table in booklanguages.py

import unittest

from lazylibrarian.booklanguages import BOOK_LANGUAGES, COMMON_COUNT, language_picker


class BookLanguagesTest(unittest.TestCase):

    def test_codes_are_unique(self):
        seen = {}
        for name, codes in BOOK_LANGUAGES:
            for code in codes:
                self.assertNotIn(code.lower(), seen, f'{code} is in both {seen.get(code.lower())} and {name}')
                seen[code.lower()] = name

    def test_names_are_codes(self):
        # The English name is what some sources report, so it must match too
        for name, codes in BOOK_LANGUAGES:
            self.assertIn(name, codes)

    def test_default_value(self):
        picker = language_picker('en, eng, en-US, en-GB, English')
        selected = [lang['name'] for lang in picker['languages'] if lang['selected']]
        self.assertEqual(selected, ['English'])
        self.assertEqual(picker['other'], '')
        self.assertEqual(len(picker['languages']), len(BOOK_LANGUAGES))

    def test_any_code_selects_language(self):
        picker = language_picker('CZE, sk')
        selected = [lang['name'] for lang in picker['languages'] if lang['selected']]
        self.assertEqual(selected, ['Czech', 'Slovak'])

    def test_unknown_entries_are_kept(self):
        picker = language_picker('en, Unknown, All, xx-YY')
        self.assertEqual(picker['other'], 'Unknown, All, xx-YY')

    def test_empty_value(self):
        picker = language_picker('')
        self.assertFalse(any(lang['selected'] for lang in picker['languages']))
        self.assertEqual(picker['other'], '')

    def test_selected_keep_their_order(self):
        # the first language is used for the single language settings
        picker = language_picker('sk, slo, slk, Slovak, cs, cze, ces, Czech, Unknown')
        selected = [lang for lang in picker['languages'] if lang['selected']]
        self.assertEqual([lang['name'] for lang in selected], ['Slovak', 'Czech'])
        self.assertEqual([lang['code'] for lang in selected], ['sk', 'cs'])
        self.assertEqual([lang['anna'] for lang in selected], ['SK', 'CS'])
        self.assertEqual([lang['zlib'] for lang in selected], ['slovak', 'czech'])

    def test_anna_unsupported(self):
        picker = language_picker('Welsh')
        self.assertEqual(picker['languages'][0]['anna'], '')

    def test_order(self):
        # selected first, then the common languages, then the rest by name
        picker = language_picker('Yiddish')
        names = [lang['name'] for lang in picker['languages']]
        self.assertEqual(names[0], 'Yiddish')
        self.assertEqual(names[1:COMMON_COUNT + 1], [name for name, _ in BOOK_LANGUAGES[:COMMON_COUNT]])
        rest = [lang['label'].lower() for lang in picker['languages'][COMMON_COUNT + 1:]]
        self.assertEqual(rest, sorted(rest))
