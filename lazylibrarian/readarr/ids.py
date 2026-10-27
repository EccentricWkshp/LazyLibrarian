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

""" The whole numbers Readarr's API gives authors and books. Ours are text (OL37861787W, 62983544),
so each gets a number of its own in the apiids table the first time it's given out, and keeps it.
SQLite's rowid can't be used: a VACUUM may number a table's rows again """

AUTHOR = 'author'
# a book as an eBook and as an audiobook are two, as Chaptarr has a row for each format
BOOK = 'book'
AUDIOBOOK = 'audiobook'


def api_ids(db, kind: str, item_ids) -> dict[str, int]:
    """ The numbers of these authors or books (kind), by their ids, given now to any without one """
    item_ids = [str(item_id) for item_id in item_ids if item_id]
    if not item_ids:
        return {}
    known = {row['ItemID']: row['ID'] for row in db.select('SELECT ID, ItemID FROM apiids WHERE Kind=?', (kind,))}
    new = [item_id for item_id in dict.fromkeys(item_ids) if item_id not in known]
    for item_id in new:
        db.action('INSERT OR IGNORE INTO apiids (Kind, ItemID) VALUES (?, ?)', (kind, item_id))
    if new:
        known.update({row['ItemID']: row['ID'] for row in db.select(
            f"SELECT ID, ItemID FROM apiids WHERE Kind=? AND ItemID IN ({','.join('?' * len(new))})",
            (kind, *new))})
    return {item_id: known[item_id] for item_id in item_ids if item_id in known}


def api_id(db, kind: str, item_id) -> int:
    return api_ids(db, kind, [item_id]).get(str(item_id), 0)


def item_id(db, kind: str, number) -> str:
    """ The author's or book's own id for a number, '' when no author or book has it """
    row = db.match('SELECT ItemID FROM apiids WHERE Kind=? AND ID=?', (kind, number))
    return row['ItemID'] if row else ''
