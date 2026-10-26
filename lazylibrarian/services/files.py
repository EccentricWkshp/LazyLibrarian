#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

""" Removing book and issue files from the library and from Calibre """

import logging
import os
from shutil import rmtree

from lazylibrarian.calibre import calibredb, get_calibre_id
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import remove_file, splitext, syspath


def remove_from_calibre(data):
    """ Remove a book or issue from the Calibre library, if it's in there """
    logger = logging.getLogger(__name__)
    calibre_id = get_calibre_id(data)
    if calibre_id:
        res, err, rc = calibredb('remove', [calibre_id])
        logger.debug(f"Delete result: {res} [{err}] {rc}")


def delete_issue_file(issuefile) -> bool:
    """ Delete a magazine or comic issue with its cover and opf, and its folder if that's now
        empty and MAG_DELFOLDER is set. Returns whether it worked """
    logger = logging.getLogger(__name__)
    try:
        remove_file(issuefile)
        fname, _ = splitext(issuefile)
        for extn in ['.opf', '.jpg']:
            remove_file(fname + extn)
        if CONFIG.get_bool('MAG_DELFOLDER'):
            parent_dir = syspath(os.path.dirname(issuefile))
            files = os.listdir(parent_dir)
            if not files or (len(files) == 1 and files[0] == '.ll_ignore'):
                logger.debug(f'Directory {parent_dir} deleted as empty')
                rmtree(parent_dir)
            else:
                logger.warning(f'Directory {parent_dir} not deleted as not empty')
                logger.debug(f"{files}")
        return True
    except Exception as e:
        logger.warning(f'delete issue failed on {issuefile}, {type(e).__name__} {str(e)}')
        return False
