#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test what an import does with a download's archives and Calibre: a rar set's volumes aren't
#   unpacked one by one after the set is (postprocess._extract_archives_in_directory), a file that
#   can't be read from an archive leaves no empty file (archive_utils.unpack_archive), and a book
#   Calibre has already is found by its identifier (calibre_integration.calibre_book_with)

import os
import shutil
import tempfile
import zipfile
from unittest import mock

from lazylibrarian import calibre_integration, postprocess
from lazylibrarian.archive_utils import unpack_archive
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


class ArchivePartsTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_rar_sets_volumes_arent_unpacked_one_by_one(self):
        """ The release's zips, each a volume of a rar set, unpacked together; the set's volumes,
        the .rar too, aren't unpacked again on their own, which emptied the folder it went to """
        release = os.path.join(self.root, 'release')
        unpacked = os.path.join(self.root, 'release.unpack')
        os.makedirs(release)
        os.makedirs(unpacked)
        for name in ('pma.zip', 'pmb.zip'):
            with zipfile.ZipFile(os.path.join(release, name), 'w') as archive:
                archive.writestr('file_id.diz', b'notes')
        for name in ('pm.rar', 'pm.r00', 'pm.r04', 'pm.part2.rar', 'issue.pdf'):
            with open(os.path.join(unpacked, name), 'wb') as f:
                f.write(b'x')
        with mock.patch.object(postprocess, 'unpack_multipart', return_value=unpacked), \
                mock.patch.object(postprocess, 'unpack_archive', return_value='') as each:
            found, changed = postprocess._extract_archives_in_directory(release, self.root, 'release')
        self.assertEqual((found, changed), (unpacked, True))
        self.assertEqual([os.path.basename(call.args[0]) for call in each.call_args_list], ['issue.pdf'],
                         'Only what is not a volume of the set')
        self.assertTrue(postprocess.RAR_VOLUME.search('Name.R12'))
        self.assertFalse(postprocess.RAR_VOLUME.search('name.part1.rar'), 'The first is the set')

    def test_one_that_cant_be_read_leaves_no_empty_file(self):
        archive_path = os.path.join(self.root, 'issue.zip')
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('Issue.pdf', b'%PDF-1.4 ' + b'page ' * 2000)
        with open(archive_path, 'r+b') as f:  # its data damaged, so reading it fails its check
            f.seek(200)
            f.write(b'damaged')
        target = unpack_archive(archive_path, self.root, 'issue')
        self.assertFalse(os.path.exists(os.path.join(target, 'Issue.pdf')))

    def test_a_book_calibre_has_already(self):
        with mock.patch.object(calibre_integration, 'calibredb', return_value=('[{"id": 1021}]', '', 0)) as asked:
            self.assertEqual(calibre_integration.calibre_book_with('hardcover:536511'), '1021')
        self.assertIn('identifiers:"=hardcover:536511"', asked.call_args.args[1])
        for answer in (('[]', '', 0), ('', 'Connection refused', 1), ('not json [', '', 0)):
            with mock.patch.object(calibre_integration, 'calibredb', return_value=answer):
                self.assertEqual(calibre_integration.calibre_book_with('OpenLibrary:OL1W'), '', answer)
        with mock.patch.object(calibre_integration, 'calibredb') as asked:
            self.assertEqual(calibre_integration.calibre_book_with(''), '')
        asked.assert_not_called()
