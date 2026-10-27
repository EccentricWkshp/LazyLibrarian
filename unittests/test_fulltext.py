#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test searching inside issues (fulltext.py): a PDF's pages and an EPUB's chapters in the index of
#   their own, words, a phrase and the start of a word found, an item changed or gone

import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from lazylibrarian import fulltext


def text_pdf(pages: list[str]) -> bytes:
    """ A PDF whose pages have these words, in Helvetica """
    objects = ['<< /Type /Catalog /Pages 2 0 R >>',
               f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * n} 0 R' for n in range(len(pages)))}] "
               f"/Count {len(pages)} >>",
               '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for number, words in enumerate(pages):
        stream = f'BT /F1 18 Tf 50 700 Td ({words}) Tj ET'
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> '
                       f'/Contents {5 + 2 * number} 0 R >>')
        objects.append(f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream')
    out = b'%PDF-1.4\n'
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n{body}\nendobj\n'.encode()
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    out += ''.join(f'{offset:010d} 00000 n \n' for offset in offsets).encode()
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return out


class FullTextTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        patch = mock.patch.object(fulltext.DIRS, 'DATADIR', self.folder)
        patch.start()
        self.addCleanup(patch.stop)
        self.pdf = os.path.join(self.folder, 'Wired.pdf')
        with open(self.pdf, 'wb') as f:
            f.write(text_pdf(['The quantum computer issue', 'Building a raspberry pi cluster']))
        self.epub = os.path.join(self.folder, 'Wood.epub')
        with zipfile.ZipFile(self.epub, 'w') as epub:
            epub.writestr('META-INF/container.xml',
                          '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
            epub.writestr('OPS/book.opf', '<package><manifest><item id="a" href="one.xhtml"/><item id="b" '
                                          'href="two%20b.xhtml"/></manifest><spine><itemref idref="a"/>'
                                          '<itemref idref="b"/></spine></package>')
            epub.writestr('OPS/one.xhtml', '<html><style>p {}</style><body><p>Dovetail joints by hand</p></body></html>')
            epub.writestr('OPS/two b.xhtml', '<html><body><p>Finishing with shellac &amp; wax</p></body></html>')

    def test_index_and_search(self):
        self.assertEqual(fulltext.pdf_text(self.pdf), ['The quantum computer issue', 'Building a raspberry pi cluster'])
        self.assertEqual(fulltext.epub_text(self.epub), ['Dovetail joints by hand', 'Finishing with shellac & wax'])
        self.assertEqual(fulltext.index_item('issue', 'i1', self.pdf), 2)
        self.assertEqual(fulltext.index_item('issue', 'i2', self.epub), 2)
        found = fulltext.search('raspberry')
        self.assertEqual([(f['item_id'], f['page']) for f in found], [('i1', 2)])
        self.assertIn('[raspberry]', found[0]['snippet'])
        self.assertEqual([f['item_id'] for f in fulltext.search('shell')], ['i2'], 'The last word can be a start')
        self.assertEqual(fulltext.search('"pi cluster"')[0]['page'], 2, 'A phrase')
        self.assertEqual(fulltext.search('"cluster pi"'), [])
        self.assertEqual(fulltext.search('dovetail', kind='comic'), [])
        self.assertEqual(fulltext.stats(), {'items': 2, 'pages': 4})
        with fulltext.connect() as db:
            self.assertEqual(fulltext.forget('issue', {'i2'}, db), 1)
        self.assertEqual(fulltext.search('quantum'), [])

    def test_a_changed_file_is_read_again(self):
        fulltext.index_item('issue', 'i1', self.pdf)
        with open(self.pdf, 'wb') as f:
            f.write(text_pdf(['A different issue']))
        os.utime(self.pdf, (1, 1))
        self.assertEqual(fulltext.index_item('issue', 'i1', self.pdf), 1)
        self.assertEqual(fulltext.search('quantum'), [])
        self.assertEqual(len(fulltext.search('different')), 1)


if __name__ == '__main__':
    unittest.main()
