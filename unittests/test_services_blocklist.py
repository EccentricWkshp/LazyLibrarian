#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the blocklist (services/blocklist.py and the database triggers that fill it) and the
#   history as Sonarr's events (services/history.list_events)

from lazylibrarian import dbupgrade
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.resultlist import evaluate_results
from lazylibrarian.services import InvalidRequestError, blocklist, commands, history
from unittests.test_resultlist import _make_book, _make_tor_result
from unittests.unittesthelpers import LLTestCaseWithStartup


class BlocklistTestCase(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        saved = CONFIG.get_bool('BLACKLIST_FAILED'), CONFIG.get_bool('BLACKLIST_PROCESSED')
        self.addCleanup(lambda: (CONFIG.set_bool('BLACKLIST_FAILED', saved[0]),
                                 CONFIG.set_bool('BLACKLIST_PROCESSED', saved[1])))
        CONFIG.set_bool('BLACKLIST_FAILED', True)
        CONFIG.set_bool('BLACKLIST_PROCESSED', False)
        with DBConnection() as db:
            db.action("DELETE FROM wanted")
            db.action("DELETE FROM blocklist")
            db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES ('ba1', 'Lee Child', 'Active')")
            db.action("INSERT OR REPLACE INTO books (BookID, AuthorID, BookName, Status, AudioStatus) VALUES "
                      "('bb1', 'ba1', 'Without Fail', 'Snatched', 'Skipped')")

    def snatched(self, url='http://x/1', title='Lee Child - Without Fail epub', status='Snatched', result=''):
        with DBConnection() as db:
            db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,"
                      "Source,DownloadID,DLResult) VALUES ('bb1',?,?,'2026-10-26 10:00:00','TestProvider',?,'1.5',"
                      "'eBook','torrent','QBITTORRENT','abc',?)", (url, title, status, result))
            return db.match('SELECT rowid FROM wanted WHERE NZBurl=?', (url,))['rowid']

    def blocked(self) -> list[dict]:
        with DBConnection() as db:
            return [dict(row) for row in db.select('SELECT * FROM blocklist')]


class TriggerTest(BlocklistTestCase):

    def test_a_download_that_fails_is_blocklisted(self):
        self.snatched()
        self.assertEqual(self.blocked(), [])
        with DBConnection() as db:
            db.action("UPDATE wanted SET Status='Failed',DLResult='NZBget deleted it' WHERE NZBurl='http://x/1'")
        blocked = self.blocked()
        self.assertEqual([(row['NZBtitle'], row['NZBprov'], row['Message']) for row in blocked],
                         [('Lee Child - Without Fail epub', 'TestProvider', 'NZBget deleted it')])
        self.assertTrue(blocked[0]['Date'], 'When it was blocklisted')

    def test_however_it_was_marked(self):
        self.snatched(status='Failed', result='Could not send it')
        rowid = self.snatched(url='http://x/2', status='Processed')
        history.mark_failed(rowid)
        self.assertEqual(sorted((row['NZBurl'], row['Message']) for row in self.blocked()),
                         [('http://x/1', 'Could not send it'), ('http://x/2', 'Manually marked as failed')])

    def test_once(self):
        self.snatched()
        with DBConnection() as db:
            for status in ('Failed', 'Snatched', 'Failed'):
                db.action("UPDATE wanted SET Status=? WHERE NZBurl='http://x/1'", (status,))
        self.assertEqual(len(self.blocked()), 1)

    def test_not_what_was_imported(self):
        self.snatched()
        with DBConnection() as db:
            db.action("UPDATE wanted SET Status='Processed' WHERE NZBurl='http://x/1'")
        self.assertEqual(self.blocked(), [])

    def test_the_upgrade_blocklists_what_failed_before(self):
        with DBConnection() as db:
            db.action("DROP TABLE blocklist")
            for trigger in ('blocklist_failed_insert', 'blocklist_failed_update'):
                db.action(f"DROP TRIGGER {trigger}")
            db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,NZBdate,NZBprov,Status,AuxInfo) VALUES "
                      "('bb1','http://x/old','Old Failure','2026-01-02 03:04:05','TestProvider','Failed','eBook')")
            with open(__file__ + '.upgrade.log', 'w') as log:
                self.addCleanup(lambda: __import__('os').remove(__file__ + '.upgrade.log'))
                dbupgrade.update_schema(db, log)
        self.assertEqual([(row['NZBurl'], row['Date']) for row in self.blocked()],
                         [('http://x/old', '2026-01-02 03:04:05')], 'Dated when it was grabbed')
        self.snatched()
        with DBConnection() as db:
            db.action("UPDATE wanted SET Status='Failed' WHERE NZBurl='http://x/1'")
        self.assertEqual(len(self.blocked()), 2, 'And the triggers are back')


class BlocklistTest(BlocklistTestCase):

    def evaluate(self, title='Lee Child - Without Fail epub', url='http://x/1'):
        book = _make_book('Lee Child', 'Without Fail', bookid='bb1')
        return evaluate_results([_make_tor_result(title, url=url)], book, 'book', 'tor')[0]['rejections']

    def test_the_search_rejects_a_blocklisted_release(self):
        self.snatched(status='Failed')
        self.assertEqual(self.evaluate(), ['Blocklisted, it failed before at TestProvider'])
        self.assertEqual(self.evaluate(url='http://x/moved'), ['Blocklisted, it failed before at TestProvider'],
                         'By its title at the same provider when its link changed')

    def test_taken_off_the_blocklist_it_can_be_taken_again(self):
        rowid = self.snatched(status='Failed')
        entry = blocklist.list_blocklist().items[0]
        self.assertEqual((entry['title'], entry['author'], entry['media_type'], entry['source_title'], entry['size']),
                         ('Without Fail', 'Lee Child', 'ebook', 'Lee Child - Without Fail epub', 1572864))
        self.assertEqual(blocklist.remove([entry['id']]), 1)
        self.assertEqual(self.evaluate(), [])
        with DBConnection() as db:
            self.assertEqual(db.match('SELECT Status FROM wanted WHERE rowid=?', (rowid,))['Status'], 'Failed',
                             'Its history stays')
        CONFIG.set_bool('BLACKLIST_PROCESSED', True)
        self.assertEqual(self.evaluate(), [], 'A failed download is not one that was downloaded')

    def test_clearing_history_leaves_the_blocklist(self):
        self.snatched(status='Failed')
        history.clear_history('Failed')
        self.assertEqual(len(self.blocked()), 1, 'As in Sonarr')

    def test_off(self):
        self.snatched(status='Failed')
        CONFIG.set_bool('BLACKLIST_FAILED', False)
        self.assertEqual(self.evaluate(), [])

    def test_clear(self):
        self.snatched(status='Failed')
        self.snatched(url='http://x/2', status='Failed')
        command = commands.start('ClearBlocklist', {})
        for _ in range(100):
            command = commands.get(command['id'])
            if command['status'] in ('completed', 'failed'):
                break
            __import__('time').sleep(0.05)
        self.assertEqual((command['status'], command['message']),
                         ('completed', 'Cleared 2 releases from the blocklist'))
        self.assertEqual(self.blocked(), [])

    def test_bad_requests(self):
        with self.assertRaises(InvalidRequestError):
            blocklist.remove([])
        with self.assertRaises(InvalidRequestError):
            blocklist.list_blocklist(sort='nosuch')


class HistoryEventsTest(BlocklistTestCase):

    def test_events(self):
        grabbed = self.snatched()
        failed = self.snatched(url='http://x/2', status='Failed', result='NZBGet deleted it')
        imported = self.snatched(url='http://x/3', status='Processed', result='/books/Without Fail.epub')
        events = {item['id']: item for item in history.list_events().items}
        self.assertEqual((events[grabbed]['event_type'], events[failed]['event_type'], events[imported]['event_type']),
                         ('grabbed', 'downloadFailed', 'downloadFolderImported'), 'Sonarr\'s event types')
        item = events[failed]
        self.assertEqual((item['title'], item['author'], item['download_client'], item['protocol'], item['message']),
                         ('Without Fail', 'Lee Child', 'qBittorrent', 'torrent', 'NZBGet deleted it'))
        self.assertEqual([item['id'] for item in history.list_events('downloadFailed').items], [failed])
        self.assertEqual(history.list_events(search='nobody').items, [])
        with self.assertRaises(InvalidRequestError):
            history.list_events('nosuch')

    def test_a_book_no_longer_in_the_library(self):
        with DBConnection() as db:
            db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,Status,AuxInfo) VALUES "
                      "('gone','http://x/9','Gone Book','Processed','AudioBook')")
        item = history.list_events().items[0]
        self.assertEqual((item['title'], item['author'], item['media_type']), ('gone', '', 'audiobook'))
