#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the Windows libmagic check in filemagic.py

import unittest
from unittest import mock

from lazylibrarian import filemagic


class NativeLibmagicTest(unittest.TestCase):

    def available(self, libraries: dict, bundled=False) -> bool:
        """ native_libmagic_available() with find_library finding just these libraries """
        with mock.patch.object(filemagic, 'find_library', side_effect=libraries.get), \
                mock.patch.object(filemagic.os.path, 'isfile', return_value=False), \
                mock.patch.object(filemagic.os.path, 'isdir', return_value=bundled):
            return filemagic.native_libmagic_available()

    def test_msys_and_cygwin_libmagic_are_not_used(self):
        # Git for Windows' copy, which hangs a Windows Python when it's loaded
        self.assertFalse(self.available({'msys-magic-1': r'C:\Program Files\Git\usr\bin\msys-magic-1.dll'}))
        self.assertFalse(self.available({'cygmagic-1': r'C:\cygwin64\bin\cygmagic-1.dll'}))
        self.assertFalse(self.available({}))

    def test_native_libmagic(self):
        for name in filemagic.NATIVE_WINDOWS_LIBS:
            self.assertTrue(self.available({name: rf'C:\tools\{name}.dll'}), name)

    def test_python_magic_bin(self):
        self.assertTrue(self.available({}, bundled=True))
