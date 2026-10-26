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

""" Cover thumbnails, Calibre covers, and removing book and issue files from the library and from Calibre """

import logging
import os
from shutil import rmtree

from lazylibrarian.calibre import calibredb, get_calibre_id
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, path_isfile, remove_file, splitext, syspath
from lazylibrarian.images import createthumb


def cover_thumbnail(cover: str) -> tuple[str, str] | None:
    """ A 200 pixel wide thumbnail of a cover in the cache, made if there isn't one yet, as (thumbnail,
        full size) paths starting cache/. The thumbnail is the cover itself if one can't be made.
        None for a cover that isn't in the cache """
    if not cover or not cover.startswith('cache/'):
        return None
    fname, extn = splitext(cover)
    imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
    fullsize = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}{extn}')
    thumb = cover
    if path_isfile(imgfile):
        thumb = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
    else:
        imgthumb = createthumb(os.path.join(DIRS.CACHEDIR, cover[6:]), 200, False)
        if imgthumb:
            thumb = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
    return thumb, f"cache/{fullsize[len(DIRS.CACHEDIR):].lstrip(os.sep)}"


def update_calibre_cover(issue):
    """ Give an issue in Calibre the cover in its CoverFile """
    logger = logging.getLogger(__name__)
    calibre_id = get_calibre_id(issue)
    if calibre_id:
        res, err, rc = calibredb('set_metadata', ['--field', f'cover:{issue["CoverFile"]}'], [calibre_id])
        logger.debug(f"Update result: {res} [{err}] {rc}")


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
