#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/magazines.py

import logging
import os
import shutil
from unittest import mock

import lazylibrarian
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.services import InvalidRequestError, NotFoundError, magazines
from lazylibrarian.startup import StartupLazyLibrarian
from unittests.unittesthelpers import TESTDIR, LLTestCaseWithDB


class MagazineServiceTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, lazylibrarian, 'MONTHNAMES', lazylibrarian.MONTHNAMES)
        startup = StartupLazyLibrarian()
        startup.logger = logging.getLogger(__name__)
        lazylibrarian.MONTHNAMES, _ = startup.build_monthtable(CONFIG)
        for title, issuedate, genre in (('Wired', '2026-01', 'Tech'), ('another', '2025-02', ''),
                                        ('Zine', '2025-10', None)):
            self.sql("INSERT INTO magazines (Title,Status,IssueDate,Genre,IssueStatus,DateType) "
                     "VALUES (?,'Active',?,?,'Wanted','')", (title, issuedate, genre))
        for title, issueid, date in (('Wired', 'I1', '2026-01'), ('Wired', 'I2', '2025-12'), ('Zine', 'I3', '2025-10')):
            self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile,Cover) VALUES (?,?,?,'/no/such.pdf','')",
                     (title, issueid, date))
        for url, status in (('http://a?x=1&y=2', 'Skipped'), ('http://b', 'Skipped'), ('http://c', 'Ignored')):
            self.sql("INSERT INTO pastissues (NZBurl,NZBtitle,Status,BookID,NZBprov,NZBmode,NZBsize,AuxInfo) "
                     "VALUES (?,'Wired.Jan',?,'Wired','prov','nzb','10','2026-01')", (url, status))
        self.owner = self.sql('SELECT UserID FROM users')[0]['UserID']

    def titles(self, page):
        return [m['Title'] for m in page.items]

    def test_list_magazines(self):
        page = magazines.list_magazines()
        self.assertEqual(self.titles(page), ['another', 'Wired', 'Zine'], 'Titles ignore case')
        self.assertEqual([m['Iss_Cnt'] for m in page.items], [0, 2, 1])
        self.assertEqual(self.titles(magazines.list_magazines(sort='IssueDate', descending=True))[0], 'Wired')
        self.assertEqual(self.titles(magazines.list_magazines(search='tech')), ['Wired'])

    def test_list_subscribed(self):
        self.sql("INSERT INTO subscribers (UserID,Type,WantID) VALUES (?,'magazine','Zine'),(?,'magazine','Wired')",
                 (self.owner, self.owner))
        self.assertEqual(self.titles(magazines.list_magazines(subscriber=self.owner)), ['Wired', 'Zine'])

    def test_get_magazine(self):
        self.assertEqual(magazines.get_magazine('wired')['Title'], 'Wired')
        with self.assertRaises(NotFoundError):
            magazines.get_magazine('nosuch')

    def test_rename_magazine(self):
        with self.assertRaises(InvalidRequestError):
            magazines.rename_magazine('Wired', 'zine')
        with mock.patch.object(magazines, 'rename_issue', side_effect=[('/x/a.pdf', ''), ('', 'locked')]):
            self.assertEqual(magazines.rename_magazine('Wired', 'Wired UK'), (1, 1))
        self.assertEqual([r['Title'] for r in self.sql("SELECT Title FROM issues WHERE IssueID IN ('I1','I2')")],
                         ['Wired UK', 'Wired UK'])
        self.assertEqual(magazines.issue_progress, '')

    def test_list_issues(self):
        page = magazines.list_issues('Wired')
        self.assertEqual([i['IssueID'] for i in page.items], ['I1', 'I2'])
        self.assertEqual([i['IssueID'] for i in magazines.list_issues('Wired', descending=False).items], ['I2', 'I1'])

    def test_issue_for_edit(self):
        with mock.patch.object(magazines, 'read_pdf_tags', return_value={'/Title': 'x'}):
            issue, tags = magazines.issue_for_edit('I1')
        self.assertEqual((issue['Title'], tags), ('Wired', {'/Title': 'x'}))
        with self.assertRaises(NotFoundError):
            magazines.issue_for_edit('nosuch')

    def test_update_issue_unchanged_or_bad_date(self):
        self.assertIn('is unchanged', magazines.update_issue('I1', 'Wired', '2026-01', {}, {})[1])
        with self.assertRaisesRegex(InvalidRequestError, 'is no date'):
            magazines.update_issue('I1', 'Wired', 'sometime', {}, {})
        # numbered by its date type, and no name says which number February's is
        self.sql("UPDATE magazines SET DateType='VI' WHERE Title='Wired'")
        with self.assertRaisesRegex(InvalidRequestError, "Wired: dated 2026-02, but the magazine's issues are numbered"):
            magazines.update_issue('I1', 'Wired', '2026-02', {}, {})
        with self.assertRaises(NotFoundError):
            magazines.update_issue('nosuch', 'Wired', '2026-01', {}, {})

    def test_update_issue_to_a_new_magazine(self):
        with mock.patch.object(magazines, 'rename_issue', return_value=('/x/New 2026-01.pdf', '')), \
                mock.patch.object(magazines, 'remove_if_empty'):
            title, response = magazines.update_issue('I3', 'New Mag', '2025-10', {}, {})
        self.assertEqual(title, 'New Mag', 'Zine has no issues left')
        self.assertIn('changed to New 2026-01.pdf', response)
        self.assertEqual(self.sql("SELECT Title FROM issues WHERE IssueID='I3'")[0]['Title'], 'New Mag')
        self.assertEqual(self.sql("SELECT IssueDate FROM magazines WHERE Title='New Mag'")[0]['IssueDate'], '2025-10')
        with mock.patch.object(magazines, 'rename_issue', return_value=('', 'locked')), \
                self.assertRaises(InvalidRequestError):
            magazines.update_issue('I1', 'Wired', '2026-02', {}, {})

    def test_list_past_issues(self):
        self.assertEqual(len(magazines.list_past_issues('Skipped').items), 2)
        self.assertEqual(len(magazines.list_past_issues('Skipped', 'Zine').items), 0)

    def test_mark_past_issues(self):
        self.assertEqual(magazines.mark_past_issues('Ignored', ['http://a?x=1&amp;y=2', 'nosuch']), 1)
        self.assertEqual(self.sql("SELECT Status FROM pastissues WHERE NZBurl='http://a?x=1&y=2'")[0]['Status'],
                         'Ignored')
        with mock.patch.object(magazines.threading, 'Thread') as thread:
            self.assertEqual(magazines.mark_past_issues('Wanted', ['http://b']), 1)
        thread.assert_called_once()
        self.assertEqual(self.sql("SELECT BookID,Status FROM wanted"), [{'BookID': 'Wired', 'Status': 'Wanted'}])
        self.assertEqual(magazines.mark_past_issues('Remove', ['http://c']), 1)
        self.assertEqual(len(self.sql('SELECT * FROM pastissues')), 2)

    def test_mark_issues_remove(self):
        self.assertEqual(magazines.mark_issues('Remove', ['I1', 'nosuch']), (1, 0, 'Wired'))
        self.assertEqual(self.sql("SELECT IssueDate FROM magazines WHERE Title='Wired'")[0]['IssueDate'], '2025-12')
        self.assertEqual(magazines.mark_issues(None, ['I2']), (0, 0, ''))

    def test_set_latest(self):
        self.assertEqual(magazines.set_latest('Wired'), '2026-01')
        self.assertEqual(magazines.set_latest('another'), '')

    def test_mark_magazines(self):
        self.assertEqual(magazines.mark_magazines('Paused', ['Wired']), (1, 0))
        self.assertEqual(magazines.mark_magazines('Subscribe', ['Wired'], self.owner), (1, 0))
        self.assertEqual(magazines.mark_magazines('Subscribe', ['Wired'], self.owner), (0, 1))
        self.assertEqual(magazines.mark_magazines('Unsubscribe', ['Wired'], self.owner), (1, 0))
        self.assertEqual(magazines.mark_magazines('Reset', ['Wired']), (1, 0))
        self.assertEqual(self.sql("SELECT IssueDate,Status FROM magazines WHERE Title='Wired'")[0],
                         {'IssueDate': '', 'Status': 'Paused'})
        self.assertEqual(magazines.mark_magazines('Remove', ['Zine']), (1, 0))
        self.assertEqual(self.sql("SELECT * FROM magazines WHERE Title='Zine'"), [])

    def test_mark_stops_after_abort(self):
        with mock.patch.object(magazines, 'magazine_scan', side_effect=lambda title: magazines.abort_marking()):
            self.assertEqual(magazines.mark_magazines('Scan', ['Wired', 'Zine']), (1, 0))

    def test_add_magazine(self):
        self.assertEqual(magazines.clean_title('Rock & Roll + More ~ digest, special'),
                         ('Rock and Roll and More', 'digest, special'))
        self.assertEqual(magazines.add_magazine('wired'), ('Wired', False), 'The one there is')
        self.assertEqual(magazines.add_magazine('Rock & Roll ~ digest'), ('Rock and Roll', True))
        self.assertEqual(self.sql("SELECT Reject,Status FROM magazines WHERE Title='Rock and Roll'")[0],
                         {'Reject': 'digest', 'Status': 'Active'})

    def test_search(self):
        with mock.patch.object(CONFIG, 'use_any', return_value=False):
            self.assertFalse(magazines.start_search([{'bookid': 'Wired'}]))
        self.assertFalse(magazines.start_search([]))
        with self.assertRaises(NotFoundError):
            magazines.search_for_magazine('nosuch')

    def test_wikidata(self):
        details = {'id': 'Q520154', 'label': 'Wired', 'description': 'A magazine', 'publisher': 'Conde Nast',
                   'issn': '1059-1028', 'country': 'United States', 'frequency': 30, 'website': 'https://wired.com',
                   'logo': '', 'started': '1993', 'subjects': ['technology', 'culture', 'business', 'science']}
        found = [{'id': 'Q520154', 'label': 'Wired', 'description': '', 'started': ''},
                 {'id': 'Q8026784', 'label': 'Wired UK', 'description': '', 'started': ''}]
        with mock.patch.object(magazines.wikidata, 'search', return_value=found), \
                mock.patch.object(magazines.wikidata, 'details', return_value=details) as get:
            self.assertEqual(magazines.refresh_magazine('wired'), 'Wired is Wired on Wikidata (Q520154)',
                             'Linked to the one called exactly its title')
            self.assertEqual(magazines.refresh_magazine('Zine'),
                             "Zine wasn't linked to Wikidata, 2 close ones, choose one in Edit")
        get.assert_called_once_with('Q520154', 'en')
        row = self.sql("SELECT * FROM magazines WHERE Title='Wired'")[0]
        self.assertEqual((row['WikidataID'], row['Publisher'], row['Frequency'], row['Started'], row['Genre']),
                         ('Q520154', 'Conde Nast', 30, '1993', 'Tech'), 'Its own genres stay')
        self.assertEqual(self.sql("SELECT Genre FROM magazines WHERE Title='another'")[0]['Genre'], '')
        with mock.patch.object(magazines.wikidata, 'details', return_value=details):
            magazines.set_wikidata('another', 'Q520154')
        self.assertEqual(self.sql("SELECT Genre FROM magazines WHERE Title='another'")[0]['Genre'],
                         'technology, culture, business', 'The subjects are the genres of one without')
        self.assertEqual(magazines.set_wikidata('Wired', ''), "Wired isn't linked to Wikidata now")
        self.assertEqual(self.sql("SELECT WikidataID,Frequency FROM magazines WHERE Title='Wired'")[0],
                         {'WikidataID': '', 'Frequency': 0})
        with mock.patch.object(magazines.wikidata, 'details', return_value={}), \
                self.assertRaisesRegex(InvalidRequestError, 'no item Q1'):
            magazines.set_wikidata('Wired', 'Q1')

    def test_scan_takes_the_title_folder_below_the_library(self):
        from lazylibrarian import magazinescan
        self.assertEqual(magazinescan.title_folder(os.path.join('/m', 'Wood Magazine'), '/m', '$Title/$IssueDate'),
                         'Wood Magazine', "An issue kept less deep than the pattern")
        self.assertEqual(magazinescan.title_folder(os.path.join('/m', 'Wood', '2011'), '/m', '_Mags/$Title/$IssueDate'),
                         'Wood', 'The fixed folders are the library')
        self.assertEqual(magazinescan.title_folder('/m', '/m', '$Title'), '')
        self.assertEqual(magazinescan.title_folder(os.path.join('/m', '2011'), '/m', '$IssueDate/$Title'), '')
        root = os.path.join(TESTDIR, 'magscan')
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(os.path.join(root, 'Wood Magazine'))
        with open(os.path.join(root, 'Wood Magazine', 'Wood 20110206.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 not really')
        saved = {key: CONFIG[key] for key in ('MAG_DIR', 'MAG_DEST_FOLDER', 'MAG_DEST_FILE', 'IMP_MAGCOVER',
                                              'IMP_MAGOPF', 'MAG_RENAME', 'FULL_SCAN')}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
        for key, value in (('MAG_DIR', root), ('MAG_DEST_FOLDER', '$Title/$IssueDate'),
                           ('MAG_DEST_FILE', '$IssueDate - $Title'), ('IMP_MAGCOVER', False), ('IMP_MAGOPF', False),
                           ('MAG_RENAME', False), ('FULL_SCAN', False)):
            CONFIG.set_from_ui(key, value)
        if DIRS.config is not CONFIG:  # where the library folders are looked up
            saved_dir = DIRS.config['MAG_DIR']
            self.addCleanup(DIRS.config.set_from_ui, 'MAG_DIR', saved_dir)
            DIRS.config.set_from_ui('MAG_DIR', root)
        magazinescan.magazine_scan()
        self.assertEqual(self.sql("SELECT Title, IssueDate FROM issues WHERE IssueFile LIKE '%Wood%'"),
                         [{'Title': 'Wood Magazine', 'IssueDate': '20110206'}],
                         'The title folder, not the library folder above it')

        # a file with no date in its name isn't dated 0-00-01, one that was is dated again, and the
        # magazine's latest issue and cover are its newest issue's whatever order they're found in
        newest = os.path.join(root, 'Wood Magazine', 'Wood 20110301.pdf')
        for name in (newest, os.path.join(root, 'Wood Magazine', 'Wood notes.pdf')):
            with open(name, 'wb') as f:
                f.write(b'%PDF-1.4 not really')
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile,Cover) VALUES "
                 "('Wood Magazine','old','0-00-01',?,'cache/magazine/x.jpg')", (newest,))
        self.sql("UPDATE magazines SET IssueDate='0-00-01' WHERE Title='Wood Magazine'")
        magazinescan.magazine_scan()
        self.assertEqual([row['IssueDate'] for row in self.sql(
            "SELECT IssueDate FROM issues WHERE IssueFile LIKE '%Wood%' ORDER BY IssueDate")], ['20110206', '20110301'])
        found = self.sql("SELECT IssueDate, LatestCover FROM magazines WHERE Title='Wood Magazine'")[0]
        self.assertEqual(found['IssueDate'], '20110301')
        self.assertEqual(found['LatestCover'], self.sql("SELECT Cover FROM issues WHERE IssueDate='20110301'")[0]['Cover'])

        # issues that came in without a cover get one at the next scan, from page 1 when the
        # magazine's cover page was never set
        self.assertEqual({row['Cover'] for row in self.sql("SELECT Cover FROM issues WHERE Title='Wood Magazine'")},
                         {'data/images/nocover.jpg'})
        CONFIG.set_from_ui('IMP_MAGCOVER', True)
        self.sql("UPDATE magazines SET CoverPage=NULL WHERE Title='Wood Magazine'")
        picture = os.path.join(root, 'cover.jpg')
        with open(picture, 'wb') as f:
            f.write(b'\xff\xd8\xff')
        os.makedirs(os.path.join(DIRS.CACHEDIR, 'magazine'), exist_ok=True)
        with mock.patch.object(magazinescan, 'create_mag_cover', return_value=picture) as made:
            magazinescan.magazine_scan()
        self.assertEqual({call.kwargs['pagenum'] for call in made.call_args_list}, {1})
        covers = [row['Cover'] for row in self.sql("SELECT Cover FROM issues WHERE Title='Wood Magazine' "
                                                   "ORDER BY IssueDate")]
        self.assertTrue(all(cover.startswith('cache/magazine/') for cover in covers), covers)

        # the magazine's cover is the newest an issue has, when its latest issue has none
        from lazylibrarian.services import library
        self.sql("UPDATE issues SET Cover='' WHERE IssueDate='20110301'")
        self.sql("UPDATE magazines SET LatestCover='' WHERE Title='Wood Magazine'")
        self.assertEqual(library.get_magazine('Wood Magazine')['cover'], covers[0])
        self.assertEqual([m['cover'] for m in library.list_magazines() if m['title'] == 'Wood Magazine'], [covers[0]])
        self.assertEqual(magazines.coverless_issues('Wood Magazine'),
                         [row['IssueID'] for row in self.sql("SELECT IssueID FROM issues WHERE IssueDate='20110301'")])

    def test_a_date_found_or_not(self):
        from lazylibrarian import magazinescan
        self.assertEqual(magazinescan.issue_date(magazinescan.get_dateparts('Wood May 2024')), '2024-05-01')
        self.assertEqual(magazinescan.issue_date(magazinescan.get_dateparts('Wood notes')), '',
                         'Not 0-00-01')
