#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test magreleases.py, what a magazine search result's name says, and the magazine search using it.
#   The names are real ones, from indexers' results for these magazines

import logging
from unittest import mock

import lazylibrarian
from lazylibrarian import magreleases, searchmag
from lazylibrarian.config2 import CONFIG
from lazylibrarian.magazinescan import get_dateparts, issue_date
from lazylibrarian.services import InvalidRequestError, magazines
from lazylibrarian.startup import StartupLazyLibrarian
from unittests.unittesthelpers import LLTestCaseWithDB


class MagReleasesTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, lazylibrarian, 'MONTHNAMES', lazylibrarian.MONTHNAMES)
        self.addCleanup(setattr, lazylibrarian, 'SEASONS', lazylibrarian.SEASONS)
        startup = StartupLazyLibrarian()
        startup.logger = logging.getLogger(__name__)
        lazylibrarian.MONTHNAMES, lazylibrarian.SEASONS = startup.build_monthtable(CONFIG)

    def read(self, name, title, form='', pairs=None):
        return magreleases.read(name, [title], '', form, pairs)

    def test_the_title_starts_the_name(self):
        for name in ('Lets Make-31 July 2023', 'German Magz - July 2017 make 2017 Heft 2',
                     'The Best of Fine Woodworking-Tables and Chairs Winter 2016', 'Australian Wood Review 096'):
            title = 'Fine Woodworking' if 'Woodworking' in name else 'Wood Magazine' if 'Wood' in name else 'Make'
            self.assertIsNone(self.read(name, title)['kind'], name)
        for name in ('14 - MAGAZINE Circuit Cellar-October 2016 pdf par2 - 2210 MB usenet-space-cowboys online',
                     '[MAGAZINE) Circuit Cellar-October 2016 pdf', 'Circuit_Cellar_TruePDF-October_2016'):
            self.assertEqual(self.read(name, 'Circuit Cellar')['issuedate'], '2016-10-01', name)
        self.assertEqual(self.read('WOOD Magazine - March 2016 True PDF English', 'Wood Magazine')['issuedate'],
                         '2016-03-01', '"Magazine" can be left out or not')
        self.assertEqual(self.read('Wood December-January 2026 RETAIL MAGAZINE', 'Wood Magazine')['issuedate'],
                         '2026-01-01')
        self.assertEqual(self.read('Nuts & Volts No 7-July 2014', 'Nuts and Volts')['issuedate'], '2014-07-01')
        self.assertIsNone(self.read('26 - MAGAZINE  Wood', 'Wood Magazine')['kind'], 'Nothing but the title')

    def test_sizes_and_counts_are_no_issue_numbers(self):
        name = '24 - MAGAZINE  Popular Woodworking - April 2015 pdf part1 rar - 1646 MB 24 - MAGAZINE  Popular ' \
               'Woodworking - April 2015 pdf part1 rar - 1646 MB - Usenet-Space-Cowboys online No 1 NZB source'
        found = self.read(name, 'Popular Woodworking', 'number')
        self.assertEqual((found['date'], found['number']), ('2015-04-01', 0))
        self.assertEqual(issue_date(get_dateparts('Popular Woodworking - April 2015 pdf - 1646 MB')), '2015-04-01',
                         'Not 20151646')
        found = self.read('Popular Mechanics - Vol  196 No  06 Jul 2018 1 of 9 Popular Mechanics', 'Popular Mechanics')
        self.assertEqual((found['date'], found['number']), ('2018-07-01', 6))

    def test_no_year_no_date(self):
        found = self.read('Nuts And Volts TruePDF-October', 'Nuts and Volts', 'date')
        self.assertEqual((found['kind'], found['issuedate']), (magreleases.UNDATED, ''))
        self.assertEqual(issue_date(get_dateparts('Popular Mechanics USA TruePDF-November')), '', 'Not 0-11-01')
        self.assertEqual(issue_date(get_dateparts('MAKE Magazine-Volume35 2013')), '20130035', 'Not 2013-00-01')

    def test_number_and_date(self):
        name = 'Fine Woodworking Issue 304-July August 2023'
        self.assertEqual(self.read(name, 'Fine Woodworking', 'date')['issuedate'], '2023-07-01')
        self.assertEqual(self.read(name, 'Fine Woodworking', 'number')['issuedate'], '20230304')
        found = self.read('Circuit Cellar_282_(01-2014)', 'Circuit Cellar')
        self.assertEqual((found['date'], found['number']), ('2014-01-01', 282))
        found = self.read('Popular Woodworking 212-August 2014 Magazine True', 'Popular Woodworking')
        self.assertEqual((found['date'], found['number']), ('2014-08-01', 212))
        found = self.read('ShopNotes Magazine-18 May 2023', 'ShopNotes')
        self.assertEqual((found['date'], found['number']), ('2023-05-18', 0), 'A day, not a number')
        self.assertEqual(self.read('ShopNotes Vol 20 Issue 120-2011', 'ShopNotes', 'number')['issuedate'], '20110120')
        self.assertEqual(self.read('Make No 98 2026 RETAIL MAGAZINE eBook-21A1', 'Make')['issuedate'], '20260098')

    def test_names_pair_numbers_and_dates(self):
        names = ['Circuit Cellar No 276-July 2013', 'Circuit Cellar No 275-June 2013', 'ShopNotes 135 - May June 2014',
                 'Circuit Cellar 284 (03-2014)']
        pairs = magreleases.pairs_of([self.read(name, name.split()[0] + ' ' + name.split()[1]) for name in names])
        self.assertEqual(pairs['month']['2013-07'], 276)
        self.assertEqual(pairs['number'][284], '2014-03-01')
        found = self.read('Circuit Cellar-July 2013', 'Circuit Cellar', 'number', pairs)
        self.assertEqual((found['kind'], found['issuedate']), (magreleases.ISSUE, '20130276'))
        found = self.read('Circuit Cellar-November 2023', 'Circuit Cellar', 'number', pairs)
        self.assertEqual(found['kind'], magreleases.UNDATED)
        self.assertIn('numbered', found['reason'])
        self.assertEqual(self.read('Circuit Cellar 284', 'Circuit Cellar', 'date', pairs)['issuedate'], '2014-03-01')
        conflict = magreleases.pairs_of([self.read('Wood No 5 July 2013', 'Wood'), self.read('Wood No 6 July 2013', 'Wood')])
        self.assertNotIn('2013-07', conflict['month'], 'A month given two numbers is no pair')

    def test_set_aside(self):
        for name, title, kind in (
                ('Popular Mechanics South Africa-October 2013', 'Popular Mechanics', magreleases.EDITION),
                ('[MAGAZINE] Popular Mechanics SA 2016 02', 'Popular Mechanics', magreleases.EDITION),
                ('Nuts and Volts Full Year TruePDF-2016', 'Nuts and Volts', magreleases.BUNDLE),
                ('Popular Woodworking Magazine (2000 - 2010) PDF English', 'Popular Woodworking', magreleases.BUNDLE),
                ('FINE WOODWORKING Magazine No 001-221 PDF English-READNFO', 'Fine Woodworking', magreleases.BUNDLE),
                ('MAKE Magazine 01-45 par2 - 314 GB usenet-space-cowboys online', 'Make', magreleases.BUNDLE),
                ('Fine Woodworking Tool Guide-Winter 2024', 'Fine Woodworking', magreleases.SPECIAL),
                ('Popular Mechanics Ultimate Survival Guide-May 2023', 'Popular Mechanics', magreleases.SPECIAL),
                ('Make Your Own PC Tricks And Tips No 23 2026 HYBRID MAGAZINE', 'Make', magreleases.SPECIAL)):
            found = self.read(name, title)
            self.assertEqual(found['kind'], kind, name)
            self.assertTrue(found['reason'].startswith('Set aside'), name)
        for name in ('Fine Woodworking No 223 Winter 2011 - 2012 Magazine English PDF',
                     'Popular Mechanics USA TruePDF-January February 2018', 'Popular Mechanics HQ PDF-November 2015'):
            self.assertEqual(self.read(name, name.split()[0] + ' ' + name.split()[1])['kind'], magreleases.ISSUE, name)
        found = self.read('Popular Mechanics South Africa-October 2013', 'Popular Mechanics South Africa')
        self.assertEqual(found['kind'], magreleases.ISSUE, 'The edition the magazine is')

    def test_two_months_together_and_the_year_apart(self):
        """ "08.09 2025" is the August-September issue, not the 8th of September; two numbers that
        aren't months in a row, or a whole date, are still a day and a month """
        for name, issuedate in (("Cook's Country 02.03 2025", '2025-02-01'),
                                ("Cook's Country 08.09 2025_example.net", '2025-08-01'),
                                ("Cook's Country 12-01 2025", '2025-12-01')):
            self.assertEqual(self.read(name, "Cook's Country")['issuedate'], issuedate, name)
        for name, month in (("Cook's Country 08.10 2025", '2025-10'), ("Cook's Country 08.09.2025", '2025-09')):
            self.assertEqual(self.read(name, "Cook's Country")['issuedate'][:7], month, name)

    def test_the_latest_issue(self):
        """ The newest key of the form most issues have: a number misread among dates isn't the newest """
        self.assertEqual(magreleases.latest_of(['2025-04-01', '2025-06-01', '20255']), '2025-06-01')
        self.assertEqual(magreleases.latest_of(['20240276', '20240277', '2026-03-01']), '20240277')
        self.assertEqual(magreleases.latest_of([magreleases.NO_ISSUE, '2025-01-01']), '2025-01-01')
        self.assertEqual(magreleases.latest_of([magreleases.NO_ISSUE]), magreleases.NO_ISSUE)
        self.assertEqual(magreleases.latest_of([]), '')

    def test_form_of(self):
        self.assertEqual(magreleases.form_of('', ['2026-03-01', '2026-05-01', '20240276']), 'date')
        self.assertEqual(magreleases.form_of('', ['20130221', '20130222', '0-00-01']), 'number')
        self.assertEqual(magreleases.form_of('', ['0-00-01']), '')
        self.assertEqual(magreleases.form_of('I', ['2026-03-01']), 'number')

    def test_wanting_a_past_issue_without_one(self):
        """ A past issue stored without an issue, as names were read before, is read again when it's
        wanted, and isn't wanted when it still has none: never downloaded as an issue of 1970-01-01 """
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject) "
                 "VALUES ('Make','Active','',NULL,'',''), ('Wood','Active','2024-01-01','','','')")
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES ('Make','1','1970-01-01',''), "
                 "('Wood','2','2024-01-01','')")
        for url, title, name in (('u1', 'Make', 'Make.No.98.2026.RETAIL.MAGAZINE.eBook-21A1'),
                                 ('u2', 'Make', 'Make TruePDF-October'), ('u3', 'Wood', 'Wood Tool Guide-January 2024')):
            self.sql("INSERT INTO pastissues (BookID,NZBurl,NZBtitle,NZBprov,AuxInfo,Status,NZBmode) "
                     "VALUES (?,?,?,'test','1970-01-01','Skipped','nzb')", (title, url, name))
        with mock.patch.object(magazines.threading, 'Thread') as thread:
            self.assertEqual(magazines.mark_past_issues('Wanted', ['u1']), 1)
            with self.assertRaises(InvalidRequestError) as raised:
                magazines.mark_past_issues('Wanted', ['u2', 'u3'])
        self.assertIn('No issue date or number', str(raised.exception))
        self.assertIn("issue 2024-01-01's, which it would replace", str(raised.exception))
        self.assertEqual(thread.call_count, 1, 'Nothing downloaded when nothing was wanted')
        self.assertEqual(self.sql("SELECT NZBurl, AuxInfo FROM wanted"), [{'NZBurl': 'u1', 'AuxInfo': '20260098'}])

    def test_downloading_a_past_issue_as_an_issue(self):
        """ A past issue its name gives no issue the magazine's issues match is downloaded as the issue
        given for it, as it's typed when it can't be put in their form """
        from lazylibrarian.services import library
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject) "
                 "VALUES ('Wood','Active','20130221','','','')")
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES ('Wood','1','20130221',''), "
                 "('Wood','2','20130222','')")
        for url, name in (('u1', 'Wood September 2026 RETAIL MAGAZINE eBook-21A1'), ('u2', 'Wood March 2026 RETAIL')):
            self.sql("INSERT INTO pastissues (BookID,NZBurl,NZBtitle,NZBprov,AuxInfo,Status,NZBmode,DLResult) VALUES "
                     "('Wood',?,?,'test','1970-01-01','Skipped','nzb','Dated 2026-09, but the magazine''s issues "
                     "are numbered')", (url, name))
        named = {row['url']: row['named'] for row in library.list_past_issues('Skipped', 'Wood')}
        self.assertEqual(named, {'u1': '2026-09', 'u2': '2026-03'}, 'What the names say, to be typed')
        with mock.patch.object(magazines.threading, 'Thread'):
            self.assertRaises(InvalidRequestError, magazines.mark_past_issues, 'Wanted', ['u1'])
            self.assertEqual(library.mark_past_issues(['u1'], 'Wanted', named['u1']), 1)
            self.assertEqual(library.mark_past_issues(['u2'], 'Wanted', 'No 230 2026'), 1)
            with self.assertRaisesRegex(InvalidRequestError, 'is no date'):
                library.mark_past_issues(['u2'], 'Wanted', 'whenever')
            self.assertRaises(InvalidRequestError, library.mark_past_issues, ['u1', 'u2'], 'Wanted', '2026-09')
        self.assertEqual({row['NZBurl']: row['AuxInfo'] for row in self.sql("SELECT NZBurl, AuxInfo FROM wanted")},
                         {'u1': '2026-09-01', 'u2': '20260230'})

    def test_a_month_without_a_year(self):
        """ A month alone is the one around when the release was posted, up to two months ahead """
        def date(name, posted):
            return magreleases.read(name, ['Popular Mechanics'], posted=posted)['issuedate']
        self.assertEqual(date('Popular Mechanics USA-October', '2026-09-21'), '2026-10-01')
        self.assertEqual(date('Popular Mechanics USA TruePDF-November', '2026-09-21'), '2026-11-01')
        self.assertEqual(date('Popular Mechanics USA TruePDF-December', '2026-09-21'), '2025-12-01')
        self.assertEqual(date('Popular Mechanics USA-February', '2025-12-20'), '2026-02-01')
        self.assertEqual(date('Popular Mechanics USA-October', ''), '', 'Not without when it was posted')
        self.assertEqual(date('Popular Mechanics USA-October', '1970-01-01'), '', "Nor a result's made-up date")
        self.assertEqual(date('Popular Mechanics USA-May 2023', '2026-09-21'), '2023-05-01', 'Its own year first')

    def test_a_past_issue_in_the_library_now(self):
        """ A past issue whose issue came in since it was stored says so """
        from lazylibrarian.services import library
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject) "
                 "VALUES ('Wood','Active','2026-09-01','','','')")
        for url, issue in (('w1', '2026-03-01'), ('w2', '2026-05-01'), ('w3', '1970-01-01')):
            self.sql("INSERT INTO pastissues (BookID,NZBurl,NZBtitle,NZBprov,NZBdate,AuxInfo,Status,NZBmode) "
                     "VALUES ('Wood',?,?,'test','2026-09-21',?,'Skipped','nzb')", (url, f'Wood {issue}', issue))
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate) VALUES ('Wood','i1','2026-05-01')")
        rows = {row['url']: row['in_library'] for row in library.list_past_issues('Skipped', 'Wood')}
        self.assertEqual(rows, {'w1': False, 'w2': True, 'w3': False})

    def test_another_edition_as_a_magazine(self):
        """ Another edition set aside is added as a magazine of its own, with its past issues """
        from lazylibrarian.services import library
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject,CoverPage) "
                 "VALUES ('Popular Mechanics','Active','2026-09-01','','','',2)")
        for url, name in (('u1', 'Popular.Mechanics.South.Africa.TruePDF-September'),
                          ('u2', 'Popular Mechanics South Africa TruePDF-October 2026'),
                          ('u3', 'Popular Mechanics USA-October'), ('u4', 'Popular Mechanics UK-October 2026')):
            self.sql("INSERT INTO pastissues (BookID,NZBurl,NZBtitle,NZBprov,NZBdate,AuxInfo,Status,NZBmode) "
                     "VALUES ('Popular Mechanics',?,?,'test','2026-09-21','1970-01-01','Skipped','nzb')", (url, name))
        rows = {row['url']: row for row in library.list_past_issues('Skipped', 'Popular Mechanics')}
        self.assertEqual(rows['u1']['edition'], 'South Africa', 'As the name has it')
        self.assertEqual((rows['u3']['edition'], rows['u3']['named']), ('', '2026-10'))
        self.assertRaises(InvalidRequestError, magazines.add_edition, 'u3')
        with mock.patch.object(magazines, 'start_search'):
            self.assertEqual(library.add_edition('u1'), {'title': 'Popular Mechanics South Africa', 'moved': 2})
        self.assertEqual(self.sql("SELECT CoverPage FROM magazines WHERE Title='Popular Mechanics South Africa'"),
                         [{'CoverPage': 2}], "The magazine's settings")
        moved = {row['NZBurl']: row['AuxInfo'] for row in self.sql(
            "SELECT NZBurl,AuxInfo FROM pastissues WHERE BookID='Popular Mechanics South Africa'")}
        self.assertEqual(moved, {'u1': '2026-09-01', 'u2': '2026-10-01'}, 'Read as its issues')
        self.assertEqual(sorted(row['NZBurl'] for row in self.sql(
            "SELECT NZBurl FROM pastissues WHERE BookID='Popular Mechanics'")), ['u3', 'u4'])

    def test_numberings(self):
        """ The same issue has the one key however its name says it, in the numbering chosen """
        for name in ('Make Volume 98', 'Make No 98 2026 RETAIL MAGAZINE', 'MAKE Magazine-Volume98 2026'):
            self.assertEqual(self.read(name, 'Make', 'running')['issuedate'], '0098', name)
        self.assertEqual(self.read('Make Magazine Vol 41 September 2014', 'Make', 'running')['issuedate'], '0041')
        self.assertEqual(self.read('Make No 98 2026', 'Make', 'yearly')['issuedate'], '20260098')
        found = self.read('Make Volume 98', 'Make', 'yearly')
        self.assertEqual((found['kind'], found['issuedate']), (magreleases.UNDATED, ''))
        self.assertIn('start again each year', found['reason'])
        self.assertEqual(self.read('Popular Woodworking Vol 45 No 05 2025', 'Popular Woodworking', 'volume')['issuedate'],
                         '00450005')
        self.assertEqual(self.read('Popular Woodworking October 2026', 'Popular Woodworking', 'volume')['kind'],
                         magreleases.UNDATED)
        self.assertEqual(self.read('Fine Woodworking Tool Guide TruePDF-2017', 'Fine Woodworking', 'year')['issuedate'],
                         '2017')
        pairs = magreleases.pairs_of([self.read('Wood Magazine 248 September 2017', 'Wood Magazine')])
        self.assertEqual(self.read('WOOD Magazine TruePDF-September 2017', 'Wood Magazine', 'running', pairs)['issuedate'],
                         '0248', 'A month a name numbered')

    def test_convert(self):
        for key, scheme, converted in (('20260098', 'running', '0098'), ('0098', 'running', '0098'),
                                       ('0098', 'yearly', '0098'), ('20250005', 'yearly', '20250005'),
                                       ('00450005', 'volume', '00450005'), ('2026-03-01', 'running', '2026-03-01'),
                                       ('20260098', '', '20260098'), ('20260098', 'number', '20260098'),
                                       ('1970-01-01', 'running', '1970-01-01'), ('2014-09-01', 'date', '2014-09-01')):
            self.assertEqual(magreleases.convert(key, scheme), converted, (key, scheme))
        pairs = {'month': {'2014-09': 41}, 'number': {41: '2014-09-01'}}
        self.assertEqual(magreleases.convert('2014-09-01', 'running', pairs), '0041')
        self.assertEqual(magreleases.convert('0041', 'date', pairs), '2014-09-01')

    def test_renumbering(self):
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject,Numbering) "
                 "VALUES ('Make','Active','20260098','','','','running')")
        for issue_id, date in (('1', '20260098'), ('2', '20250097'), ('3', '0096'), ('4', '20250096'),
                               ('5', '1970-01-01')):
            self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES ('Make',?,?,'')", (issue_id, date))
        self.sql("INSERT INTO wanted (BookID,NZBurl,NZBtitle,AuxInfo,Status) VALUES "
                 "('Make','w1','Make No 99 2026','20260099','Snatched')")
        with mock.patch.object(magazines, 'rename_issue', return_value=('', '')) as renamed:
            done = magazines.renumber_issues('make')
        self.assertEqual(done['renumbered'], 2)
        self.assertEqual(done['left'], ["20250096 (its number, 0096, is another issue's)"])
        self.assertEqual(sorted(call.args[0] for call in renamed.call_args_list), ['1', '2'], 'Their files renamed')
        issues = {row['IssueID']: row['IssueDate'] for row in self.sql("SELECT IssueID,IssueDate FROM issues")}
        self.assertEqual(issues, {'1': '0098', '2': '0097', '3': '0096', '4': '20250096', '5': '1970-01-01'})
        self.assertEqual(self.sql("SELECT AuxInfo FROM wanted"), [{'AuxInfo': '0099'}])
        self.assertEqual(self.sql("SELECT IssueDate FROM magazines"), [{'IssueDate': '20250096'}],
                         'The latest as the issues sort')

    def test_choosing_a_numbering(self):
        from lazylibrarian.services import editing
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject,CoverPage) "
                 "VALUES ('Make','Active','','','','',1)")
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES ('Make','1','20260098','')")
        found = editing.magazine_for_edit('Make')
        self.assertEqual((found['numbering'], found['numbering_found']), ('', 'number'))
        with mock.patch('lazylibrarian.services.commands.start') as start:
            saved = editing.save_magazine('Make', {'numbering': 'running'})
            editing.save_magazine('Make', {'numbering': 'running'})
        start.assert_called_once_with('RenumberIssues', {'title': 'Make'})
        self.assertIn('renumbered as running numbers', saved['message'])
        self.assertRaises(InvalidRequestError, editing.save_magazine, 'Make', {'numbering': 'weekly'})
        # an issue edited, and one imported by hand, are kept in it
        with mock.patch.object(magazines, 'rename_issue', return_value=('Make - 0099.pdf', '')):
            magazines.update_issue('1', 'Make', 'Volume 99', {}, {})
        self.assertEqual(self.sql("SELECT IssueDate FROM issues"), [{'IssueDate': '0099'}])
        from lazylibrarian import database
        from lazylibrarian.services import manualimport
        with database.DBConnection() as db:
            self.assertEqual(manualimport._checked_issue(db, 'magazine', 'Make', 'No 100 2026'), '0100')

    def test_typing_an_issue(self):
        """ An issue's date or number, typed in its Edit, read as a name would be in the form the
        magazine's issues are known by """
        from lazylibrarian import database
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject,CoverPage) VALUES "
                 "('Make','Active','0025',NULL,'','',1), ('Wired','Active','2026-01-01','','','',1), "
                 "('Annual','Active','2025','','','',1), ('New','Active','','','','',1)")
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES ('Make','1','0025',''), "
                 "('Make','2','0022',''), ('Make','3','1970-01-01',''), ('Wired','4','2026-01-01','')")
        self.sql("INSERT INTO pastissues (BookID,NZBurl,NZBtitle,AuxInfo,Status) VALUES "
                 "('Wired','u1','Wired No 230 March 2026','2026-03-01','Have')")
        with database.DBConnection() as db:
            def entered(title, entry):
                return magreleases.entered(db, title, entry)[0]
            # Make's issues are running numbers, without a numbering chosen
            for entry in ('34', 'Volume 34', 'Vol 34', 'No 34', '#34', 'Issue 34', '0034', 'Make Volume 34',
                          'MAKE Magazine - Volume 34'):
                self.assertEqual(entered('Make', entry), '0034', entry)
            self.assertEqual(entered('Make', 'No 98 2026'), '20260098', 'A number with its year, as they have been')
            # Wired's are dated, a number given a date by a name
            for entry in ('2026-03', 'March 2026', 'Mar 2026', '2026-03-01', '230'):
                self.assertEqual(entered('Wired', entry), '2026-03-01', entry)
            self.assertEqual(magreleases.entered(db, 'Wired', '34')[1],
                             "\"34\" can't be an issue of Wired: numbered 34, but the magazine's issues are dated and "
                             "no name gives that number's date. How its issues are known is chosen in the "
                             "magazine's Edit")
            self.assertIn('is no date', magreleases.entered(db, 'Make', 'whenever')[1])
            self.assertEqual(entered('Annual', '2026'), '2026')
            # a magazine with no issues yet takes what's typed
            self.assertEqual((entered('New', '34'), entered('New', 'March 2026')), ('0034', '2026-03-01'))
            self.sql("UPDATE magazines SET Numbering='yearly' WHERE Title='Make'")
            self.assertEqual(entered('Make', 'No 5 2025'), '20250005')
            self.assertIn("there's no year", magreleases.entered(db, 'Make', '34')[1])
        # the newest issue isn't the one filed under 1970-01-01
        self.assertEqual(magazines.set_latest('Make'), '0025')

    def test_no_date_type(self):
        self.assertEqual(issue_date(get_dateparts('Make No 98 2026', datetype=None)), '20260098',
                         "A magazine's DateType can be NULL")

    def test_a_search(self):
        """ A magazine search takes the newer issues, and keeps the rest with why they aren't wanted;
        what it kept before is read again """
        self.sql("INSERT INTO magazines (Title,Status,IssueDate,DateType,Regex,Reject) "
                 "VALUES ('Popular Mechanics','Active','2026-05-01','','','')")
        self.sql("INSERT INTO issues (Title,IssueID,IssueDate,IssueFile) VALUES "
                 "('Popular Mechanics','1','2026-05-01',''), ('Popular Mechanics','2','2026-03-01','')")
        self.sql("INSERT INTO pastissues (BookID,NZBurl,NZBtitle,NZBprov,AuxInfo,Status) VALUES "
                 "('Popular Mechanics','u0','Popular Mechanics USA TruePDF-November','old','0-11-01','Skipped'), "
                 "('Popular Mechanics','u00','Lets Popular Mechanics-May 2020','old','2020-05-01','Skipped')")
        names = ['Popular Mechanics July-August 2026 RETAIL MAGAZINE eBook-21A1',
                 'Popular Mechanics South Africa TruePDF-September 2026',
                 'Popular Mechanics March-April 2026 HYBRID MAGAZINE', 'Popular Mechanics Full Year 2025',
                 'Lets Popular Mechanics-September 2026']
        results = [{'bookid': 'Popular Mechanics', 'nzbprov': 'test', 'nzbtitle': name, 'nzburl': f'u{n + 1}',
                    'nzbdate': 'Fri, 01 Jan 2026 00:00:00 +0100', 'nzbsize': '50000000', 'nzbmode': 'nzb'}
                   for n, name in enumerate(names)]
        with mock.patch.object(CONFIG, 'use_nzb', return_value=1), \
                mock.patch.object(CONFIG, 'use_direct', return_value=0), \
                mock.patch.object(CONFIG, 'use_irc', return_value=0), \
                mock.patch.object(CONFIG, 'use_tor', return_value=0), \
                mock.patch.object(CONFIG, 'use_rss', return_value=0), \
                mock.patch.object(searchmag, 'iterate_over_znab_sites', return_value=(results, 1)), \
                mock.patch.object(searchmag, 'download_maglist'), \
                mock.patch.object(searchmag.threading, 'Thread') as thread, \
                mock.patch.object(searchmag.time, 'sleep'):
            searchmag.search_magazines([{'bookid': 'Popular Mechanics'}])
        wanted = self.sql("SELECT NZBtitle, AuxInfo FROM wanted")
        self.assertEqual(wanted, [{'NZBtitle': names[0], 'AuxInfo': '2026-07-01'}])
        self.assertEqual([item['nzbtitle'] for item in thread.call_args.kwargs['args'][0]], [names[0]])
        past = {row['NZBurl']: row for row in self.sql("SELECT NZBurl, AuxInfo, Status, DLResult FROM pastissues")}
        self.assertEqual(sorted(past), ['u0', 'u2', 'u4'],
                         "Lets Popular Mechanics isn't kept, nor read again, nor an issue there is")
        self.assertEqual((past['u2']['AuxInfo'], past['u2']['DLResult']),
                         ('1970-01-01', 'Set aside: another edition ("south africa")'))
        self.assertIn('several issues', past['u4']['DLResult'])
        self.assertEqual((past['u0']['AuxInfo'], past['u0']['DLResult']),
                         ('1970-01-01', 'No issue date or number in the name'), 'Read again: not 0-11-01')
