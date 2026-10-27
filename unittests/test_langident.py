#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the numpy-free language identifier (langident.py), which gives what langid gives, and
#   UnRAR2 reading the list of an archive whose entries have no dates

import time
import unittest

from lazylibrarian import bookwork
from lazylibrarian.langident import LanguageIdentifier
from lib.UnRAR2.unix import parse_date

# what langid 1.1.6 said for each, choosing between LazyLibrarian's default languages
EXPECTED = {'The Girl with the Dragon Tattoo': ('en', 1.0), 'Without Fail': ('en', 0.9999579375824164),
            'Le Petit Prince': ('fr', 0.7613503158323767), 'Der Steppenwolf': ('de', 0.998615986401655),
            'Il nome della rosa': ('it', 0.9999999999823108)}


class LangIdentTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.identifier = LanguageIdentifier.load()

    def test_as_langid(self):
        self.identifier.set_languages(bookwork.DEFAULT_LANGID_LANGUAGES)
        for text, (language, probability) in EXPECTED.items():
            found = self.identifier.classify(text)
            self.assertEqual(found[0], language, text)
            self.assertAlmostEqual(found[1], probability, places=6, msg=text)

    def test_some_languages(self):
        self.identifier.set_languages(['en', 'de'])
        self.assertEqual(self.identifier.classify('Le Petit Prince')[0] in ('en', 'de'), True)
        self.identifier.set_languages(None)
        self.assertEqual(len(self.identifier.classes), 97)
        with self.assertRaises(ValueError):
            self.identifier.set_languages(['xx'])

    def test_what_lazylibrarian_uses(self):
        self.assertIsInstance(bookwork.LANGID, LanguageIdentifier)
        self.assertEqual(bookwork.language_from_words('Der Steppenwolf')[0], 'de')


class UnRarDateTest(unittest.TestCase):

    def test_dates(self):
        self.assertEqual(parse_date('2026-10-26 14:52')[:5], (2026, 10, 26, 14, 52))
        self.assertEqual(parse_date('26-10-26 14:52')[:3], (2026, 10, 26))
        self.assertIsNone(parse_date('????-??-?? ??:??'), 'A RAR5 entry without a date')
        self.assertIsInstance(parse_date('2026-10-26 14:52'), time.struct_time)
