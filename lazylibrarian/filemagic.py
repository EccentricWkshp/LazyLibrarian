#  This file is part of Lazylibrarian.
#
# Purpose:
#   python-magic, or None when no usable libmagic is installed. Import it from here:
#       from lazylibrarian.filemagic import magic
#   On Windows python-magic falls back to the msys or cygwin build of libmagic, and Git for
#   Windows puts msys-magic-1.dll on the PATH when its Unix tools are installed there (GitHub's
#   Windows runners have them). Loading that into a Windows Python hangs the process, so on
#   Windows magic is only imported when a native libmagic is available.

import importlib.util
import os
import sys
from ctypes.util import find_library

# The libmagic names python-magic tries that are Windows builds, not msys or cygwin ones
NATIVE_WINDOWS_LIBS = ('magic', 'libmagic', 'magic1', 'libmagic-1')


def native_libmagic_available() -> bool:
    for name in NATIVE_WINDOWS_LIBS:
        if find_library(name) or os.path.isfile(f'{name}.dll'):
            return True
    # python-magic-bin bundles a native libmagic inside the package
    spec = importlib.util.find_spec('magic')
    return bool(spec and spec.origin and os.path.isdir(os.path.join(os.path.dirname(spec.origin), 'libmagic')))


magic = None
if sys.platform != 'win32' or native_libmagic_available():
    try:
        import magic
    except Exception:  # magic might fail for multiple reasons
        magic = None
