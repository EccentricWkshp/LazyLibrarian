#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test annas.py's hosts: the domains Wikipedia gives, and none of them answering

from unittest import mock

from lazylibrarian import annas
from lazylibrarian.config2 import CONFIG
from unittests.unittesthelpers import LLTestCase


class AnnasHostsTest(LLTestCase):

    def setUp(self):
        super().setUp()
        saved = CONFIG['ANNA_HOST']
        self.addCleanup(CONFIG.__setitem__, 'ANNA_HOST', saved)
        for name in ('_domains_fetched', '_unanswered_said'):
            patcher = mock.patch.object(annas, name, 0.0)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_domains_are_asked_for_now_and_then(self):
        CONFIG['ANNA_HOST'] = 'https://annas-archive.org'
        with mock.patch.object(annas, 'fetch_annas_archive_domains',
                               return_value=['annas-archive.gl', 'annas-archive.gl']) as fetch:
            self.assertEqual(annas.annas_hosts_update(), ['https://annas-archive.org', 'annas-archive.gl'])
            self.assertEqual(annas.annas_hosts_update(), ['https://annas-archive.org', 'annas-archive.gl'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(CONFIG['ANNA_HOST'], 'https://annas-archive.org,annas-archive.gl')

    def test_no_host_answering_is_said_once(self):
        CONFIG['ANNA_HOST'] = 'a.example,b.example'
        with mock.patch.object(annas, 'fetch_annas_archive_domains', return_value=[]) as fetch, \
                mock.patch.object(annas, 'annas_login'), \
                mock.patch.object(annas, 'html_parser', side_effect=ValueError('http status 403')) as search, \
                self.assertLogs('lazylibrarian.annas', 'WARNING') as logs:
            self.assertIsNone(annas.annas_search('dune'))
            self.assertIsNone(annas.annas_search('dune'))
        self.assertEqual((search.call_count, fetch.call_count, len(logs.output)), (4, 1, 1))
        self.assertIn('a.example (ValueError: http status 403)', logs.output[0])
