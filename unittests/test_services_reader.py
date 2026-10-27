#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/reader.py: an item's file and pages for the reader, and Send to Device. And the
#   covers an issue's pages make, for magazines and comics

import io
import os
from unittest import mock

from PIL import Image
from pypdf import PdfWriter

from lazylibrarian import auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    comics,
    commands,
    magazines,
    reader,
)
from unittests.unittesthelpers import TESTDIR, LLTestCaseWithDB


def touch(path, data: bytes = b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for number in range(pages):
        writer.add_blank_page(width=100 * (number + 1), height=300)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def cbz(widths: list[int]) -> bytes:
    import zipfile
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for number, width in enumerate(widths, start=1):
            image = io.BytesIO()
            Image.new('RGB', (width, 20)).save(image, 'JPEG')
            archive.writestr(f'{number:03d}.jpg', image.getvalue())
    return out.getvalue()


class ReaderTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        saved = {k: CONFIG[k] for k in ('EBOOK_TYPE', 'IMP_MAGCOVER', 'IMP_CONVERT')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(k, v) for k, v in saved.items()])
        CONFIG.set_csv('EBOOK_TYPE', 'epub, pdf')
        CONFIG.set_from_ui('IMP_CONVERT', '')
        root = os.path.join(TESTDIR, 'reader')
        self.epub = touch(os.path.join(root, 'Witching', 'Witching.epub'))
        self.bookpdf = touch(os.path.join(root, 'Witching', 'Witching.pdf'), pdf(1))
        self.issue = touch(os.path.join(root, 'Wired', 'Wired 2026-01.pdf'), pdf(3))
        self.comic = touch(os.path.join(root, 'Saga', 'Saga 54.cbz'), cbz([10, 20]))
        os.makedirs(os.path.join(DIRS.CACHEDIR, 'magazine'), exist_ok=True)
        os.makedirs(os.path.join(DIRS.CACHEDIR, 'comic'), exist_ok=True)
        self.sql("UPDATE users SET UserID='u123456789', Perms=65535, BookType='pdf', SendTo='a@k.com'")
        auth.reset_owner_cache()
        self.addCleanup(auth.reset_owner_cache)
        self.sql("INSERT INTO authors (AuthorID,AuthorName) VALUES ('A1','Anne Rice')")
        self.sql("INSERT INTO books (BookID,AuthorID,BookName,BookFile) VALUES ('B1','A1','Witching',?)", (self.epub,))
        self.sql("INSERT INTO magazines (Title, IssueDate, CoverPage) VALUES ('Wired', '2026-01', 3)")
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES ('Wired','I1','2026-01',?)",
                 (self.issue,))
        self.sql("INSERT INTO comics (ComicID,Title) VALUES ('CV1','Saga')")
        self.sql("INSERT INTO comicissues (ComicID,IssueID,IssueFile) VALUES ('CV1','54',?)", (self.comic,))

    def test_files(self):
        found = reader.item_file('book', 'B1')
        self.assertEqual((found['path'], found['format'], found['formats']), (self.bookpdf, 'pdf', ['epub', 'pdf']),
                         "The owner's preferred format")
        self.assertEqual(reader.item_file('book', 'B1', 'epub')['path'], self.epub)
        with self.assertRaisesRegex(NotFoundError, 'only epub, pdf'):
            reader.item_file('book', 'B1', 'mobi')
        self.assertEqual(reader.item_file('issue', 'I1')['name'], 'Wired 2026-01.pdf')
        self.assertEqual(reader.item_file('comic', 'CV1_54')['name'], 'Saga 54.cbz')
        with self.assertRaises(NotFoundError):
            reader.item_file('comic', 'CV1_55')
        with self.assertRaises(InvalidRequestError):
            reader.item_file('film', 'B1')

    def test_reading(self):
        self.assertEqual(reader.reading('issue', 'I1'),
                         {'title': 'Wired 2026-01', 'format': 'pdf', 'formats': [], 'reader': 'pdf', 'pages': 3})
        self.assertEqual(reader.reading('comic', 'CV1_54')['pages'], 2)
        self.assertEqual(reader.reading('book', 'B1', 'epub')['reader'], 'epub')
        self.assertEqual(Image.open(io.BytesIO(reader.page('comic', 'CV1_54', 2))).width, 20)
        with self.assertRaisesRegex(NotFoundError, 'no page 9'):
            reader.page('issue', 'I1', 9)

    def test_send_to_device(self):
        with mock.patch.object(reader.delivery, 'email_file', return_value=(['a@k.com'], [])) as email:
            self.assertEqual(reader.send('issue', 'I1'), 'Sent Wired 2026-01 to a@k.com')
        email.assert_called_once_with('u123456789', self.issue, 'Wired 2026-01')
        with mock.patch.object(reader.delivery, 'email_file', return_value=([], ['a@k.com'])), \
                self.assertRaisesRegex(InvalidRequestError, 'failed'):
            reader.send('issue', 'I1')
        self.sql("UPDATE users SET SendTo=''")
        with self.assertRaisesRegex(InvalidRequestError, 'Settings, Connect'):
            reader.send('issue', 'I1')

    def test_issue_covers(self):
        self.assertEqual(magazines.set_issue_cover('I1', 2), 'The cover is page 2 now')
        cover = self.sql("SELECT Cover FROM issues WHERE IssueID='I1'")[0]['Cover']
        self.assertTrue(cover.startswith('cache/magazine/'))
        self.assertEqual(Image.open(os.path.join(DIRS.DATADIR, cover)).width, round(200 * 150 / 72))
        self.assertEqual(self.sql("SELECT LatestCover FROM magazines")[0]['LatestCover'], cover,
                         "The latest issue's is the magazine's")
        with self.assertRaisesRegex(InvalidRequestError, 'no page 12'):
            magazines.set_issue_cover('I1', 12)
        self.assertEqual(magazines.cover_page(issueid='I1'), 3)

        self.assertEqual(comics.set_issue_cover('CV1', '54', 2), 'The cover is page 2 now')
        cover = self.sql("SELECT Cover FROM comicissues")[0]['Cover']
        self.assertEqual(Image.open(os.path.join(DIRS.DATADIR, cover)).width, 20)
        self.assertEqual(self.sql("SELECT LatestCover FROM comics")[0]['LatestCover'], cover,
                         'The cached cover, not a picture next to the file')

        self.assertEqual(magazines.set_issue_cover('I1', 0), 'It has no cover now')
        self.assertEqual(comics.set_issue_cover('CV1', '54', 0), 'It has no cover now')
        cover = self.sql("SELECT Cover FROM comicissues")[0]['Cover']
        self.assertTrue(os.path.exists(os.path.join(DIRS.DATADIR, cover)), 'The no cover picture, cached')

    def test_cover_commands(self):
        command = {'id': 0}
        with mock.patch.object(commands, '_update'):
            self.assertEqual(commands._issue_covers(command, {'title': 'Wired'}), 'Made covers from page 3 for 1 issue',
                             "The magazine's cover page")
            self.assertEqual(commands._issue_covers(command, {'media_type': 'comic', 'ids': ['CV1_54'], 'page': 1}),
                             'Made the covers of 1 issue')
            with self.assertRaisesRegex(InvalidRequestError, 'Which issues'):
                commands._swap_cover(command, {})
