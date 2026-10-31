#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/comics.py

from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import InvalidRequestError, NotFoundError, comics
from unittests.unittesthelpers import LLTestCaseWithDB

RESULT = {'seriesid': 'CV7', 'title': 'Paper Girls', 'searchterm': 'paper girls', 'start': '2015', 'first': '1',
          'last': '30', 'publisher': 'Image', 'link': 'http://cv/7'}


class ComicServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        for cid, title, latest in (('CV1', 'Saga', '54'), ('CV2', 'batman', '3'), ('CX3', 'Monstress', '')):
            self.sql("INSERT INTO comics (ComicID,Title,Status,LatestIssue,IssueStatus,aka,Description) "
                     "VALUES (?,?,'Active',?,'Wanted','','')", (cid, title, latest))
        for cid, iid in (('CV1', '54'), ('CV1', '9'), ('CV1', '10'), ('CV2', '3')):
            self.sql("INSERT INTO comicissues (ComicID,IssueID,IssueFile) VALUES (?,?,'/no/such.cbz')", (cid, iid))
        self.owner = self.sql('SELECT UserID FROM users')[0]['UserID']
        self.addCleanup(setattr, comics, 'found_comics', [])

    def ids(self, page):
        return [c['ComicID'] for c in page.items]

    def test_list_comics(self):
        page = comics.list_comics()
        self.assertEqual(self.ids(page), ['CV2', 'CX3', 'CV1'], 'Titles ignore case')
        self.assertEqual([c['Iss_Cnt'] for c in page.items], [1, 0, 3])
        self.assertEqual(self.ids(comics.list_comics(search='saga')), ['CV1'])

    def test_a_cover_when_the_latest_issue_has_none(self):
        from lazylibrarian.services import library
        self.sql("UPDATE comicissues SET Cover='cache/comic/9.jpg' WHERE ComicID='CV1' AND IssueID='9'")
        self.sql("UPDATE comicissues SET Cover='cache/comic/10.jpg' WHERE ComicID='CV1' AND IssueID='10'")
        self.sql("UPDATE comicissues SET Cover='images/nocover.png' WHERE ComicID='CV1' AND IssueID='54'")
        self.assertEqual(library.get_comic('CV1')['cover'], 'cache/comic/10.jpg', 'Issue 10 is newer than 9')
        self.assertEqual([c['cover'] for c in library.list_comics() if c['id'] == 'CV1'], ['cache/comic/10.jpg'])

    def test_list_subscribed(self):
        self.sql("INSERT INTO subscribers (UserID,Type,WantID) VALUES (?,'comic','CV1'),(?,'comic','CX3')",
                 (self.owner, self.owner))
        self.assertEqual(self.ids(comics.list_comics(subscriber=self.owner)), ['CX3', 'CV1'])

    def test_list_issues(self):
        page = comics.list_issues('CV1')
        self.assertEqual([i['IssueID'] for i in page.items], ['54', '10', '9'], 'Newest first, numbers by value')
        self.assertEqual([i['IssueID'] for i in comics.list_issues('CV1', descending=False).items], ['9', '10', '54'])
        self.assertEqual(page.items[0]['Title'], 'Saga')
        with self.assertRaises(NotFoundError):
            comics.list_issues('nosuch')

    def test_update_comic(self):
        self.assertEqual(comics.update_comic('CV1', 'Saga!', 'CV2', 'S', 'd'), 'CV1', 'CV2 is taken')
        self.assertEqual(comics.update_comic('CV1', 'Saga!', 'CV9', 'S', 'd'), 'CV9')
        self.assertEqual(self.sql("SELECT Title FROM comics WHERE ComicID='CV9'")[0]['Title'], 'Saga!')
        self.assertEqual(len(self.sql("SELECT * FROM comicissues WHERE ComicID='CV9'")), 3)
        with self.assertRaises(NotFoundError):
            comics.update_comic('CV1', 'x', 'x', '', '')

    def test_find_and_add(self):
        self.assertIsNone(comics.find_comics('Saga'), 'We have it already')
        with mock.patch.object(comics, 'cv_identify', side_effect=[[dict(RESULT)], []]), \
                mock.patch.object(comics, 'cx_identify', return_value=[]):
            results = comics.find_comics('"Paper Girls"')
        self.assertEqual([r['seriesid'] for r in results], ['CV7'])
        self.addCleanup(CONFIG.set_from_ui, 'CV_APIKEY', CONFIG['CV_APIKEY'])
        CONFIG.set_str('CV_APIKEY', '')
        with self.assertRaises(InvalidRequestError):
            comics.add_comic('CV7')
        CONFIG.set_str('CV_APIKEY', 'key')
        with self.assertRaises(NotFoundError):
            comics.add_comic('CV8')
        with mock.patch.object(comics, 'cv_identify', return_value=[]), \
                mock.patch.object(comics, 'cx_identify', return_value=[]), \
                mock.patch.object(comics, 'start_search'):
            self.assertTrue(comics.add_comic('CV7'))
            self.assertFalse(comics.add_comic('CV7'), 'Already added')
        self.assertEqual(self.sql("SELECT Title,Publisher FROM comics WHERE ComicID='CV7'")[0],
                         {'Title': 'Paper Girls', 'Publisher': 'Image'})

    def test_mark_comics(self):
        self.assertEqual(comics.mark_comics('Paused', ['CV1']), 1)
        comics.mark_comics('Subscribe', ['CV1'], self.owner)
        comics.mark_comics('Subscribe', ['CV1'], self.owner)
        self.assertEqual(len(self.sql('SELECT * FROM subscribers')), 1)
        comics.mark_comics('Unsubscribe', ['CV1'], self.owner)
        self.assertEqual(self.sql('SELECT * FROM subscribers'), [])
        comics.mark_comics('Reset', ['CV1'])
        self.assertEqual(self.sql("SELECT LatestIssue,Status FROM comics WHERE ComicID='CV1'")[0],
                         {'LatestIssue': '', 'Status': 'Paused'})
        comics.mark_comics('Remove', ['CX3'])
        self.assertEqual(self.sql("SELECT * FROM comics WHERE ComicID='CX3'"), [])
        self.assertEqual(comics.mark_comics('Nothing', ['CV1']), 0)

    def test_mark_issues(self):
        self.assertEqual(comics.mark_issues('Remove', ['CV1_54', 'CV1_99']), 'CV1')
        self.assertEqual(self.sql("SELECT LatestIssue FROM comics WHERE ComicID='CV1'")[0]['LatestIssue'], '10',
                         'The newest left, by number: 10 is newer than 9')
        comics.mark_issues('Remove', ['CV2_3'])
        self.assertEqual(self.sql("SELECT LatestIssue FROM comics WHERE ComicID='CV2'")[0]['LatestIssue'], '')

    def test_a_scan_doesnt_open_the_issues_it_has(self):
        """ An issue the library has is known by its file, which isn't opened again, and the comic's
        latest issue is the highest numbered, with its cover """
        import os
        import shutil

        from lazylibrarian import comicscan
        from unittests.unittesthelpers import TESTDIR
        root = os.path.join(TESTDIR, 'comicscan')
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for issue in ('9', '10'):
            name = os.path.join(root, f'Saga {issue}.cbz')
            with open(name, 'wb') as f:
                f.write(b'PK')
            self.sql("UPDATE comicissues SET IssueFile=?, Pages=20, Cover=? WHERE ComicID='CV1' AND IssueID=?",
                     (name, f'cache/comic/{issue}.jpg', issue))
        self.sql("DELETE FROM comicissues WHERE ComicID='CV1' AND IssueID='54'")
        saved = CONFIG.get_bool('FULL_SCAN')
        self.addCleanup(CONFIG.set_from_ui, 'FULL_SCAN', saved)
        CONFIG.set_from_ui('FULL_SCAN', False)
        with mock.patch.object(comicscan, 'issue_folder', return_value=root), \
                mock.patch.object(comicscan, 'comic_metadata', side_effect=AssertionError('opened')) as opened, \
                mock.patch.object(comicscan, 'create_mag_cover') as made:
            comicscan.comic_scan()
        opened.assert_not_called()
        made.assert_not_called()
        self.assertEqual(self.sql("SELECT LatestIssue, LatestCover FROM comics WHERE ComicID='CV1'"),
                         [{'LatestIssue': '10', 'LatestCover': 'cache/comic/10.jpg'}], '10 is after 9')

    def test_scan_and_search(self):
        with mock.patch.object(comics, 'start_task', return_value=True) as start:
            comics.start_scan('CV1')
            comics.start_scan()
        self.assertEqual([c.args[0] for c in start.call_args_list], ['COMICSCAN_CV1', 'COMICSCAN'])
        with mock.patch.object(CONFIG, 'use_any', return_value=False):
            self.assertFalse(comics.start_search('CV1'))
        with self.assertRaises(NotFoundError):
            comics.search_for_comic('nosuch')
