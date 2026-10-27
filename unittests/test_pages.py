#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the pages of issue files (pages.py) and what files say about themselves (filemeta.py):
#   PDFs drawn by pdfium, comic archives in page order, an EPUB's cover and package metadata,
#   a cbz's ComicInfo.xml

import io
import os
import shutil
import tempfile
import unittest
import zipfile

from PIL import Image
from pypdf import PdfWriter

from lazylibrarian import filemeta, pages


def picture(width: int, kind: str = 'JPEG') -> bytes:
    out = io.BytesIO()
    Image.new('RGB', (width, 40), 'red').save(out, kind)
    return out.getvalue()


def jpeg_width(data: bytes) -> int:
    return Image.open(io.BytesIO(data)).width


CONTAINER = ('<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
             'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
             'media-type="application/oebps-package+xml"/></rootfiles></container>')
OPF = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
       '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Wired May 2024</dc:title>'
       '<dc:description>&lt;p&gt;The AI issue&lt;/p&gt;</dc:description><dc:publisher>Conde Nast</dc:publisher>'
       '<dc:date>2024-05-01T00:00:00</dc:date><dc:language>en</dc:language>'
       '<meta name="calibre:series" content="Wired"/><meta name="calibre:series_index" content="5.0"/>'
       '</metadata><manifest><item id="c" href="images/cover%20art.png" media-type="image/png" '
       'properties="cover-image"/></manifest></package>')
COMICINFO = ('<?xml version="1.0"?><ComicInfo><Series>Saga</Series><Number>12</Number><Volume>1</Volume>'
             '<Year>2013</Year><Month>5</Month><Summary>Space opera</Summary><Publisher>Image</Publisher>'
             '<PageCount>3</PageCount></ComicInfo>')


class PagesTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.pdf = os.path.join(self.folder, 'Wired 2024-05.pdf')
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.add_blank_page(width=400, height=300)
        writer.add_metadata({'/Title': 'Wired', '/Subject': 'The AI issue', '/CreationDate': "D:20240501120000Z",
                             '/LL_Title': 'Wired', '/LL_Issue': '2024-05-01'})
        with open(self.pdf, 'wb') as f:
            writer.write(f)
        self.cbz = os.path.join(self.folder, 'Saga 012.cbz')
        with zipfile.ZipFile(self.cbz, 'w') as archive:
            # named so that sorted as text, page 10 would come before page 2
            for name, width in (('p10.jpg', 30), ('p2.png', 20), ('p1.jpg', 10), ('.hidden.jpg', 99)):
                archive.writestr(name, picture(width, 'PNG' if name.endswith('png') else 'JPEG'))
            archive.writestr('ComicInfo.xml', COMICINFO)
        self.epub = os.path.join(self.folder, 'Wired.epub')
        with zipfile.ZipFile(self.epub, 'w') as epub:
            epub.writestr('META-INF/container.xml', CONTAINER)
            epub.writestr('OEBPS/content.opf', OPF)
            epub.writestr('OEBPS/images/cover art.png', picture(50, 'PNG'))

    def test_pdf_pages(self):
        self.assertEqual(pages.page_count(self.pdf), 2)
        page = pages.page_image(self.pdf, 2, width=100)
        self.assertEqual(page[:3], b'\xff\xd8\xff', 'A JPEG')
        self.assertEqual(jpeg_width(page), 100)
        self.assertEqual(jpeg_width(pages.page_image(self.pdf, 1)), round(200 * 150 / 72), 'Drawn at 150dpi')
        self.assertEqual(pages.page_image(self.pdf, 3), b'')
        self.assertEqual(pages.page_image(self.pdf, 0), b'')

    def test_archive_pages_in_order(self):
        self.assertEqual(pages.page_count(self.cbz), 3, "Hidden files aren't pages")
        self.assertEqual([jpeg_width(pages.page_image(self.cbz, n)) for n in (1, 2, 3)], [10, 20, 30])
        self.assertEqual(jpeg_width(pages.page_image(self.cbz, 3, width=15)), 15)
        self.assertEqual(pages.page_image(self.cbz, 4), b'')

    def test_epub_cover(self):
        self.assertEqual(Image.open(io.BytesIO(pages.epub_cover(self.epub))).width, 50,
                         'The cover its package names, its name escaped there')
        self.assertEqual(pages.epub_cover(self.cbz), b'')
        self.assertFalse(pages.is_paged(self.epub))
        self.assertEqual(pages.page_count(os.path.join(self.folder, 'missing.pdf')), 0)

    def test_what_files_say(self):
        meta = filemeta.read_metadata(self.pdf)
        self.assertEqual((meta['series'], meta['date'], meta['description'], meta['pages']),
                         ('Wired', '2024-05-01', 'The AI issue', 2), "LazyLibrarian's own tags win")
        meta = filemeta.read_metadata(self.epub)
        self.assertEqual((meta['title'], meta['series'], meta['number'], meta['date'], meta['description'],
                          meta['publisher'], meta['language']),
                         ('Wired May 2024', 'Wired', '5', '2024-05-01', 'The AI issue', 'Conde Nast', 'en'))
        meta = filemeta.read_metadata(self.cbz)
        self.assertEqual((meta['series'], meta['number'], meta['volume'], meta['date'], meta['description'],
                          meta['publisher'], meta['pages']), ('Saga', '12', '1', '2013-05', 'Space opera', 'Image', 3))
        self.assertEqual(filemeta.issue_details(meta, '2013-05-01'), ('Space opera', 3, 'Vol 1 #12'))
        self.assertEqual(filemeta.issue_details(meta, '0012'), ('Space opera', 3, ''),
                         'No number when the issue is known by it')
        self.assertEqual(filemeta.read_metadata(os.path.join(self.folder, 'missing.pdf'))['pages'], 0)

    def test_dates(self):
        self.assertEqual(filemeta._date('D:20240501120000Z'), '2024-05-01')
        self.assertEqual(filemeta._date('2024-05'), '2024-05')
        self.assertEqual(filemeta._date('0000'), '')
        self.assertEqual(filemeta._date('soon'), '')


if __name__ == '__main__':
    unittest.main()
