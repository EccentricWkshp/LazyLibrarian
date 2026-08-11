import os
import gzip
import json
import shutil
import sqlite3
import time
import logging
from lazylibrarian.config2 import CONFIG
from lazylibrarian import database
from lazylibrarian.filesystem import DIRS

logger = logging.getLogger(__name__)

AUTHORS_DUMP_URL = "https://openlibrary.org/data/ol_dump_authors_latest.txt.gz"
WORKS_DUMP_URL = "https://openlibrary.org/data/ol_dump_works_latest.txt.gz"

def get_dump_dir():
    dump_dir = CONFIG['OL_DUMP_DIR']
    if not dump_dir:
        cache_base = DIRS.CACHEDIR if DIRS.CACHEDIR else os.path.join(DIRS.DATADIR, 'cache')
        dump_dir = os.path.join(cache_base, 'openlibrary_dump')
    if not os.path.exists(dump_dir):
        os.makedirs(dump_dir, exist_ok=True)
    return dump_dir

def get_dump_db_path():
    return os.path.join(get_dump_dir(), 'ol_catalog.sqlite3')

def init_dump_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ol_authors (
            author_id TEXT PRIMARY KEY,
            author_name TEXT COLLATE NOCASE
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ol_works (
            work_id TEXT PRIMARY KEY,
            author_id TEXT,
            title TEXT COLLATE NOCASE,
            first_publish_year TEXT,
            isbn TEXT,
            cover_i TEXT,
            FOREIGN KEY(author_id) REFERENCES ol_authors(author_id)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ol_authors_name ON ol_authors(author_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ol_works_author ON ol_works(author_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ol_works_title ON ol_works(title);")
    conn.commit()
    return conn

def download_dump_file(url, local_path):
    """Download url to local_path, skipping the download if a same-size file already
    exists (e.g. left over from a previous run that got interrupted after completing
    this stage). Returns True if local_path ends up complete and usable."""
    import urllib.request

    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'LazyLibrarian/1.0'})
    try:
        with urllib.request.urlopen(req) as resp:
            remote_size = int(resp.headers.get('Content-Length', 0))
    except Exception as e:
        logger.warning(f"Unable to check remote size for {url}: {e}")
        remote_size = 0

    if remote_size and os.path.exists(local_path) and os.path.getsize(local_path) == remote_size:
        logger.info(f"{os.path.basename(local_path)} already fully downloaded ({remote_size} bytes), skipping")
        return True

    logger.info(f"Downloading {url} -> {local_path}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'LazyLibrarian/1.0'})
    partial_path = f"{local_path}.part"
    with urllib.request.urlopen(req) as resp, open(partial_path, 'wb') as out:
        shutil.copyfileobj(resp, out, length=1024 * 1024)

    downloaded_size = os.path.getsize(partial_path)
    if remote_size and downloaded_size != remote_size:
        logger.error(f"Download of {url} incomplete: got {downloaded_size} bytes, expected {remote_size}")
        os.remove(partial_path)
        return False

    os.replace(partial_path, local_path)
    return True


def update_openlibrary_dump():
    """Scheduled task to download and stream OpenLibrary author & work dumps into local SQLite database.
    Safe to interrupt and re-run: already-complete downloads are skipped, and indexing uses
    INSERT OR REPLACE so re-processing a file is idempotent."""
    if not CONFIG['OL_USE_DUMP']:
        logger.debug("OpenLibrary local dump indexing disabled in configuration")
        return

    dump_dir = get_dump_dir()
    db_path = get_dump_db_path()
    logger.info(f"Starting OpenLibrary Bulk Dump Sync -> {db_path}")

    conn = None
    try:
        conn = init_dump_db(db_path)
        cur = conn.cursor()

        # 1. Ingest Authors Dump
        authors_gz = os.path.join(dump_dir, 'ol_dump_authors.txt.gz')
        if not download_dump_file(AUTHORS_DUMP_URL, authors_gz):
            logger.error("Aborting OpenLibrary dump sync: authors download failed or incomplete")
            return

        logger.info("Indexing OpenLibrary Authors into local database...")
        batch = []
        with gzip.open(authors_gz, 'rt', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 5:
                    key = parts[1].split('/')[-1]
                    try:
                        data = json.loads(parts[4])
                        name = data.get('name', '')
                        if key and name:
                            batch.append((key, name))
                    except Exception:
                        pass
                if len(batch) >= 10000:
                    cur.executemany("INSERT OR REPLACE INTO ol_authors (author_id, author_name) VALUES (?, ?)", batch)
                    conn.commit()
                    batch = []
        if batch:
            cur.executemany("INSERT OR REPLACE INTO ol_authors (author_id, author_name) VALUES (?, ?)", batch)
            conn.commit()

        # 2. Ingest Works Dump
        works_gz = os.path.join(dump_dir, 'ol_dump_works.txt.gz')
        if not download_dump_file(WORKS_DUMP_URL, works_gz):
            logger.error("Aborting OpenLibrary dump sync: works download failed or incomplete")
            return

        logger.info("Indexing OpenLibrary Works into local database...")
        batch = []
        with gzip.open(works_gz, 'rt', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 5:
                    key = parts[1].split('/')[-1]
                    try:
                        data = json.loads(parts[4])
                        title = data.get('title', '')
                        authors = data.get('authors', [])
                        author_id = ''
                        if authors:
                            a_ref = authors[0].get('author', {}).get('key', '')
                            if a_ref:
                                author_id = a_ref.split('/')[-1]
                        covers = data.get('covers', [])
                        cover_i = str(covers[0]) if covers else ''
                        first_publish_date = str(data.get('created', {}).get('value', ''))[:4]
                        if key and title and author_id:
                            batch.append((key, author_id, title, first_publish_date, '', cover_i))
                    except Exception:
                        pass
                if len(batch) >= 10000:
                    cur.executemany("INSERT OR REPLACE INTO ol_works (work_id, author_id, title, first_publish_year, isbn, cover_i) VALUES (?, ?, ?, ?, ?, ?)", batch)
                    conn.commit()
                    batch = []
        if batch:
            cur.executemany("INSERT OR REPLACE INTO ol_works (work_id, author_id, title, first_publish_year, isbn, cover_i) VALUES (?, ?, ?, ?, ?, ?)", batch)
            conn.commit()

        logger.info("OpenLibrary Bulk Dump indexing complete successfully.")
    except Exception as e:
        logger.error(f"Error updating OpenLibrary bulk dump: {e}")
    finally:
        if conn:
            conn.close()

def query_local_dump_author(author_name):
    """Search local dump database for author ID by name."""
    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT author_id, author_name FROM ol_authors WHERE author_name = ? COLLATE NOCASE", (author_name,))
        res = cur.fetchone()
        conn.close()
        if res:
            return {'authorid': res[0], 'authorname': res[1]}
    except Exception as e:
        logger.error(f"Local dump author query error: {e}")
    return None

def query_local_dump_books(author_id):
    """Query local dump database for all works belonging to an author ID."""
    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return []
    docs = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT work_id, title, first_publish_year, cover_i FROM ol_works WHERE author_id = ?", (author_id,))
        rows = cur.fetchall()
        conn.close()
        for r in rows:
            docs.append({
                'key': f"/works/{r[0]}",
                'title': r[1],
                'first_publish_year': r[2],
                'cover_i': r[3],
                'author_key': [author_id]
            })
    except Exception as e:
        logger.error(f"Local dump books query error: {e}")
    return docs
