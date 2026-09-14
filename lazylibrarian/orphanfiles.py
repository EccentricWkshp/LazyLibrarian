import logging
import os

from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import book_file, get_directory


def list_orphan_books():
    logger = logging.getLogger(__name__)
    startdir = get_directory('eBook')
    db = database.DBConnection()
    logger.debug(f"Counting directories: {startdir}")
    book_folders = []
    for rootdir, dirnames, _filenames in os.walk(startdir):
        for directory in dirnames:
            # prevent magazine being scanned
            c = directory[0]
            ignorefile = '.ll_ignore'
            dirname = os.path.join(rootdir, directory)
            if c in ["_", "."]:
                logger.debug(f'Skipping {dirname}')
                # ignore directories containing this special file
            elif os.path.exists(os.path.join(rootdir, directory, ignorefile)):
                logger.debug(f'Found .ll_ignore file in {dirname}')
            elif book_file(dirname, booktype='ebook', config=CONFIG, recurse=False):
                book_folders.append(dirname)
    logger.debug(f"Found {len(book_folders)} directories containing books")

    missing = []

    for folder in book_folders:
        book = os.path.splitext(os.path.basename(book_file(folder, booktype='ebook', config=CONFIG, recurse=False)))[0]
        match = db.match("select * from books where bookfile like ?", (f"%{book}%",))
        if not match and ' - ' in book:  # might be author - title
            book = book.split(' - ')[1]
            match = db.match("select * from books where bookfile like ?", (f"%{book}%",))
        if not match:
            missing.append(book)
    logger.info(f"Found: {len(book_folders) - len(missing)},  Not found: {len(missing)}")
    return missing


def list_orphan_audio():
    logger = logging.getLogger(__name__)
    startdir = get_directory('Audio')
    db = database.DBConnection()
    logger.debug(f"Counting directories: {startdir}")
    book_folders = []
    for rootdir, dirnames, _filenames in os.walk(startdir):
        for directory in dirnames:
            # prevent magazine being scanned
            c = directory[0]
            ignorefile = '.ll_ignore'
            dirname = os.path.join(rootdir, directory)
            if c in ["_", "."]:
                logger.debug(f'Skipping {dirname}')
                # ignore directories containing this special file
            elif os.path.exists(os.path.join(rootdir, directory, ignorefile)):
                logger.debug(f'Found .ll_ignore file in {dirname}')
            elif book_file(dirname, booktype='audio', config=CONFIG, recurse=False):
                book_folders.append(dirname)
    logger.debug(f"Found {len(book_folders)} directories containing audiobooks")

    missing = []

    for folder in book_folders:
        book = os.path.splitext(os.path.basename(book_file(folder, booktype='audio', config=CONFIG, recurse=False)))[0]
        match = db.match("select * from books where audiofile like ?", (f"%{book}%",))
        if not match and ' - ' in book:  # might be author - title
            book = book.split(' - ')[1]
            match = db.match("select * from books where audiofile like ?", (f"%{book}%",))
        if not match:
            missing.append(book)
    logger.info(f"Found: {len(book_folders) - len(missing)},  Not found: {len(missing)}")
    return missing
