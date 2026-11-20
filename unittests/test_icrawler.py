#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test that Pillow opens only the image formats LazyLibrarian expects: a cover or page from a
#   download or a web search can be any file, and another of Pillow's decoders (EPS runs Ghostscript)
#   is more of it a crafted one can reach. icrawler's downloader, which keeps a search's images,
#   and images.save_jpeg, which converts a cover

import io
import os
import shutil
import tempfile
from types import SimpleNamespace

from PIL import Image

from lazylibrarian import images, pages
from lib.icrawler import ImageDownloader
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS

EPS = b'%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n'


def picture(kind: str) -> bytes:
    data = io.BytesIO()
    Image.new('RGB', (10, 20), 'red').save(data, kind)
    return data.getvalue()


class ImageFormatsTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_search_keeps_only_the_formats_expected(self):
        downloader = ImageDownloader.__new__(ImageDownloader)  # keep_file needs none of its threads
        for kind in ('PNG', 'WEBP', 'GIF', 'BMP', 'JPEG'):
            task = {}
            self.assertTrue(downloader.keep_file(task, SimpleNamespace(content=picture(kind))), kind)
            self.assertEqual(task['img_size'], (10, 20))
        self.assertFalse(downloader.keep_file({}, SimpleNamespace(content=EPS)), 'Never handed to Ghostscript')
        self.assertFalse(downloader.keep_file({}, SimpleNamespace(content=picture('TIFF'))))

    def test_a_cover_converted_only_from_the_formats_expected(self):
        cover = os.path.join(self.root, 'cover.jpg')
        self.assertTrue(images.save_jpeg(picture('PNG'), cover))
        with Image.open(cover) as saved:
            self.assertEqual((saved.format, saved.size), ('JPEG', (10, 20)))
        os.remove(cover)
        self.assertFalse(images.save_jpeg(EPS, cover))
        self.assertFalse(os.path.exists(cover))
        self.assertEqual(pages.IMAGE_FORMATS, ('JPEG', 'PNG', 'WEBP', 'GIF', 'BMP'))
