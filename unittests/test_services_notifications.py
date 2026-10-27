#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the webhooks (services/notifications.py and the database triggers that queue a download's
#   events), sending them to a small web server here

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.services import InvalidRequestError, health, notifications
from unittests.unittesthelpers import LLTestCaseWithStartup


class Receiver(BaseHTTPRequestHandler):
    received: list = []
    status = 200

    def do_POST(self):  # noqa: N802, as http.server names it
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        self.received.append({'method': self.command, 'path': self.path, 'headers': dict(self.headers),
                              'body': json.loads(body or b'{}')})
        self.send_response(self.status)
        self.end_headers()

    def do_PUT(self):  # noqa: N802
        self.do_POST()

    def log_message(self, *args):
        pass


class NotificationsTestCase(LLTestCaseWithStartup):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_address[1]}/hook'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        Receiver.received = []
        Receiver.status = 200
        notifications._failures.clear()
        with DBConnection() as db:
            for table in ('wanted', 'notifications', 'notificationevents', 'appstate'):
                db.action(f"DELETE FROM {table}")
            db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES ('na1', 'Lee Child', 'Active')")
            db.action("INSERT OR REPLACE INTO books (BookID, AuthorID, BookName, BookIsbn, Status, AudioStatus, "
                      "BookFile) VALUES ('nb1', 'na1', 'Without Fail', '9780515136562', 'Wanted', 'Skipped', '')")

    def hook(self, name='Hook', **triggers) -> dict:
        definition = {'name': name, 'settings': {'url': self.url, 'method': 'POST', 'username': '', 'password': '',
                                                 'headers': []}}
        definition.update(dict.fromkeys(notifications.TRIGGERS.values(), False))
        definition.update(triggers)
        return notifications.save(definition)

    def snatched(self, url='http://x/1', source='SABNZBD', title='Lee Child - Without Fail epub'):
        with DBConnection() as db:
            db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,"
                      "Source,DownloadID,DLResult) VALUES ('nb1',?,?,'2026-10-26 10:00:00','TestProvider',"
                      "'Snatched','1.5','eBook','nzb',?,'SABnzbd_nzo_1','')", (url, title, source))

    def set_wanted(self, assignments: str, url='http://x/1'):
        with DBConnection() as db:
            db.action(f"UPDATE wanted SET {assignments} WHERE NZBurl=?", (url,))

    def events(self) -> list[tuple]:
        with DBConnection() as db:
            return [(row['Event'], row['Upgrade'], row['Message'])
                    for row in db.select('SELECT * FROM notificationevents ORDER BY EventID')]

    def sent(self) -> list[dict]:
        """ What is sent now """
        Receiver.received = []
        notifications.deliver_pending()
        return [request['body'] for request in Receiver.received]


class TriggerTest(NotificationsTestCase):

    def test_nothing_is_queued_without_a_connection_wanting_it(self):
        self.snatched()
        self.set_wanted("Status='Failed'")
        self.assertEqual(self.events(), [])
        self.hook(on_grab=True)
        self.set_wanted("Status='Snatched'")
        self.set_wanted("Status='Failed'")
        self.assertEqual(self.events(), [('Grab', 0, None)], 'No connection wants failures')

    def test_a_downloads_events(self):
        self.hook(on_grab=True, on_download=True, on_download_failure=True, on_manual_interaction_required=True)
        self.snatched()
        self.set_wanted("DLResult='Import blocked: No ebook found'")
        self.set_wanted("DLResult='Import blocked: Still no ebook found'")
        self.set_wanted("Status='Processed', DLResult='/books/Without Fail.epub'")
        self.set_wanted("Status='Seeding'")
        self.snatched(url='http://x/2')
        self.set_wanted("Status='Failed', DLResult='NZBGet deleted it'", url='http://x/2')
        self.assertEqual(self.events(), [('Grab', 0, None),
                                         ('ManualInteractionRequired', 0, 'Import blocked: No ebook found'),
                                         ('Download', 0, None), ('Grab', 0, None),
                                         ('DownloadFailure', 0, 'NZBGet deleted it')])

    def test_an_import_of_a_book_with_a_file_is_an_upgrade(self):
        self.hook(on_upgrade=True)
        with DBConnection() as db:
            db.action("UPDATE books SET BookFile='/books/Without Fail.pdf' WHERE BookID='nb1'")
        self.snatched()
        self.set_wanted("Status='Processed'")
        self.assertEqual(self.events(), [('Grab', 1, None), ('Download', 1, None)])


class SendTest(NotificationsTestCase):

    def test_grab_and_import_payloads(self):
        self.hook(on_grab=True, on_download=True)
        self.snatched()
        grab, = self.sent()
        self.assertEqual(grab['eventType'], 'Grab')
        self.assertEqual(grab['author'], {'id': 'na1', 'name': 'Lee Child'})
        self.assertEqual(grab['books'][0]['title'], 'Without Fail')
        self.assertEqual(grab['books'][0]['isbn'], '9780515136562')
        self.assertEqual(grab['release'], {'releaseTitle': 'Lee Child - Without Fail epub', 'indexer': 'TestProvider',
                                           'size': 1572864, 'quality': 'EPUB', 'protocol': 'usenet'})
        self.assertEqual((grab['downloadClient'], grab['downloadId'], grab['mediaType']),
                         ('SABnzbd', 'SABnzbd_nzo_1', 'ebook'))
        with DBConnection() as db:
            db.action("UPDATE books SET BookFile='/books/Without Fail.epub' WHERE BookID='nb1'")
        self.set_wanted("Status='Processed'")
        Receiver.received = []
        imported, = self.sent()
        self.assertEqual(imported['eventType'], 'Download')
        self.assertFalse(imported['isUpgrade'])
        self.assertEqual(imported['bookFiles'], [{'path': '/books/Without Fail.epub', 'quality': 'EPUB', 'size': 0}])
        self.assertEqual(self.sent(), [], 'Each is sent once')

    def test_upgrades_go_to_the_upgrade_connections(self):
        self.hook('Imports', on_download=True)
        self.hook('Upgrades', on_upgrade=True)
        with DBConnection() as db:
            db.action("UPDATE books SET BookFile='/books/Without Fail.pdf' WHERE BookID='nb1'")
        self.snatched()
        self.set_wanted("Status='Processed'")
        self.assertEqual([body['isUpgrade'] for body in self.sent()], [True])

    def test_a_manual_import_was_never_grabbed(self):
        self.hook(on_grab=True, on_download=True)
        self.snatched(source='MANUAL')
        self.set_wanted("Status='Processed'")
        self.assertEqual([(body['eventType'], body['downloadClient']) for body in self.sent()],
                         [('Download', 'Manual Import')])

    def test_failure_and_blocked_payloads(self):
        self.hook(on_download_failure=True, on_manual_interaction_required=True)
        self.snatched()
        self.set_wanted("DLResult='Import blocked: No ebook found'")
        self.set_wanted("Status='Failed', DLResult='NZBGet deleted it'")
        blocked, failed = self.sent()
        self.assertEqual((blocked['eventType'], blocked['message'], blocked['downloadStatusMessages']),
                         ('ManualInteractionRequired', 'No ebook found',
                          [{'title': 'Lee Child - Without Fail epub', 'messages': ['No ebook found']}]))
        self.assertEqual((failed['eventType'], failed['message']), ('DownloadFailure', 'NZBGet deleted it'))

    def test_method_login_and_headers(self):
        definition = self.hook(on_grab=True)
        definition['settings'].update(method='PUT', username='me', password='secret',
                                      headers=[{'key': 'X-Token', 'value': 'abc'}])
        notifications.save(definition, definition['id'])
        self.snatched()
        self.sent()
        request, = Receiver.received
        self.assertEqual(request['method'], 'PUT')
        self.assertEqual(request['headers']['X-Token'], 'abc')
        self.assertEqual(request['headers']['Authorization'], f"Basic {base64.b64encode(b'me:secret').decode()}")
        self.assertEqual(request['headers']['Content-Type'], 'application/json')

    def test_a_failing_connection_shows_in_health(self):
        self.hook(on_grab=True)
        Receiver.status = 500
        self.snatched()
        self.sent()
        self.assertEqual([(c['source'], c['message']) for c in notifications.health_checks()],
                         [('NotificationStatusCheck', 'Notification unavailable due to failures: Hook')])
        self.assertEqual(self.events()[0][0], 'Grab')
        Receiver.status = 200
        self.snatched(url='http://x/2')
        self.sent()
        self.assertEqual(notifications.health_checks(), [], 'It works again')

    def test_late_events_are_not_sent(self):
        self.hook(on_grab=True)
        self.snatched()
        with DBConnection() as db:
            db.action("UPDATE notificationevents SET Created='2020-01-01 00:00:00'")
        self.assertEqual(self.sent(), [])


class SettingsTest(NotificationsTestCase):

    def test_saving_checks_it(self):
        good = self.hook()
        for change, why in (({'name': ' '}, 'name'), ({'settings': {'url': 'ftp://x'}}, 'web address'),
                            ({'settings': {'url': self.url, 'method': 'GET'}}, 'method'),
                            ({'settings': {'url': self.url, 'headers': [{'key': 'Bad Name', 'value': 'x'}]}},
                             'header name'),
                            ({'settings': {'url': self.url, 'headers': [{'key': 'X', 'value': 'a\r\nB: c'}]}},
                             'one line'),
                            ({'implementation': 'Discord'}, 'kind')):
            with self.subTest(why), self.assertRaisesRegex(InvalidRequestError, why):
                notifications.save({**good, 'id': 0, 'name': 'Other', **change})
        with self.assertRaisesRegex(InvalidRequestError, 'called Hook already'):
            notifications.save({**good, 'id': 0})

    def test_the_password_is_never_sent_back(self):
        definition = self.hook()
        definition['settings']['password'] = 'secret'
        saved = notifications.save(definition, definition['id'])
        self.assertEqual(saved['settings']['password'], notifications.MASK)
        saved['name'] = 'Renamed'
        notifications.save(saved, saved['id'])
        with DBConnection() as db:
            stored = json.loads(db.match('SELECT Settings FROM notifications')['Settings'])
        self.assertEqual(stored['password'], 'secret', 'Saved masked, it keeps the password')

    def test_test(self):
        definition = self.hook()
        notifications.test(definition, definition['id'])
        self.assertEqual(Receiver.received[0]['body']['eventType'], 'Test')
        Receiver.status = 401
        with self.assertRaisesRegex(InvalidRequestError, 'Unable to send the test notification: 401'):
            notifications.test(definition)

    def test_delete(self):
        definition = self.hook()
        notifications.delete(definition['id'])
        self.assertEqual(notifications.list_notifications(), [])


class HealthAndUpdateTest(NotificationsTestCase):

    def checks(self, *found):
        return mock.patch.object(health, 'checks', return_value=[
            {'source': source, 'type': kind, 'message': message, 'link': ''} for source, kind, message in found])

    def test_new_issues_and_restored_ones(self):
        self.hook(on_health_issue=True, on_health_restored=True)
        with self.checks(('RootFolderCheck', 'error', 'The eBook library folder [/books] is missing'),
                         ('ImportBlockedCheck', 'warning', '1 download could not be imported'),
                         ('UpdateCheck', 'notice', 'A new version is available')):
            notifications.check_health()
        self.assertEqual([(b['eventType'], b['type']) for b in self.sent()], [('Health', 'RootFolderCheck')],
                         'Warnings only when asked for')
        Receiver.received = []
        with self.checks(('ImportBlockedCheck', 'warning', '2 downloads could not be imported')):
            notifications.check_health()
        self.assertEqual([(b['eventType'], b['level'], b['message']) for b in self.sent()],
                         [('HealthRestored', 'error', 'The eBook library folder [/books] is missing')])

    def test_warnings_when_asked_for(self):
        self.hook(on_health_issue=True, include_health_warnings=True)
        with self.checks(('IndexerCheck', 'warning', 'No indexers are enabled')):
            notifications.check_health()
            notifications.check_health()
        self.assertEqual([b['level'] for b in self.sent()], ['warning'], 'Told once')

    def test_an_update(self):
        self.hook(on_application_update=True)
        saved = CONFIG['CURRENT_VERSION']
        self.addCleanup(CONFIG.set_str, 'CURRENT_VERSION', saved)
        CONFIG.set_str('CURRENT_VERSION', 'aaaa1111')
        notifications.check_version()
        notifications.check_version()
        CONFIG.set_str('CURRENT_VERSION', 'bbbb2222')
        notifications.check_version()
        update, = self.sent()
        self.assertEqual((update['eventType'], update['previousVersion'], update['newVersion']),
                         ('ApplicationUpdate', 'aaaa1111', 'bbbb2222'))
