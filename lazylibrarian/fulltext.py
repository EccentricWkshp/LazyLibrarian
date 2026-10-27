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

""" The words in issues, to search inside them: each page's text of a PDF, each chapter's of an
EPUB, kept in an SQLite full-text index of its own, fulltext.db in the data folder, so the library's
database and its backups stay small and the index can be made again at any time """

import contextlib
import logging
import os
import posixpath
import re
import sqlite3
import threading
import zipfile
from html import unescape
from urllib.parse import unquote

from lazylibrarian import pages
from lazylibrarian.filesystem import DIRS, splitext, syspath

# one writer at a time, pdfium has a lock of its own
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(DIRS.DATADIR, 'fulltext.db')


def connect() -> sqlite3.Connection:
    """ The index, made when it isn't there. With FTS5 the pages are a full-text table, without it a
    plain one searched with LIKE """
    db = sqlite3.connect(syspath(_path()), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS indexed (Kind TEXT, ItemID TEXT, Path TEXT, MTime REAL, Pages INTEGER, '
               'PRIMARY KEY (Kind, ItemID))')
    try:
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS pagetext USING fts5(Kind UNINDEXED, ItemID UNINDEXED, '
                   "Page UNINDEXED, Text, tokenize='unicode61 remove_diacritics 2')")
    except sqlite3.OperationalError:
        db.execute('CREATE TABLE IF NOT EXISTS pagetext (Kind TEXT, ItemID TEXT, Page INTEGER, Text TEXT)')
    return db


def has_fts(db: sqlite3.Connection) -> bool:
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='pagetext'").fetchone()
    return bool(row) and 'fts5' in (row['sql'] or '').lower()


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def pdf_text(path) -> list[str]:
    """ Each page's text of a PDF """
    if not pages.pdfium:
        return []
    found = []
    with pages._pdfium_lock:
        pdf = pages.pdfium.PdfDocument(syspath(path))
        try:
            for number in range(len(pdf)):
                page = pdf[number]
                textpage = page.get_textpage()
                found.append(_clean(textpage.get_text_range()))
                textpage.close()
                page.close()
        finally:
            pdf.close()
    return found


def epub_text(path) -> list[str]:
    """ Each chapter's text of an EPUB, in reading order """
    found = []
    with zipfile.ZipFile(syspath(path)) as epub:
        name, opf = pages.epub_package(epub)
        folder = posixpath.dirname(name)
        items = {el.get('id'): el.get('href') for el in opf.iter() if el.tag.endswith('}item') or el.tag == 'item'}
        for ref in (el for el in opf.iter() if el.tag.endswith('itemref')):
            href = items.get(ref.get('idref'))
            if not href:
                continue
            with contextlib.suppress(KeyError):
                html = epub.read(posixpath.normpath(posixpath.join(folder, unquote(href)))).decode('utf-8', 'ignore')
                body = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', html)
                found.append(_clean(unescape(re.sub(r'<[^>]+>', ' ', body))))
    return found


def text_of(path) -> list[str]:
    extn = splitext(str(path))[1].lower()
    if extn == '.pdf':
        return pdf_text(path)
    if extn == '.epub':
        return epub_text(path)
    return []


def index_item(kind: str, item_id: str, path: str, db: sqlite3.Connection | None = None) -> int:
    """ Put an item's words in the index, again when its file changed. Returns its pages indexed """
    own = db is None
    db = db or connect()
    try:
        mtime = os.path.getmtime(syspath(path))
        row = db.execute('SELECT Path, MTime, Pages FROM indexed WHERE Kind=? AND ItemID=?', (kind, item_id)).fetchone()
        if row and row['Path'] == path and row['MTime'] == mtime:
            return row['Pages']
        try:
            texts = text_of(path)
        except Exception as why:
            logging.getLogger(__name__).warning(f"Can't read the words of {path}: {type(why).__name__} {why}")
            texts = []
        with _lock:
            db.execute('DELETE FROM pagetext WHERE Kind=? AND ItemID=?', (kind, item_id))
            db.executemany('INSERT INTO pagetext (Kind, ItemID, Page, Text) VALUES (?,?,?,?)',
                           [(kind, item_id, number, text) for number, text in enumerate(texts, start=1) if text])
            db.execute('INSERT OR REPLACE INTO indexed (Kind, ItemID, Path, MTime, Pages) VALUES (?,?,?,?,?)',
                       (kind, item_id, path, mtime, len(texts)))
            db.commit()
        return len(texts)
    finally:
        if own:
            db.close()


def forget(kind: str, keep: set[str], db: sqlite3.Connection) -> int:
    """ Take out the items of a kind that aren't in keep. Returns how many """
    gone = [row['ItemID'] for row in db.execute('SELECT ItemID FROM indexed WHERE Kind=?', (kind,))
            if row['ItemID'] not in keep]
    with _lock:
        for item_id in gone:
            db.execute('DELETE FROM pagetext WHERE Kind=? AND ItemID=?', (kind, item_id))
            db.execute('DELETE FROM indexed WHERE Kind=? AND ItemID=?', (kind, item_id))
        db.commit()
    return len(gone)


def _fts_query(words: str) -> str:
    """ Words as an FTS5 query: each one a quoted term, a last one as a prefix, "a phrase" kept """
    phrases = re.findall(r'"([^"]+)"', words)
    rest = re.sub(r'"[^"]*"', ' ', words)
    terms = [f'"{phrase}"' for phrase in phrases] + [f'"{word}"' for word in re.findall(r'\w+', rest)]
    if terms and not words.rstrip().endswith('"') and terms[-1].strip('"').isalnum():
        terms[-1] += '*'
    return ' '.join(terms)


def search(words: str, kind: str = 'issue', limit: int = 100) -> list[dict]:
    """ The pages with these words, best first: each its item, page and a snippet with the words
    marked by [ and ] """
    words = (words or '').strip()
    if not words:
        return []
    db = connect()
    try:
        if has_fts(db):
            query = _fts_query(words)
            if not query:
                return []
            rows = db.execute("SELECT ItemID, Page, snippet(pagetext, 3, '[', ']', '…', 16) AS Snippet FROM pagetext "
                              "WHERE pagetext MATCH ? AND Kind=? ORDER BY rank LIMIT ?", (query, kind, limit))
        else:
            rows = db.execute("SELECT ItemID, Page, substr(Text, 1, 200) AS Snippet FROM pagetext WHERE Kind=? AND "
                              "Text LIKE ? LIMIT ?", (kind, f'%{words}%', limit))
        return [{'item_id': row['ItemID'], 'page': row['Page'], 'snippet': row['Snippet']} for row in rows]
    finally:
        db.close()


def stats(kind: str = 'issue') -> dict:
    """ How many items of a kind are indexed, and with how many pages """
    db = connect()
    try:
        row = db.execute('SELECT COUNT(*) AS Items, IFNULL(SUM(Pages), 0) AS Pages FROM indexed WHERE Kind=?',
                         (kind,)).fetchone()
        return {'items': row['Items'], 'pages': row['Pages']}
    finally:
        db.close()
