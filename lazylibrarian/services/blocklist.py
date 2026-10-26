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

""" The blocklist, like Sonarr's: releases that failed, which the searches won't take again while
Settings has BLACKLIST_FAILED on. A download goes on it when it is marked failed, however that
happens, by the database's triggers (dbupgrade.BLOCKLIST_TRIGGERS). It is kept apart from the
history, so taking a release off it leaves its history, and clearing history leaves it blocked """

import logging

from lazylibrarian import database
from lazylibrarian.services import InvalidRequestError
from lazylibrarian.services.history import PROTOCOLS, download_target, indexer_name, size_bytes
from lazylibrarian.services.paging import Page, page_of

SORTS = ('date', 'title', 'source_title', 'indexer')


def find(db, url: str, title: str, provider: str, irc: bool = False) -> dict | None:
    """ The blocklist entry for a release, by its link, or by its title at the same provider when
    the link changed. An IRC bot's releases share a link, so they're told apart by title """
    cmd, args = 'SELECT rowid,* FROM blocklist WHERE NZBurl=?', (url,)
    if irc:
        cmd, args = f'{cmd} AND NZBtitle=?', (url, title)
    row = db.match(cmd, args)
    if not row and provider and title:
        row = db.match('SELECT rowid,* FROM blocklist WHERE NZBprov=? AND NZBtitle=?', (provider, title))
    return dict(row) if row else None


def list_blocklist(search: str = '', sort: str = 'date', descending: bool = True, offset: int = 0,
                   limit: int | None = None) -> Page:
    """ The blocked releases with what each was for, the most recent first """
    if sort not in SORTS:
        raise InvalidRequestError(f"Sort by one of {', '.join(SORTS)}")
    db = database.DBConnection()
    try:
        rows = db.select("SELECT blocklist.rowid AS Id,blocklist.*,BookName,AuthorName,books.AuthorID AS AuthorID "
                         "FROM blocklist LEFT JOIN books ON blocklist.BookID=books.BookID "
                         "LEFT JOIN authors ON books.AuthorID=authors.AuthorID")
        records = []
        for row in rows:
            record = download_target(db, row, book=row)
            record.update(id=row['Id'], source_title=row['NZBtitle'] or '', indexer=indexer_name(row['NZBprov']),
                          protocol=PROTOCOLS.get(row['NZBmode'], row['NZBmode'] or ''),
                          size=size_bytes(row['NZBsize']), date=row['Date'] or '', message=row['Message'] or '')
            records.append(record)
    finally:
        db.close()
    return page_of(records, search=search, search_fields=('title', 'author', 'source_title', 'indexer', 'issue'),
                   sort=sort, descending=descending, natural=sort == 'title', offset=offset, limit=limit)


def remove(ids: list[int]) -> int:
    """ Take releases off the blocklist, so the searches can take them again. Returns how many were """
    if not ids:
        raise InvalidRequestError('Choose what to take off the blocklist')
    db = database.DBConnection()
    try:
        removed = 0
        for item_id in ids:
            row = db.match('SELECT NZBtitle FROM blocklist WHERE rowid=?', (item_id,))
            if row:
                db.action('DELETE FROM blocklist WHERE rowid=?', (item_id,))
                logging.getLogger(__name__).info(f"Removed {row['NZBtitle']} from the blocklist")
                removed += 1
    finally:
        db.close()
    return removed


def clear() -> int:
    """ Empty the blocklist, returns how many releases were on it """
    db = database.DBConnection()
    try:
        count = db.match('SELECT COUNT(*) AS counter FROM blocklist')['counter']
        db.action('DELETE FROM blocklist')
    finally:
        db.close()
    logging.getLogger(__name__).info(f"Cleared the blocklist of {count} releases")
    return count
