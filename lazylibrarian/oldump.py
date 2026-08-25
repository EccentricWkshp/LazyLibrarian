import gzip
import json
import logging
import os
import sqlite3
import time

from lazylibrarian import database
from lazylibrarian.common import get_user_agent
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import thread_name

logger = logging.getLogger(__name__)

# How often (in downloaded bytes) to log download progress.
DOWNLOAD_PROGRESS_STEP = 200 * 1024 * 1024
# How often (in indexed rows) to log indexing progress.
INDEX_PROGRESS_STEP = 500000

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
    this stage). If a `local_path.part` staging file is left over from a run that was
    interrupted mid-download, resumes it with an HTTP Range request instead of
    restarting from byte zero - these dumps are several GB compressed, and a plain
    restart after every interruption (network blip, container restart, OOM) could
    make the download never finish on a slow or flaky connection. Falls back to a
    full restart if the server doesn't honour the Range request (returns 200 instead
    of 206) or the partial file turns out larger than the current remote copy (a new
    dump was published mid-download). Returns True if local_path ends up complete and
    usable."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': get_user_agent(configured=False)})
    try:
        with urllib.request.urlopen(req) as resp:
            remote_size = int(resp.headers.get('Content-Length', 0))
    except Exception as e:
        logger.warning(f"Unable to check remote size for {url}: {e}")
        remote_size = 0

    if remote_size and os.path.exists(local_path) and os.path.getsize(local_path) == remote_size:
        logger.info(f"{os.path.basename(local_path)} already fully downloaded ({remote_size} bytes), skipping")
        return True

    partial_path = f"{local_path}.part"
    resume_from = 0
    mode = 'wb'
    if os.path.exists(partial_path):
        partial_size = os.path.getsize(partial_path)
        if remote_size and partial_size < remote_size:
            resume_from = partial_size
            mode = 'ab'
        elif partial_size:
            # Either no remote_size to compare against, or the partial file is already
            # as big as (or bigger than) the current remote copy - can't trust it, start over.
            os.remove(partial_path)

    headers = {'User-Agent': get_user_agent(configured=False)}
    if resume_from:
        headers['Range'] = f'bytes={resume_from}-'
        logger.info(f"Resuming {os.path.basename(local_path)} from byte {resume_from} "
                   f"({resume_from * 100 // remote_size}% already downloaded)")
    else:
        logger.info(f"Downloading {url} -> {local_path}...")

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        if resume_from and e.code == 416:
            # Range not satisfiable - our partial file is already complete/stale, restart clean.
            logger.warning(f"Server rejected resume of {os.path.basename(local_path)}, restarting from scratch")
            os.remove(partial_path)
            return download_dump_file(url, local_path)
        raise

    with resp:
        if resume_from and resp.status != 206:
            # Server ignored the Range header and is sending the whole file again - can't
            # append what we already have on top of that, so restart the file cleanly.
            logger.warning(f"Server didn't honour resume for {os.path.basename(local_path)} "
                           f"(status {resp.status}), restarting from scratch")
            resume_from = 0
            mode = 'wb'
        downloaded = resume_from
        next_log_at = downloaded + DOWNLOAD_PROGRESS_STEP
        with open(partial_path, mode) as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_log_at:
                    if remote_size:
                        logger.info(f"{os.path.basename(local_path)}: {downloaded // (1024 * 1024)} MB "
                                   f"({downloaded * 100 // remote_size}%)")
                    else:
                        logger.info(f"{os.path.basename(local_path)}: {downloaded // (1024 * 1024)} MB")
                    next_log_at = downloaded + DOWNLOAD_PROGRESS_STEP

    downloaded_size = os.path.getsize(partial_path)
    if remote_size and downloaded_size != remote_size:
        logger.error(f"Download of {url} incomplete: got {downloaded_size} bytes, expected {remote_size} "
                     f"- left as {partial_path} to resume next run")
        return False

    os.replace(partial_path, local_path)
    logger.info(f"{os.path.basename(local_path)} download complete ({downloaded_size} bytes)")
    return True


def update_openlibrary_dump():
    """Scheduled (or manually-triggered, see webServe.force_openlibrary_dump) task to
    download and stream OpenLibrary author & work dumps into local SQLite database.
    Safe to interrupt and re-run: already-complete downloads are skipped, an
    interrupted download resumes via HTTP Range rather than restarting, and indexing
    uses INSERT OR REPLACE so re-processing a file is idempotent."""
    if not CONFIG['OL_USE_DUMP']:
        logger.debug("OpenLibrary local dump indexing disabled in configuration")
        return

    incoming_threadname = thread_name()
    thread_name('OLDUMPUPDATE')
    dump_dir = get_dump_dir()
    db_path = get_dump_db_path()
    logger.info(f"Starting OpenLibrary Bulk Dump Sync -> {db_path}")

    jobdb = database.DBConnection()
    logger.debug(f"Storing start time for {thread_name()}")
    jobdb.upsert("jobs", {"Start": time.time()}, {"Name": thread_name()})

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
        indexed = 0
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
                    indexed += len(batch)
                    batch = []
                    if indexed % INDEX_PROGRESS_STEP < 10000:
                        logger.info(f"Indexed {indexed} authors so far...")
        if batch:
            cur.executemany("INSERT OR REPLACE INTO ol_authors (author_id, author_name) VALUES (?, ?)", batch)
            conn.commit()
            indexed += len(batch)
        logger.info(f"Indexed {indexed} authors total")

        # 2. Ingest Works Dump
        works_gz = os.path.join(dump_dir, 'ol_dump_works.txt.gz')
        if not download_dump_file(WORKS_DUMP_URL, works_gz):
            logger.error("Aborting OpenLibrary dump sync: works download failed or incomplete")
            return

        logger.info("Indexing OpenLibrary Works into local database...")
        batch = []
        indexed = 0
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
                    indexed += len(batch)
                    batch = []
                    if indexed % INDEX_PROGRESS_STEP < 10000:
                        logger.info(f"Indexed {indexed} works so far...")
        if batch:
            cur.executemany("INSERT OR REPLACE INTO ol_works (work_id, author_id, title, first_publish_year, isbn, cover_i) VALUES (?, ?, ?, ?, ?, ?)", batch)
            conn.commit()
            indexed += len(batch)
        logger.info(f"Indexed {indexed} works total")

        logger.info("OpenLibrary Bulk Dump indexing complete successfully.")
    except Exception as e:
        logger.error(f"Error updating OpenLibrary bulk dump: {e}")
    finally:
        if conn:
            conn.close()
        logger.debug(f"Storing finish time for {thread_name()}")
        jobdb.upsert("jobs", {"Finish": time.time()}, {"Name": thread_name()})
        jobdb.close()
        thread_name(incoming_threadname)

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
