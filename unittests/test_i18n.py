#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test functions in i18n.py

import os
import tempfile
import unittest

from lazylibrarian import i18n

SAMPLE_PO = r'''# Test catalog
msgid ""
msgstr ""
"Language: sk\n"
"Plural-Forms: nplurals=3; plural=((n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2);\n"

#: base.html:1
msgid "Authors"
msgstr "Autori"

msgid "Line one "
"and two"
msgstr "Riadok jeden "
"a dva"

msgid "Quote \"me\""
msgstr "Cituj \"ma\""

#, fuzzy
msgid "Fuzzy"
msgstr "Neisté"

msgid "Untranslated"
msgstr ""

msgctxt "verb"
msgid "Search"
msgstr "Hľadať"

#, python-format
msgid "%(count)s author"
msgid_plural "%(count)s authors"
msgstr[0] "%(count)s autor"
msgstr[1] "%(count)s autori"
msgstr[2] "%(count)s autorov"

msgid "Half done"
msgid_plural "Half done plural"
msgstr[0] "Napoly"
msgstr[1] ""
msgstr[2] ""
'''


class I18nTest(unittest.TestCase):

    def setUp(self):
        fd, self.po_file = tempfile.mkstemp(suffix='.po')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(SAMPLE_PO)
        self.trans = i18n.POTranslations(self.po_file)

    def tearDown(self):
        os.remove(self.po_file)
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_gettext(self):
        self.assertEqual(self.trans.gettext('Authors'), 'Autori')
        self.assertEqual(self.trans.gettext('Line one and two'), 'Riadok jeden a dva')
        self.assertEqual(self.trans.gettext('Quote "me"'), 'Cituj "ma"')
        self.assertEqual(self.trans.gettext('Untranslated'), 'Untranslated')
        self.assertEqual(self.trans.gettext('Not in catalog'), 'Not in catalog')

    def test_mark_only(self):
        # N_() returns the English text, gettext() translates it later
        self.assertEqual(i18n.N_('Authors'), 'Authors')

    def test_fuzzy_is_ignored(self):
        self.assertEqual(self.trans.gettext('Fuzzy'), 'Fuzzy')

    def test_context(self):
        self.assertEqual(self.trans.pgettext('verb', 'Search'), 'Hľadať')
        self.assertEqual(self.trans.gettext('Search'), 'Search')

    def test_plurals(self):
        expected = {1: 'autor', 2: 'autori', 4: 'autori', 5: 'autorov', 0: 'autorov', 22: 'autorov'}
        for n, word in expected.items():
            msg = self.trans.ngettext('%(count)s author', '%(count)s authors', n) % {'count': n}
            self.assertEqual(msg, f'{n} {word}')
        self.assertEqual(self.trans.nplurals, 3)

    def test_partial_plurals_fall_back(self):
        self.assertEqual(self.trans.ngettext('Half done', 'Half done plural', 1), 'Napoly')
        self.assertEqual(self.trans.ngettext('Half done', 'Half done plural', 5), 'Half done plural')
        self.assertIsNone(self.trans.plural_forms('Half done'))
        self.assertEqual(self.trans.plural_forms('%(count)s author'),
                         ['%(count)s autor', '%(count)s autori', '%(count)s autorov'])

    def test_match_accept_language(self):
        langs = ['en', 'sk', 'pt_BR']
        data = [
            ('', 'en'),
            ('sk', 'sk'),
            ('sk-SK,sk;q=0.9,en;q=0.8', 'sk'),
            ('de-DE,de;q=0.9,sk;q=0.5', 'sk'),
            ('en-US,en;q=0.9,sk;q=0.8', 'en'),
            ('fr;q=1.0,sk;q=0', 'en'),
            ('pt-BR', 'pt_BR'),
            ('sk;q=0.5,en;q=0.9', 'en'),
            ('garbage;q=abc', 'en'),
        ]
        for header, expected in data:
            self.assertEqual(i18n.match_accept_language(header, langs), expected, header)

    def test_default_is_automatic(self):
        from lazylibrarian.configdefs import BASE_DEFAULTS
        item = next(i for i in BASE_DEFAULTS if i.key == 'UI_LANGUAGE')
        self.assertEqual(item.default, i18n.AUTO)
        self.assertEqual(i18n.resolve_language(item.default, 'sk-SK,sk;q=0.9'), 'sk')
        self.assertEqual(i18n.resolve_language(item.default, 'de-DE'), 'en')

    def test_resolve_language(self):
        self.assertEqual(i18n.resolve_language('en'), 'en')
        self.assertEqual(i18n.resolve_language('xx'), 'en')
        self.assertEqual(i18n.resolve_language('auto', 'zz'), 'en')
        self.assertIn('sk', i18n.available_languages())
        self.assertEqual(i18n.resolve_language('sk'), 'sk')
        self.assertEqual(i18n.resolve_language('auto', 'sk-SK,en;q=0.5'), 'sk')

    def test_thread_language(self):
        i18n.set_language('en')
        self.assertEqual(i18n.gettext('Authors'), 'Authors')
        self.assertEqual(i18n.plural_expression(), 'n != 1')
        i18n.set_language('sk')
        self.assertEqual(i18n.get_language(), 'sk')
        self.assertEqual(i18n.gettext('Authors'), 'Autori')
        self.assertIn('n>=2', i18n.plural_expression())

    def test_status_label(self):
        i18n.set_language('sk')
        self.assertEqual(i18n.status_label('Wanted'), 'Hľadaný')
        self.assertEqual(i18n.status_label('SomethingNew'), 'SomethingNew')
        i18n.set_language('en')
        self.assertEqual(i18n.status_label('Wanted'), 'Wanted')

    def test_js_helpers(self):
        i18n.set_language('en')
        self.assertEqual(i18n.js_string('a "b" </script>'), '"a \\"b\\" <\\/script>"')
        self.assertEqual(i18n.ngettext_js('one', 'many'), '{"f": ["one", "many"], "t": false}')


if __name__ == '__main__':
    unittest.main()
