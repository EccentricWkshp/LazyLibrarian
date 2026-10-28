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
