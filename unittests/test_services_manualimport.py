#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test services/queue.py, the download queue, and services/manualimport.py, Manual Import, with
#   real files going through the post processor's import, and the commands that run imports

import logging
import os
import time
from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.postprocess import replace_audiobook_files
from lazylibrarian.services import InvalidRequestError, NotFoundError, commands, manualimport, queue
from unittests.test_postprocess import ProcessDirTestCase


class ManualImportTestCase(ProcessDirTestCase):

    def setUp(self):
        super().setUp()
        self.db.action("DELETE FROM wanted")  # the database is shared by the class's tests
        queue._asked.clear()
        for name, value in (('get_download_progress', (100, True)), ('delete_task', True),
                            ('get_download_name', None), ('check_contents', None)):
            patch = mock.patch(f'lazylibrarian.postprocess.{name}', return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        self.create_test_author_and_book("mi_001", "John Doe", "Test Book One")
        self.create_test_author_and_book("mi_002", "Jane Roe", "Another Story")
        self.db.action("UPDATE books SET Status='Wanted' WHERE BookID IN ('mi_001','mi_002')")
        self.incoming = os.path.join(self.test_root, "incoming")
        os.makedirs(self.incoming)

    def write(self, *names, data="book data"):
        path = os.path.join(self.incoming, *names)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(data)
        return path

    def book(self, book_id):
        return self.db.match("SELECT Status,BookFile FROM books WHERE BookID=?", (book_id,))

    def same_book_again(self):
        """ mi_003, Test Book One again, as a library can have a book from two sources """
        self.db.action("INSERT OR REPLACE INTO books (BookID,AuthorID,BookName,Status,AudioStatus) "
                       "SELECT 'mi_003',AuthorID,BookName,'Skipped','Skipped' FROM books WHERE BookID='mi_001'")

    def queued(self, book_id="mi_001", title="John_Doe-Test_Book_One", result="", book_type="eBook"):
        self.create_snatched_download(book_id, title, book_type=book_type, source="SABNZBD",
                                      download_id=f"nzo_{book_id}")
        status = 'AudioStatus' if book_type == 'AudioBook' else 'Status'
        self.db.action(f"UPDATE books SET {status}='Snatched' WHERE BookID=?", (book_id,))
        if result:
            self.db.action("UPDATE wanted SET DLResult=? WHERE BookID=?", (result, book_id))
        return self.db.match("SELECT rowid FROM wanted WHERE BookID=?", (book_id,))['rowid']


class QueueTest(ManualImportTestCase):

    def test_list(self):
        blocked = self.queued(result="Import blocked: [/downloads/x] was not found")
        downloading = self.queued("mi_002", "Jane_Roe-Another_Story")
        with mock.patch('lazylibrarian.services.queue.get_download_progress',
                        side_effect=lambda source, download_id: (100, True) if download_id == 'nzo_mi_001'
                        else (42, False)):
            items = {item['id']: item for item in queue.list_queue()}
        item = items[blocked]
        self.assertEqual((item['title'], item['author'], item['media_type'], item['download_client'], item['protocol']),
                         ('Test Book One', 'John Doe', 'ebook', 'SABnzbd', 'usenet'))
        self.assertEqual((item['status'], item['tracked_download_state'], item['tracked_download_status']),
                         ('completed', 'importBlocked', 'warning'), 'Like Sonarr')
        self.assertEqual(item['status_messages'], [{'title': 'John_Doe-Test_Book_One',
                                                    'messages': ['[/downloads/x] was not found']}])
        self.assertEqual((items[downloading]['status'], items[downloading]['progress']), ('downloading', 42))

    def test_client_unavailable_or_without_it(self):
        item_id = self.queued()
        for progress, status in ((-2, 'downloadClientUnavailable'), (-1, 'warning'), (100, 'completed')):
            queue._asked.clear()
            with mock.patch('lazylibrarian.services.queue.get_download_progress', return_value=(progress, False)):
                item = queue.list_queue()[0]
            self.assertEqual((item['id'], item['status']), (item_id, status), progress)

    def test_progress_is_kept_a_while(self):
        self.queued()
        with mock.patch('lazylibrarian.services.queue.get_download_progress', return_value=(10, False)) as asked:
            queue.list_queue()
            queue.list_queue()
        asked.assert_called_once()

    def test_remove(self):
        item_id = self.queued()
        with mock.patch('lazylibrarian.services.queue.delete_task', return_value=True) as delete:
            self.assertEqual(queue.remove(item_id), '')
        delete.assert_called_once_with('SABNZBD', 'nzo_mi_001', True, abandoned=True)
        self.assertFalse(self.db.match("SELECT * FROM wanted WHERE rowid=?", (item_id,)), 'Forgotten')
        self.assertEqual(self.book('mi_001')['Status'], 'Wanted')
        with self.assertRaises(NotFoundError):
            queue.remove(item_id)

    def test_remove_and_blocklist(self):
        item_id = self.queued()
        with mock.patch('lazylibrarian.services.queue.delete_task') as delete, \
                mock.patch('lazylibrarian.services.queue.books.start_search') as search:
            queue.remove(item_id, remove_from_client=False, blocklist=True)
        delete.assert_not_called()
        search.assert_called_once_with([{'bookid': 'mi_001'}], library='eBook', force=True)
        self.assertEqual(self.db.match("SELECT Status FROM wanted WHERE rowid=?", (item_id,))['Status'], 'Failed',
                         'A search won\'t take it again')

        item_id = self.queued("mi_002", "Jane_Roe-Another_Story")
        with mock.patch('lazylibrarian.services.queue.delete_task', return_value=False), \
                mock.patch('lazylibrarian.services.queue.books.start_search') as search:
            message = queue.remove(item_id, blocklist=True, skip_redownload=True)
        search.assert_not_called()
        self.assertIn('did not remove', message)


class CandidatesTest(ManualImportTestCase):

    def test_a_folder(self):
        self.write("John Doe - Test Book One.epub")
        self.write("John Doe - Test Book One.mobi")
        self.write("Unknown Thing", "track 01.mp3")
        self.write("chapter 1.mp3")
        self.write("chapter 2.mp3")
        self.write("readme.txt")
        found = manualimport.candidates(self.incoming)
        self.assertEqual(found['error'], '')
        items = {item['relative_path']: item for item in found['items']}
        self.assertEqual(set(items), {'John Doe - Test Book One.epub', 'Unknown Thing', 'chapter 1.mp3'})
        ebook = items['John Doe - Test Book One.epub']
        self.assertEqual((ebook['media_type'], len(ebook['files']), ebook['book']['id'], ebook['rejections']),
                         ('ebook', 2, 'mi_001', []), 'The formats of one book are one item')
        loose = items['chapter 1.mp3']
        self.assertEqual((loose['media_type'], loose['path'], len(loose['files'])), ('audiobook', self.incoming, 2),
                         'The audio files in a folder are one audiobook')
        self.assertEqual(items['Unknown Thing']['rejections'], ['Choose the book'])

    def test_bad_folders(self):
        with self.assertRaises(InvalidRequestError):
            manualimport.candidates('relative/folder')
        with self.assertRaises(NotFoundError):
            manualimport.candidates(os.path.join(self.test_root, 'missing'))

    def test_a_queued_download(self):
        item_id = self.queued()
        client = os.path.join(self.download_dir, "John_Doe-Test_Book_One")
        with mock.patch('lazylibrarian.postprocess.get_download_folder', return_value=client):
            found = manualimport.candidates(queue_id=item_id)
            self.assertIn('was not found', found['error'])
            self.create_ebook_file(os.path.join(client, "Test Book One.epub"))
            found = manualimport.candidates(queue_id=item_id)
        self.assertEqual(len(found['items']), 1, 'Its folder is one item, as the post processor takes it')
        item = found['items'][0]
        self.assertEqual((item['path'], item['relative_path'], item['queue_id'], item['book']['id']),
                         (client, "John_Doe-Test_Book_One", item_id, 'mi_001'))
        # a folder chosen for it lists what is in there, for its book
        self.write("Test Book One.epub")
        found = manualimport.candidates(self.incoming, item_id)
        self.assertEqual([(i['relative_path'], i['book']['id']) for i in found['items']],
                         [('Test Book One.epub', 'mi_001')])

    def test_a_folder_that_is_a_queued_download(self):
        # the reported one: the library had the book twice, the import guessed the other one, so the
        # download it was stayed in the queue. A folder named as the release is that download
        self.same_book_again()
        item_id = self.queued(title="John Doe - Test Book One MP3", book_type="AudioBook")
        self.write("John Doe - Test Book One MP3", "John Doe - Test Book One 01.mp3")
        self.write("John Doe - Test Book One MP3", "John Doe - Test Book One 02.mp3")
        self.write("Jane Roe - Another Story", "Another Story.epub")
        items = {item['relative_path']: item for item in manualimport.candidates(self.incoming)['items']}
        item = items["John Doe - Test Book One MP3"]
        self.assertEqual((item['queue_id'], item['book']['id'], item['media_type']), (item_id, 'mi_001', 'audiobook'))
        self.assertIsNone(items["Jane Roe - Another Story"]['queue_id'])
        # and its loose files, when the download's own folder is chosen
        item = manualimport.candidates(os.path.join(self.incoming, "John Doe - Test Book One MP3"))['items'][0]
        self.assertEqual((item['queue_id'], item['book']['id']), (item_id, 'mi_001'))

    def test_the_same_book_twice_guesses_the_wanted_one(self):
        self.same_book_again()
        self.db.action("UPDATE books SET Status='Skipped' WHERE BookID='mi_001'")
        self.db.action("UPDATE books SET Status='Wanted' WHERE BookID='mi_003'")
        self.write("John Doe - Test Book One.epub")
        self.assertEqual(manualimport.candidates(self.incoming)['items'][0]['book']['id'], 'mi_003')

    def test_search_books(self):
        self.assertEqual([book['id'] for book in manualimport.search_books('roe story')], ['mi_002'])
        self.assertEqual(manualimport.search_books(' '), [])

    def test_already_in_the_library(self):
        have = self.write("library copy", "Test Book One.epub")
        self.db.action("UPDATE books SET BookFile=? WHERE BookID='mi_001'", (have,))
        self.write("John Doe - Test Book One.epub")
        item = next(i for i in manualimport.candidates(self.incoming)['items'] if i['book'])
        rejection = f"{manualimport.ALREADY} {have}, importing replaces the same format"
        self.assertEqual(item['rejections'], [rejection], 'Like Sonarr\'s existing file')
        item_id = self.queued()
        item = manualimport.candidates(self.incoming, item_id)['items'][0]
        self.assertIn(rejection, item['rejections'], 'A queued download\'s book too')

    def test_suggested_folders(self):
        mapped = os.path.join(self.test_root, "mapped")
        os.makedirs(mapped)
        with mock.patch.object(manualimport.remotepaths, 'mappings',
                               return_value=[{'Id': 1, 'Host': 'nas', 'RemotePath': '/downloads', 'LocalPath': mapped},
                                             {'Id': 2, 'Host': 'nas', 'RemotePath': '/x', 'LocalPath': '/gone'}]):
            folders = manualimport.suggested_folders()
        self.assertIn({'path': os.path.normpath(self.download_dir), 'label': 'Download directory'}, folders)
        self.assertIn({'path': os.path.normpath(mapped), 'label': 'nas /downloads'}, folders)
        self.assertNotIn('/gone', [folder['path'] for folder in folders])


class ImportTest(ManualImportTestCase):

    def test_a_folder_for_a_queued_book(self):
        # the reported one: importing a book from a folder left its queued download in the queue
        item_id = self.queued()
        epub = self.write("John Doe - Test Book One.epub")
        manualimport.import_item({'path': epub, 'files': [epub], 'media_type': 'ebook', 'book_id': 'mi_001'})
        self.assertEqual(self.db.match("SELECT Status FROM wanted WHERE rowid=?", (item_id,))['Status'], 'Processed')
        self.assertEqual(len(self.db.select("SELECT * FROM wanted WHERE BookID='mi_001'")), 1, 'No Manual row')

    def test_a_queued_download_found_in_a_folder(self):
        # importing what the folder's candidates say, as the page does, takes it off the queue
        self.same_book_again()
        item_id = self.queued(title="John Doe - Test Book One MP3", book_type="AudioBook")
        self.write("John Doe - Test Book One MP3", "John Doe - Test Book One 01.mp3")
        self.write("John Doe - Test Book One MP3", "John Doe - Test Book One 02.mp3")
        item = manualimport.candidates(os.path.join(self.incoming, "John Doe - Test Book One MP3"))['items'][0]
        manualimport.import_item({**item, 'book_id': item['book']['id']})
        self.assertEqual(self.db.match("SELECT Status FROM wanted WHERE rowid=?", (item_id,))['Status'], 'Processed')
        self.assertEqual(queue.list_queue(), [])
        self.assertEqual(len(self.db.select("SELECT * FROM wanted")), 1, 'No Manual row')

    def test_the_queue_has_no_manual_rows(self):
        self.db.action("INSERT INTO wanted (BookID,NZBurl,NZBtitle,Status,AuxInfo,Source) VALUES "
                       "('mi_002','manual:1','x','Snatched','eBook','MANUAL')")
        self.assertEqual(queue.list_queue(), [])

    def test_a_queued_book_that_does_not_import_from_another_folder_is_not_blocked(self):
        item_id = self.queued()
        folder = os.path.dirname(self.write("chosen", "notes.txt"))
        with self.assertRaises(InvalidRequestError):
            manualimport.import_item({'path': folder, 'media_type': 'ebook', 'book_id': 'mi_001'})
        self.assertFalse(self.db.match("SELECT DLResult FROM wanted WHERE rowid=?", (item_id,))['DLResult'])

    def test_from_a_folder(self):
        epub = self.write("John Doe - Test Book One.epub")
        other = self.write("Somebody Else.epub")
        message = manualimport.import_item({'path': epub, 'files': [epub], 'media_type': 'ebook',
                                            'book_id': 'mi_001'})
        self.assertTrue(message.endswith('.epub'), message)
        self.assertTrue(os.path.isfile(message), 'In the library')
        row = self.db.match("SELECT Status,NZBprov,AuxInfo FROM wanted WHERE BookID='mi_001'")
        self.assertEqual(tuple(row), ('Processed', 'Manual', 'eBook'), 'In the history')
        self.assertTrue(os.path.exists(other), 'Only the files chosen')
        self.assertFalse([name for name in os.listdir(DIRS.TMPDIR) if name.startswith('manualimport-')],
                         'The working copy is gone')

    def test_nothing_to_import(self):
        text = self.write("notes", "notes.txt")
        with self.assertRaises(InvalidRequestError) as cm:
            manualimport.import_item({'path': os.path.dirname(text), 'media_type': 'ebook', 'book_id': 'mi_001'})
        self.assertEqual(str(cm.exception), 'No valid file or archives found')
        self.assertTrue(os.path.exists(text), 'Its files are kept')
        self.assertFalse(os.path.exists(f"{os.path.dirname(text)}.fail"), 'Not renamed')
        self.assertFalse(self.db.match("SELECT * FROM wanted WHERE BookID='mi_001'"), 'Nothing in the history')
        with self.assertRaises(InvalidRequestError):
            manualimport.import_item({'path': text, 'media_type': 'ebook', 'book_id': 'nosuchbook'})

    def test_a_blocked_download(self):
        item_id = self.queued(result="Import blocked: [/downloads/x] was not found")
        folder = os.path.dirname(self.write("chosen", "Test Book One.epub"))
        manualimport.import_item({'path': folder, 'media_type': 'ebook', 'book_id': 'mi_001', 'queue_id': item_id})
        row = self.db.match("SELECT Status,BookID FROM wanted WHERE rowid=?", (item_id,))
        self.assertEqual(tuple(row), ('Processed', 'mi_001'))
        self.assertNotEqual(self.book('mi_001')['Status'], 'Snatched')

    def test_a_download_that_was_something_else(self):
        item_id = self.queued()
        folder = os.path.dirname(self.write("chosen", "Another Story.epub"))
        manualimport.import_item({'path': folder, 'media_type': 'ebook', 'book_id': 'mi_002', 'queue_id': item_id})
        self.assertEqual(self.db.match("SELECT BookID FROM wanted WHERE rowid=?", (item_id,))['BookID'], 'mi_002')
        self.assertEqual(self.book('mi_001')['Status'], 'Wanted', 'The book it was for is wanted again')

    def test_a_failed_queued_import_is_blocked(self):
        item_id = self.queued()
        folder = os.path.dirname(self.write("chosen", "notes.txt"))
        with self.assertRaises(InvalidRequestError):
            manualimport.import_item({'path': folder, 'media_type': 'ebook', 'book_id': 'mi_001',
                                      'queue_id': item_id})
        row = self.db.match("SELECT Status,DLResult FROM wanted WHERE rowid=?", (item_id,))
        self.assertEqual(row['Status'], 'Snatched')
        self.assertTrue(row['DLResult'] == 'Import blocked: No valid file or archives found', row['DLResult'])


class ReplaceAudiobookTest(ManualImportTestCase):
    """ Like Sonarr replacing an episode's file: an audiobook imported where one already is replaces it """

    def setUp(self):
        super().setUp()
        self.library = os.path.join(self.audio_library, "John Doe", "Test Book One")
        self.download = os.path.join(self.incoming, "new copy")
        for folder, names in ((self.library, ("Test Book One Part 01 of 02.mp3", "Test Book One Part 02 of 02.mp3",
                                              "cover.jpg")),
                              (self.download, ("Track 01.mp3", "Track 02.mp3"))):
            os.makedirs(folder, exist_ok=True)
            for name in names:
                with open(os.path.join(folder, name), "w") as f:
                    f.write(folder)
        saved = CONFIG['RECYCLE_BIN']
        self.addCleanup(CONFIG.set_str, 'RECYCLE_BIN', saved)
        CONFIG.set_str('RECYCLE_BIN', '')

    def test_the_old_parts_are_deleted(self):
        replace_audiobook_files(self.download, self.library, logging.getLogger(__name__))
        self.assertEqual(os.listdir(self.library), ["cover.jpg"], 'Only the audio files go')

    def test_or_go_to_the_recycling_bin(self):
        recycle_bin = os.path.join(self.test_root, "recycle")
        CONFIG.set_str('RECYCLE_BIN', recycle_bin)
        replace_audiobook_files(self.download, self.library, logging.getLogger(__name__))
        self.assertEqual(sorted(os.listdir(os.path.join(recycle_bin, "John Doe", "Test Book One"))),
                         ["Test Book One Part 01 of 02.mp3", "Test Book One Part 02 of 02.mp3"],
                         'In the folders they were in')

    def test_importing_one(self):
        # the reported one: a second import of Without Fail left two sets of parts
        self.db.action("UPDATE books SET AudioFile=? WHERE BookID='mi_001'",
                       (os.path.join(self.library, "Test Book One Part 01 of 02.mp3"),))
        manualimport.import_item({'path': self.download, 'media_type': 'audiobook', 'book_id': 'mi_001'})
        audio = sorted(name for name in os.listdir(self.library) if name.endswith('.mp3'))
        self.assertEqual(len(audio), 2, audio)
        self.assertFalse([name for name in audio if 'Part 01 of 02' in name and 'Track' in name])
        for name in audio:
            with open(os.path.join(self.library, name)) as f:
                self.assertEqual(f.read(), self.download, f'{name} is from the new copy')

    def test_not_when_importing_from_the_library_folder(self):
        replace_audiobook_files(self.library, self.library, logging.getLogger(__name__))
        replace_audiobook_files(os.path.dirname(self.library), self.library, logging.getLogger(__name__))
        self.assertEqual(len(os.listdir(self.library)), 3)


class CommandTest(ManualImportTestCase):

    def wait(self, command):
        for _ in range(200):
            command = commands.get(command['id'])
            if command['status'] in ('completed', 'failed'):
                return command
            time.sleep(0.05)
        raise AssertionError(f'{command} did not finish')

    def test_manual_import(self):
        epub = self.write("John Doe - Test Book One.epub")
        command = self.wait(commands.start('ManualImport', {'files': [
            {'path': epub, 'files': [epub], 'media_type': 'ebook', 'book_id': 'mi_001'},
            {'path': os.path.join(self.incoming, 'gone'), 'media_type': 'ebook', 'book_id': 'mi_002'}]}))
        self.assertEqual(command['status'], 'completed', command)
        self.assertTrue(command['message'].startswith('Imported 1 of 2. '), command['message'])
        self.assertEqual([result['imported'] for result in command['result']], [True, False])
        self.assertEqual(commands.list_commands()[0]['id'], command['id'], 'Most recent first')

    def test_nothing_imported_fails(self):
        command = self.wait(commands.start('ManualImport', {'files': []}))
        self.assertEqual((command['status'], command['message']), ('failed', 'Choose something to import'))
        with self.assertRaises(InvalidRequestError):
            commands.start('NoSuchCommand', {})
        with self.assertRaises(NotFoundError):
            commands.get(0)
