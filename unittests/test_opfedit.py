#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the basic opf editor, reading our fields and writing them back

import os
import tempfile
import unittest

from lazylibrarian.opfedit import opf_read, opf_write

LL = '''<?xml version="1.0"  encoding="UTF-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" >
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>Salt &amp; Pepper &quot;Deluxe&quot;</dc:title>
        <dc:language>en</dc:language>
        <dc:identifier opf:scheme="HardCover">12345</dc:identifier>
        <dc:creator opf:file-as="Guillebeau, Chris" opf:role="aut">Chris Guillebeau</dc:creator>
        <dc:creator opf:file-as="Moss, Ann" opf:role="ill">Ann Moss</dc:creator>
        <dc:identifier opf:scheme="ISBN">9780307951526</dc:identifier>
        <dc:description>A bold start &amp; more
over two lines</dc:description>
        <meta content="Big &amp; &quot;Small&quot;" name="calibre:series"/>
    </metadata>
</package>
'''

EPUB3 = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">urn:isbn:9780307951526</dc:identifier>
    <dc:title>The $100 Startup</dc:title>
    <dc:creator id="c1">Chris Guillebeau</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
</package>
'''


class OpfEditTest(unittest.TestCase):
    def opf(self, text: str) -> str:
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: [os.remove(os.path.join(folder, name)) for name in os.listdir(folder)])
        path = os.path.join(folder, 'metadata.opf')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    @staticmethod
    def round_trip(path: str, changes: dict | None = None) -> str:
        template, replaces = opf_read(path)
        written = opf_write(template, [(name, (changes or {}).get(name, value)) for name, value in replaces])
        with open(written, encoding='utf-8') as f:
            return f.read()

    def test_values_are_read_as_text(self):
        _, replaces = opf_read(self.opf(LL))
        fields = dict(replaces)
        self.assertEqual('Salt & Pepper "Deluxe"', fields['title'])
        self.assertEqual('A bold start & more\nover two lines', fields['description'])
        self.assertEqual('Big & "Small"', fields['calibre:series'])
        self.assertEqual('12345', fields['HardCover'])
        self.assertEqual(('Chris Guillebeau', 'aut', 'Guillebeau, Chris'),
                         (fields['creator_00'], fields['role_00'], fields['fileas']))
        self.assertEqual(('Ann Moss', 'ill', 'Moss, Ann'),
                         (fields['creator_01'], fields['role_01'], fields['fileas_01']))

    def test_a_round_trip_changes_nothing(self):
        # once each value was escaped again, & became &amp;amp; and grew with every save
        path = self.opf(LL)
        self.assertEqual(LL, self.round_trip(path))

    def test_a_change_is_escaped(self):
        written = self.round_trip(self.opf(LL), {'calibre:series': 'Fish & "Chips"', 'creator_00': 'Bo <Bo>'})
        self.assertIn('<meta content="Fish &amp; &quot;Chips&quot;" name="calibre:series"/>', written)
        self.assertIn('opf:role="aut">Bo &lt;Bo&gt;</dc:creator>', written)
        self.assertIn('opf:file-as="Moss, Ann" opf:role="ill">Ann Moss</dc:creator>', written)

    def test_epub3_creators_and_identifiers(self):
        # a creator without role or file-as and an identifier without a scheme stopped the reading
        # part way, and the template, cut short there, was written back over the opf
        path = self.opf(EPUB3)
        _, replaces = opf_read(path)
        fields = dict(replaces)
        self.assertEqual('Chris Guillebeau', fields['creator_00'])
        self.assertEqual('en', fields['language'])
        self.assertEqual(EPUB3, self.round_trip(path))

    def test_an_opf_it_cant_read_isnt_written(self):
        path = self.opf(LL.replace('</dc:description>', ''))
        self.assertEqual(('', []), opf_read(path))
        self.assertFalse(os.path.exists(f'{path}_mod'))


if __name__ == '__main__':
    unittest.main()
