#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the language picker table in booklanguages.py

import unittest

from lazylibrarian.annas import Language, anna_languages
from lazylibrarian.booklanguages import (
    BOOK_LANGUAGES,
    COMMON_COUNT,
    GB_COUNTRIES,
    country_picker,
    language_picker,
    magazine_language_picker,
)


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
        picker = language_picker('sk, slo, slk, Slovak, cs, cze, ces, Czech, Unknown')
        selected = [lang for lang in picker['languages'] if lang['selected']]
        self.assertEqual([lang['name'] for lang in selected], ['Slovak', 'Czech'])
        self.assertEqual([lang['anna'] for lang in selected], ['SK', 'CS'])
        self.assertEqual([lang['zlib'] for lang in selected], ['slovak', 'czech'])

    def test_anna_unsupported(self):
        picker = language_picker('Welsh')
        self.assertEqual(picker['languages'][0]['anna'], '')

    def test_anna_languages(self):
        # the picker fills in several languages, older configs have a single one
        self.assertEqual(anna_languages('SK, CS'), [Language.SK, Language.CS])
        self.assertEqual(anna_languages('de'), [Language.DE])
        self.assertEqual(anna_languages('EN, XX, en'), [Language.EN])
        self.assertEqual(anna_languages('ANY'), [])
        self.assertEqual(anna_languages('EN, ANY'), [])
        self.assertEqual(anna_languages(''), [])

    def test_order(self):
        # selected first, then the common languages, then the rest by name
        picker = language_picker('Yiddish')
        names = [lang['name'] for lang in picker['languages']]
        self.assertEqual(names[0], 'Yiddish')
        self.assertEqual(names[1:COMMON_COUNT + 1], [name for name, _ in BOOK_LANGUAGES[:COMMON_COUNT]])
        rest = [lang['label'].lower() for lang in picker['languages'][COMMON_COUNT + 1:]]
        self.assertEqual(rest, sorted(rest))

    def test_countries(self):
        self.assertEqual(len(GB_COUNTRIES), 249)
        self.assertEqual(len(set(GB_COUNTRIES)), 249)
        self.assertEqual(list(GB_COUNTRIES), sorted(GB_COUNTRIES))
        self.assertTrue(all(len(code) == 2 and code.isupper() for code in GB_COUNTRIES))

    def test_country_picker(self):
        self.assertEqual(country_picker('sk ')['selected'], 'SK')
        self.assertEqual(country_picker('')['selected'], '')
        # GoogleBooks ignored anything but one country, so these stay automatic
        self.assertEqual(country_picker('SK CZ')['selected'], '')
        self.assertEqual(country_picker('XX')['selected'], '')

    def test_magazine_language_picker(self):
        picker = magazine_language_picker('SK')
        self.assertEqual(picker['selected'], 'sk')
        self.assertIsNone(picker['other'])
        self.assertEqual(len(picker['languages']), len(BOOK_LANGUAGES))
        labels = [lang['label'].lower() for lang in picker['languages']]
        self.assertEqual(labels, sorted(labels))

    def test_magazine_language_keeps_unknown_value(self):
        # a value the list doesn't have stays selected, so saving doesn't change it
        picker = magazine_language_picker('sk cz de en')
        self.assertEqual(picker['selected'], 'sk cz de en')
        self.assertEqual(picker['other'], 'sk cz de en')
        self.assertEqual(magazine_language_picker('')['other'], '')
