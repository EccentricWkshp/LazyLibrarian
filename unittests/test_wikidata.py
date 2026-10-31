#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test wikidata.py with Wikidata's answers made up, and the missing and expected issues
#   services/magazines.py works out from them

import datetime
import unittest
from unittest import mock

from lazylibrarian import wikidata
from lazylibrarian.services.magazines import issue_schedule


def item(value):
    return {'mainsnak': {'datavalue': {'value': value}}, 'rank': 'normal'}


WIRED = {'labels': {'en': {'value': 'Wired'}}, 'descriptions': {'en': {'value': 'American magazine'}},
         'sitelinks': {'enwiki': {'title': 'Wired (magazine)'}},
         'claims': {'P123': [item({'id': 'Q1'})], 'P236': [item('1059-1028'), item('1059-1028')],
                    'P495': [item({'id': 'Q30'})], 'P31': [item({'id': 'Q2'})],
                    'P2896': [item({'amount': '+1', 'unit': 'http://www.wikidata.org/entity/Q5151'})],
                    'P856': [item('https://www.wired.com/')], 'P154': [item('Wired logo.svg')],
                    'P571': [item({'time': '+1993-01-02T00:00:00Z'})], 'P921': [item({'id': 'Q3'})],
                    'P136': [{'mainsnak': {'datavalue': {'value': {'id': 'Q4'}}}, 'rank': 'deprecated'}]}}
LABELS = {'Q1': 'Condé Nast', 'Q30': 'United States', 'Q2': 'monthly magazine', 'Q3': 'technology', 'Q4': 'old'}


def answers(params, url=wikidata.API):
    if 'wikipedia.org' in url:
        return {'extract': 'Wired is a magazine.'} if url.endswith('/Wired_%28magazine%29') else {}
    if params.get('query'):
        return {'results': {'bindings': [
            {'item': {'value': 'http://www.wikidata.org/entity/Q8026784'}, 'itemLabel': {'value': 'Wired UK'},
             'start': {'value': '2009-01-01T00:00:00Z'}},
            {'item': {'value': 'http://www.wikidata.org/entity/Q520154'}, 'itemLabel': {'value': 'Wired'},
             'itemDescription': {'value': 'American magazine'}}]}}
    if params['ids'] == 'Q520154':
        return {'entities': {'Q520154': WIRED}}
    if params['ids'] == 'Q404':
        return {'entities': {'Q404': {'missing': ''}}}
    return {'entities': {key: {'labels': {'en': {'value': LABELS[key]}}} for key in params['ids'].split('|')}}


class WikidataTest(unittest.TestCase):

    def test_search(self):
        with mock.patch.object(wikidata, '_get', side_effect=answers) as get:
            found = wikidata.search('wired')
            self.assertEqual([(m['id'], m['label'], m['started']) for m in found],
                             [('Q520154', 'Wired', ''), ('Q8026784', 'Wired UK', '2009')], 'Called exactly that first')
            wikidata.search('wired "magazine"\\')
        self.assertIn('mwapi:search "wired  magazine  "', get.call_args.args[0]['query'], "Quotes can't end it")
        self.assertEqual(wikidata.search('  '), [])

    def test_details(self):
        with mock.patch.object(wikidata, '_get', side_effect=answers):
            found = wikidata.details('Q520154')
            self.assertEqual(wikidata.details('Q404'), {})
        self.assertEqual(found, {'id': 'Q520154', 'label': 'Wired', 'description': 'Wired is a magazine.',
                                 'publisher': 'Condé Nast', 'issn': '1059-1028', 'country': 'United States',
                                 'frequency': 30, 'website': 'https://www.wired.com/',
                                 'logo': 'https://commons.wikimedia.org/wiki/Special:FilePath/Wired_logo.svg?width=400',
                                 'started': '1993', 'subjects': ['technology']})

    def test_frequency_from_the_kind_of_periodical(self):
        self.assertEqual(wikidata._frequency({'claims': {}}, ['weekly newspaper']), 7)
        self.assertEqual(wikidata._frequency({'claims': {}}, ['bimonthly magazine']), 61)
        self.assertEqual(wikidata._frequency({'claims': {}}, ['magazine']), 0)


class ScheduleTest(unittest.TestCase):
    today = datetime.date(2026, 6, 20)

    def test_monthly(self):
        found = issue_schedule(['2026-01-01', '2026-02-01', '2026-05-01'], 30, self.today)
        self.assertEqual(found['missing'], ['2026-03-01', '2026-04-01'])
        self.assertEqual((found['next'], found['overdue'], found['inferred']), ('2026-06-01', True, False))

    def test_inferred_weekly(self):
        found = issue_schedule(['2026-06-01', '2026-06-08', '2026-06-15', '2026-05-25', '2026-05-11'], 0, self.today)
        self.assertEqual((found['frequency'], found['inferred']), (7, True))
        self.assertEqual(found['missing'], ['2026-05-18'])
        self.assertEqual((found['next'], found['overdue']), ('2026-06-22', False))

    def test_numbers(self):
        found = issue_schedule(['0101', '0102', '0105'], 0, self.today)
        self.assertEqual((found['missing'], found['next']), (['103', '104'], '106'))

    def test_too_little_to_tell(self):
        self.assertEqual(issue_schedule(['2026-01-01', '2026-02-01'], 0, self.today),
                         {'frequency': 0, 'inferred': False, 'missing': [], 'next': '', 'overdue': False})
        self.assertEqual(issue_schedule([], 30, self.today)['next'], '')

    def test_misread_dates_and_the_most_recent_missing(self):
        # issues dated before the magazine started were misread, and of more missing than are
        # shown, the most recent are
        dates = ['0-00-01', '1910', '1910-01-01', '1995-10-01', '1995-11-01', '1996-01-01', '2026-03-01',
                 '2026-05-01']
        found = issue_schedule(dates, 30, self.today, started='1980')
        self.assertEqual(len(found['missing']), 60)
        self.assertEqual((found['missing'][0], found['missing'][-2:]), ('2021-04-01', ['2026-02-01', '2026-04-01']))
        self.assertEqual(issue_schedule(dates[2:6], 30, self.today, started='1980')['missing'], ['1995-12-01'])
        self.assertEqual(len(issue_schedule(dates[2:6], 30, self.today)['missing']), 60, '1910 to 1995')


if __name__ == '__main__':
    unittest.main()
