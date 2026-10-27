#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

""" The pages of an issue or book file: how many a PDF or comic archive (cbz, cbr, cb7) has, and
each one as a JPEG, PDFs drawn by pdfium so no other program is needed. And an EPUB's cover, the
one its package names """

import contextlib
import io
import logging
import posixpath
import threading
import zipfile
from urllib.parse import unquote
from xml.etree import ElementTree

import lazylibrarian
from lazylibrarian.filesystem import splitext, syspath
from lazylibrarian.formatter import natural_sort

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None
try:
    from PIL import Image
except ImportError:
    Image = None

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
ARCHIVES = ('.cbz', '.cbr', '.cb7')
PAGED = ('.pdf', *ARCHIVES)
# pdfium isn't thread safe
_pdfium_lock = threading.Lock()


def _extension(path) -> str:
    return splitext(str(path))[1].lower()


def is_paged(path) -> bool:
    """ Whether a file is one these pages can be drawn from """
    return _extension(path) in PAGED


class _Archive:
    """ A comic archive's images, in page order: names sorted as people number pages """

    def __init__(self, path):
        extn = _extension(path)
        self.read = None
        names = []
        if extn in ('.cbz', '.epub'):
            self._zip = zipfile.ZipFile(syspath(path))
            names = self._zip.namelist()
            self.read = self._zip.read
        elif extn == '.cbr' and lazylibrarian.UNRARLIB == 1:
            self._zip = lazylibrarian.RARFILE.RarFile(syspath(path))
            names = self._zip.namelist()
            self.read = self._zip.read
        elif extn == '.cbr' and lazylibrarian.UNRARLIB == 2:
            self._zip = lazylibrarian.RARFILE(syspath(path))
            names = [member.filename for member in self._zip.infoiter()]
            self.read = lambda name: self._zip.read_files(name)[0][1]
        elif extn == '.cb7':
            import py7zr  # noqa: PLC0415, optional
            self._zip = py7zr.SevenZipFile(syspath(path), mode='r')
            names = self._zip.getnames()

            def read(name):
                self._zip.reset()
                return self._zip.read([name])[name].read()
            self.read = read
        self.pages = [name for name in names if name.lower().endswith(IMAGE_EXTENSIONS)
                      and not posixpath.basename(name).startswith('.')]
        natural_sort(self.pages, key=lambda name: name.lower())

    def close(self):
        with contextlib.suppress(Exception):
            self._zip.close()


def page_count(path) -> int:
    """ How many pages a PDF or comic archive has, 0 when it can't be read """
    try:
        if _extension(path) == '.pdf':
            if not pdfium:
                from lazylibrarian.images import pdf_pagecount  # noqa: PLC0415, it imports a lot
                return pdf_pagecount(path)
            with _pdfium_lock:
                pdf = pdfium.PdfDocument(syspath(path))
                try:
                    return len(pdf)
                finally:
                    pdf.close()
        if _extension(path) in ARCHIVES:
            archive = _Archive(path)
            try:
                return len(archive.pages)
            finally:
                archive.close()
    except Exception as why:
        logging.getLogger(__name__).warning(f"Can't count the pages of {path}: {type(why).__name__} {why}")
    return 0


def _jpeg(image, width: int) -> bytes:
    if width and image.width > width:
        image = image.resize((width, max(1, round(image.height * width / image.width))), Image.LANCZOS)
    out = io.BytesIO()
    image.convert('RGB').save(out, 'jpeg', quality=85)
    return out.getvalue()


def page_image(path, page: int = 1, width: int = 0) -> bytes:
    """ A page, counted from 1, as a JPEG no wider than width (when given), b'' if there's no such
    page or it can't be drawn """
    logger = logging.getLogger(__name__)
    if page < 1:
        return b''
    try:
        if _extension(path) == '.pdf':
            if not pdfium or not Image:
                return b''
            with _pdfium_lock:
                pdf = pdfium.PdfDocument(syspath(path))
                try:
                    if page > len(pdf):
                        return b''
                    pdf_page = pdf[page - 1]
                    # drawn at 150dpi, or just big enough for the width asked for
                    scale = width / pdf_page.get_width() if width else 150 / 72
                    image = pdf_page.render(scale=min(scale, 4)).to_pil()
                    pdf_page.close()
                finally:
                    pdf.close()
            return _jpeg(image, width)
        if _extension(path) in ARCHIVES:
            archive = _Archive(path)
            try:
                if page > len(archive.pages):
                    return b''
                data = archive.read(archive.pages[page - 1])
            finally:
                archive.close()
            if not Image:
                return data
            return _jpeg(Image.open(io.BytesIO(data)), width)
    except Exception as why:
        logger.warning(f"Can't draw page {page} of {path}: {type(why).__name__} {why}")
    return b''


def epub_package(epub: zipfile.ZipFile) -> tuple[str, ElementTree.Element]:
    """ An EPUB's package file: its path in the zip and its root """
    container = ElementTree.fromstring(epub.read('META-INF/container.xml'))
    rootfile = next(el for el in container.iter() if el.tag.endswith('rootfile'))
    name = rootfile.get('full-path')
    return name, ElementTree.fromstring(epub.read(name))


def epub_cover(path) -> bytes:
    """ The cover an EPUB's package names, EPUB 3's cover-image or EPUB 2's cover meta, b'' if
    it names none """
    try:
        with zipfile.ZipFile(syspath(path)) as epub:
            name, opf = epub_package(epub)
            items = [el for el in opf.iter() if el.tag.endswith('}item') or el.tag == 'item']
            cover = next((item for item in items if 'cover-image' in (item.get('properties') or '').split()), None)
            if cover is None:
                meta = next((el for el in opf.iter() if el.tag.endswith('meta') and el.get('name') == 'cover'), None)
                if meta is not None:
                    cover = next((item for item in items if item.get('id') == meta.get('content')), None)
            if cover is None or not (cover.get('media-type') or '').startswith('image/'):
                return b''
            href = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(cover.get('href'))))
            return epub.read(href)
    except Exception as why:
        logging.getLogger(__name__).debug(f"No cover named in {path}: {type(why).__name__} {why}")
    return b''
