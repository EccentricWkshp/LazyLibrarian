#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/delivery.py

import os
from unittest import mock

from lazylibrarian import notifiers
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import NotFoundError, delivery
from unittests.unittesthelpers import TESTDIR, LLTestCaseWithDB


def touch(path, text='x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)
    return path


class DeliveryServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        saved = {k: CONFIG[k] for k in ('EBOOK_TYPE', 'MAG_SINGLE', 'COMIC_SINGLE', 'RSS_PODCAST')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(k, v) for k, v in saved.items()])
        CONFIG.set_csv('EBOOK_TYPE', 'epub, mobi, pdf')
        root = os.path.join(TESTDIR, 'delivery')
        self.epub = touch(os.path.join(root, 'Witching', 'Witching.epub'))
        self.mobi = touch(os.path.join(root, 'Witching', 'Witching.mobi'))
        self.single = touch(os.path.join(root, 'Lasher', 'Lasher.epub'))
        audiodir = os.path.join(root, 'Audio')
        self.part1 = touch(os.path.join(audiodir, 'Audio - 01.mp3'))
        self.part2 = touch(os.path.join(audiodir, 'Audio - 02.mp3'))
        touch(os.path.join(audiodir, 'playlist.ll'), 'Audio - 01.mp3\nAudio - 02.mp3\n')
        self.issue = touch(os.path.join(root, 'Wired', 'Wired 2026-01.pdf'))
        self.comic = touch(os.path.join(root, 'Saga', 'Saga 54.cbz'))
        self.sql("UPDATE users SET UserID='u123456789', Perms=65535, BookType='mobi', SendTo='a@k.com,b@k.com'")
        self.sql("INSERT INTO authors (AuthorID,AuthorName) VALUES ('A1','Anne Rice')")
        for bookid, name, bookfile, audiofile in (('B1', 'Witching', self.epub, ''), ('B2', 'Lasher', self.single, ''),
                                                  ('B3', 'Audio', '', self.part1), ('B4', 'Gone', '/no/such.epub', '')):
            self.sql("INSERT INTO books (BookID,AuthorID,BookName,BookFile,AudioFile,BookImg) VALUES (?,'A1',?,?,?,'')",
                     (bookid, name, bookfile, audiofile))
        self.sql("INSERT INTO magazines (Title) VALUES ('Wired'),('Empty')")
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES ('Wired','I1','2026-01',?)",
                 (self.issue,))
        self.sql("INSERT INTO comics (ComicID,Title) VALUES ('CV1','Saga')")
        self.sql("INSERT INTO comicissues (ComicID,IssueID,IssueFile) VALUES ('CV1','54',?)", (self.comic,))
        names = mock.patch.object(delivery, 'name_vars', return_value={'AudioSingleFile': 'Audio'})
        names.start()
        self.addCleanup(names.stop)

    def test_ebook_formats(self):
        self.assertEqual(delivery.ebook_formats(self.epub), ['epub', 'mobi'])

    def test_book_formats(self):
        found = delivery.book_to_open('B1', 'eBook')
        self.assertEqual((found['action'], found['formats'], found['unavailable']), ('formats', ['epub', 'mobi'], ''))
        self.assertEqual(delivery.book_to_open('B1', 'eBook', preftype='mobi')['path'], self.mobi)
        self.assertEqual(delivery.book_to_open('B1', 'eBook', booktype='pdf', preftype='mobi')['unavailable'], 'pdf')
        self.assertEqual(delivery.book_to_open('B2', 'eBook')['path'], self.single)
        self.assertEqual(delivery.book_to_open('B4', 'eBook')['action'], 'missing')
        with self.assertRaises(NotFoundError):
            delivery.book_to_open('nosuch', 'eBook')

    def test_audiobook_parts(self):
        self.assertEqual(delivery.book_to_open('B3', 'AudioBook'), {
            'action': 'parts', 'count': 2, 'whole': False, 'library': 'AudioBook', 'author': 'Anne Rice',
            'title': 'Audio'})
        found = delivery.book_to_open('B3', 'AudioBook', booktype='2')
        self.assertEqual((found['path'], found['name']), (self.part2, 'Audio part2.mp3'))
        self.assertEqual(delivery.book_to_open('B3', 'eBook')['action'], 'missing', 'No ebook of it')

    def test_magazine(self):
        CONFIG.set_bool('MAG_SINGLE', False)
        self.assertEqual(delivery.magazine_to_open('I1')['path'], self.issue)
        self.assertEqual(delivery.magazine_to_open('wired')['action'], 'list')
        CONFIG.set_bool('MAG_SINGLE', True)
        self.assertEqual(delivery.magazine_to_open('Wired')['name'], 'Wired 2026-01.pdf')
        self.assertEqual(delivery.magazine_to_open('Empty'), {'action': 'missing', 'title': 'Empty', 'issuedate': None})
        with self.assertRaises(NotFoundError):
            delivery.magazine_to_open('nosuch')

    def test_comic(self):
        CONFIG.set_bool('COMIC_SINGLE', False)
        self.assertEqual(delivery.comic_to_open('CV1', '54')['name'], 'Saga 54.cbz')
        self.assertEqual(delivery.comic_to_open('CV1_54')['action'], 'list')
        CONFIG.set_bool('COMIC_SINGLE', True)
        self.assertEqual(delivery.comic_to_open('CV1')['path'], self.comic)
        with self.assertRaises(NotFoundError):
            delivery.comic_to_open('nosuch')

    def test_feed_file(self):
        self.assertEqual(delivery.feed_file('u123456789B1', 'book'), (self.mobi, None), 'The user wants mobi')
        self.assertEqual(delivery.feed_file('u123456789I1.pdf', 'issue'), (self.issue, 'Wired I1.pdf'))
        self.assertEqual(delivery.feed_file('u123456789CV1_54', 'comic'), (self.comic, 'Saga 54.cbz'))
        with mock.patch.object(delivery, 'zip_audio', return_value=None):
            self.assertEqual(delivery.feed_file('u123456789B3', 'audio'), (self.part1, None))
        logo = delivery.feed_file('u123456789B1', 'img')
        self.assertTrue(logo is None or logo[0].endswith('ll192.png'), 'No cover, the logo if it can be found')
        self.assertIsNone(delivery.feed_file('short', 'book'))
        self.assertIsNone(delivery.feed_file('u000000000B1', 'book'), 'No such user')
        self.sql("UPDATE users SET Perms=0")
        self.assertIsNone(delivery.feed_file('u123456789B1', 'book'), 'Not allowed to download')

    def test_email_file(self):
        with mock.patch.object(notifiers.email_notifier, 'email_file',
                               side_effect=lambda **kw: kw['to_addr'] == 'a@k.com') as email:
            self.assertEqual(delivery.email_file('u123456789', self.epub, 'Witching'), (['a@k.com'], ['b@k.com']))
        self.assertEqual(email.call_count, 2, 'One email each, kindles need that')
        self.assertEqual(self.sql('SELECT Addr,FileName FROM sent_file'), [{'Addr': 'a@k.com',
                                                                            'FileName': 'Witching.epub'}])
        self.sql("UPDATE users SET SendTo=''")
        self.assertEqual(delivery.email_file('u123456789', self.epub), ([], []))
