#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test Readarr's v1 API for the apps that manage Readarr (lazylibrarian/readarr): each format's
#   authors and books in Readarr's shapes with whole number ids, its queue, history, wanted and
#   settings, beside LazyLibrarian's own /api/v1

import os
from unittest import mock

from fastapi.testclient import TestClient

from lazylibrarian import webapp
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.readarr.ids import AUDIOBOOK, AUTHOR, BOOK, api_id
from unittests.test_webapp import legacy_app
from unittests.unittesthelpers import TESTDIR, LLTestCaseWithDB

KEY = 'k' * 32
READ_KEY = 'r' * 32


class ReadarrApiTest(LLTestCaseWithDB):

    def setUp(self):
        super().setUp()
        settings = ('API_ENABLED', 'API_KEY', 'API_RO_KEY', 'EBOOK_DIR', 'AUDIO_DIR')
        saved = {key: CONFIG[key] for key in settings}
        self.addCleanup(lambda: [CONFIG.set_from_ui(key, value) for key, value in saved.items()])
        CONFIG.set_bool('API_ENABLED', True)
        CONFIG.set_str('API_KEY', KEY)
        CONFIG.set_str('API_RO_KEY', READ_KEY)
        self.library = os.path.join(TESTDIR, 'readarr')
        os.makedirs(self.library, exist_ok=True)
        CONFIG.set_str('EBOOK_DIR', self.library)
        CONFIG.set_str('AUDIO_DIR', self.library)
        self.epub = os.path.join(self.library, 'Killing Floor.epub')
        with open(self.epub, 'wb') as f:
            f.write(b'x' * 1234)
        with DBConnection() as db:
            for table in ('books', 'authors', 'bookauthors', 'series', 'member', 'wanted', 'apiids'):
                db.action(f"DELETE FROM {table}")
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status, DateAdded, AuthorImg, ol_link) VALUES "
                      "('OL1A', 'Lee Child', 'Active', '2026-10-01', 'https://covers/lee.jpg', "
                      "'https://openlibrary.org/authors/OL1A')")
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status) VALUES ('OL2A', 'Hidden Author', 'Ignored')")
            for book_id, name, date, status, audio, bookfile in (
                    ('OL1W', 'Killing Floor', '1997-03-17', 'Open', 'Wanted', self.epub),
                    ('OL2W', 'Die Trying', '1998', 'Wanted', 'Skipped', ''),
                    ('OL3W', 'Tripwire', '2026-11-05', 'Skipped', 'Skipped', '')):
                db.action("INSERT INTO books (BookID, AuthorID, BookName, BookDate, Status, AudioStatus, BookFile, "
                          "BookAdded, BookGenre, ol_id) VALUES (?, 'OL1A', ?, ?, ?, ?, ?, '2026-10-02', "
                          "'Thriller, Crime', ?)", (book_id, name, date, status, audio, bookfile, book_id))
            db.action("INSERT INTO series (SeriesID, SeriesName, Status) VALUES ('S1', 'Jack Reacher', 'Active')")
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES ('S1', 'OL1W', '1')")
            db.action("INSERT INTO wanted (BookID, NZBurl, NZBtitle, NZBdate, NZBprov, Status, AuxInfo, Source, "
                      "NZBmode, NZBsize) VALUES ('OL2W', 'u1', 'Lee.Child.Die.Trying.EPUB', '2026-10-20 10:00:00', "
                      "'p', 'Processed', 'eBook', 'SABNZBD', 'nzb', '1.5')")
        self.client = TestClient(webapp.create_app('/ll', legacy_app))

    def get(self, path, **params):
        return self.client.get(f'/ll/readarr{path}', params=params, headers={'X-Api-Key': KEY})

    def test_the_key_is_needed(self):
        self.assertEqual(self.client.get('/ll/readarr/api/v1/system/status').status_code, 401)
        self.assertEqual(self.client.get('/ll/readarr/api/v1/system/status',
                                         headers={'X-Api-Key': 'x' * 32}).status_code, 401)
        self.assertEqual(self.client.get('/ll/readarr/api/v1/author', params={'apikey': READ_KEY}).status_code, 200)

    def test_it_says_it_is_readarr(self):
        found = self.get('/api/v1/system/status').json()
        self.assertEqual((found['appName'], found['version'], found['urlBase']), ('Readarr', '0.4.18.2805', '/ll/readarr'))
        self.assertEqual(self.get('/audio/api/v1/system/status').json()['urlBase'], '/ll/readarr/audio')
        self.assertEqual(self.client.get('/ll/api/v1/system/status', headers={'X-Api-Key': KEY}).json()['appName'],
                         'LazyLibrarian', 'Our own API is as it was')

    @mock.patch.dict('lazylibrarian.INFOSOURCES', {'OpenLibrary': {'author_link': 'ol_link', 'book_key': 'ol_id',
                                                                   'link_template': 'https://openlibrary.org/works/{}'}})
    def test_authors(self):
        found = self.get('/api/v1/author').json()
        self.assertEqual([a['authorName'] for a in found], ['Lee Child'], 'Not an ignored one')
        lee = found[0]
        self.assertIsInstance(lee['id'], int)
        self.assertEqual((lee['foreignAuthorId'], lee['monitored'], lee['monitorNewItems'], lee['added']),
                         ('OL1A', True, 'new', '2026-10-01T00:00:00Z'))
        self.assertEqual(lee['statistics'], {'bookFileCount': 1, 'bookCount': 2, 'availableBookCount': 1,
                                             'totalBookCount': 3, 'sizeOnDisk': 1234, 'percentOfBooks': 50.0})
        self.assertEqual(lee['images'][0]['url'], f"/ll/readarr/MediaCover/{lee['id']}/poster.jpg")
        self.assertEqual(lee['links'], [{'url': 'https://openlibrary.org/authors/OL1A', 'name': 'OpenLibrary'}])
        self.assertEqual(self.get(f"/api/v1/author/{lee['id']}").json()['authorName'], 'Lee Child')
        self.assertEqual(self.get('/api/v1/author/999').status_code, 404)
        audio = self.get('/audio/api/v1/author').json()[0]
        self.assertEqual(audio['id'], lee['id'], 'An author is one in both')
        self.assertEqual((audio['statistics']['bookCount'], audio['statistics']['availableBookCount']), (1, 0))

    def test_books(self):
        author = self.get('/api/v1/author').json()[0]['id']
        books = {b['title']: b for b in self.get('/api/v1/book', authorId=author).json()}
        self.assertEqual(set(books), {'Killing Floor', 'Die Trying', 'Tripwire'})
        floor = books['Killing Floor']
        self.assertEqual((floor['monitored'], floor['seriesTitle'], floor['releaseDate'], floor['genres'],
                          floor['statistics']['sizeOnDisk'], floor['authorId'], floor['mediaType']),
                         (True, 'Jack Reacher #1', '1997-03-17T00:00:00Z', ['Thriller', 'Crime'], 1234, author, 'ebook'))
        self.assertEqual((floor['ebookMonitored'], floor['audiobookMonitored']), (True, True))
        self.assertEqual(books['Die Trying']['releaseDate'], '1998-01-01T00:00:00Z')
        self.assertFalse(books['Tripwire']['monitored'])
        one = self.get(f"/api/v1/book/{floor['id']}").json()
        self.assertEqual((one['title'], one['author']['authorName']), ('Killing Floor', 'Lee Child'))
        self.assertEqual([b['title'] for b in self.get('/api/v1/book', bookIds=[floor['id']]).json()], ['Killing Floor'])
        audio = {b['title']: b for b in self.get('/audio/api/v1/book', authorId=author).json()}
        self.assertNotEqual(audio['Killing Floor']['id'], floor['id'], "A book's audiobook is another, as in Chaptarr")
        self.assertEqual((audio['Killing Floor']['monitored'], audio['Killing Floor']['mediaType']), (True, 'audiobook'))

    def test_ids_are_kept(self):
        with DBConnection() as db:
            first = api_id(db, AUTHOR, 'OL1A')
            self.assertEqual(api_id(db, AUTHOR, 'OL1A'), first)
            self.assertNotEqual(api_id(db, BOOK, 'OL1W'), api_id(db, AUDIOBOOK, 'OL1W'))

    def test_wanted_and_calendar(self):
        missing = self.get('/api/v1/wanted/missing', pageSize=10).json()
        self.assertEqual((missing['totalRecords'], missing['records'][0]['title']), (1, 'Die Trying'))
        self.assertEqual(missing['records'][0]['author']['authorName'], 'Lee Child')
        self.assertEqual([b['title'] for b in self.get('/audio/api/v1/wanted/missing').json()['records']],
                         ['Killing Floor'])
        found = self.get('/api/v1/calendar', start='2026-11-01', end='2026-11-30', unmonitored='true').json()
        self.assertEqual([b['title'] for b in found], ['Tripwire'])
        self.assertEqual(self.get('/api/v1/calendar', start='2026-11-01', end='2026-11-30').json(), [],
                         'Not an unmonitored one unless asked')

    def test_history_and_queue(self):
        history = self.get('/api/v1/history', pageSize=5).json()
        self.assertEqual(history['totalRecords'], 1)
        event = history['records'][0]
        self.assertEqual((event['eventType'], event['sourceTitle'], event['quality']['quality']['name']),
                         ('bookFileImported', 'Lee.Child.Die.Trying.EPUB', 'EPUB'))
        self.assertEqual(self.get('/audio/api/v1/history').json()['totalRecords'], 0, "Only the format's own")
        with mock.patch('lazylibrarian.services.queue.list_queue', return_value=[]):
            queue = self.get('/api/v1/queue').json()
        self.assertEqual((queue['totalRecords'], queue['records']), (0, []))

    def test_settings(self):
        self.assertEqual(self.get('/api/v1/rootfolder').json()[0]['path'], self.library)
        profiles = self.get('/api/v1/qualityprofile').json()
        self.assertTrue(profiles and all(item['quality']['id'] in (0, 1, 2, 3, 4) or item['quality']['id'] >= 100
                                         for item in profiles[0]['items']), profiles)
        audio_profiles = self.get('/audio/api/v1/qualityprofile').json()
        self.assertIn(12, [item['quality']['id'] for item in audio_profiles[0]['items']], 'M4B is 12, as in Readarr')
        self.assertEqual(self.get('/api/v1/metadataprofile').json()[0]['id'], 1)
        self.assertEqual(self.get('/api/v1/tag').json(), [])

    def test_pictures(self):
        author = self.get('/api/v1/author').json()[0]['id']
        response = self.client.get(f'/ll/readarr/MediaCover/{author}/poster.jpg', headers={'X-Api-Key': KEY},
                                   follow_redirects=False)
        self.assertEqual((response.status_code, response.headers['location']), (307, 'https://covers/lee.jpg'))
        response = self.client.get(f'/ll/readarr/api/v1/MediaCover/{author}/poster.jpg', headers={'X-Api-Key': KEY},
                                   follow_redirects=False)
        self.assertEqual(response.status_code, 307, 'Below /api/v1 too')

    def test_what_is_not_here_is_logged(self):
        with self.assertLogs('lazylibrarian.readarr.api', 'WARNING') as logged:
            self.assertEqual(self.get('/api/v1/series').status_code, 404)
        self.assertIn('no GET /api/v1/series yet', logged.output[0])
