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

""" The cover walls: recent issues, books and audiobooks, and authors, with their thumbnails """

from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int
from lazylibrarian.services.files import cover_thumbnail

NO_COVER = 'images/nocover.jpg'


def thumbnail(cover) -> str:
    """ The wall picture for a cover """
    covers = cover_thumbnail(cover)
    return covers[0] if covers else NO_COVER


def limited(rows) -> tuple[list, bool]:
    """ The first MAX_WALL rows as dicts, and whether there were more """
    maxcount = CONFIG.get_int('MAX_WALL')
    if maxcount and len(rows) > maxcount:
        return [dict(r) for r in rows[:maxcount]], True
    return [dict(r) for r in rows], False


def select(cmd: str, args=None) -> list:
    db = database.DBConnection()
    try:
        return db.select(cmd, args)
    finally:
        db.close()


def magazine_wall(title: str = '') -> tuple[list, bool]:
    """ The most recently acquired issues, of one magazine if title is given, and whether there were more """
    cmd = "SELECT IssueFile,IssueID,IssueDate,Title,Cover from issues"
    args = None
    if title:
        cmd += " WHERE Title=?"
        args = (title,)
    issues, more = limited(select(cmd + " order by IssueAcquired DESC", args))
    for issue in issues:
        issue['Cover'] = thumbnail(issue.get('Cover'))
        issue['Title'] = issue['Title'].replace('&amp;', '&')
    return issues, more


def comic_wall(comicid=None) -> tuple[list, bool]:
    """ The most recently acquired comic issues, of one comic if comicid is given, and whether there were more """
    cmd = ("SELECT IssueFile,IssueID,comics.ComicID,Title,Cover from comicissues,comics WHERE "
           "comics.ComicID = comicissues.ComicID")
    args = None
    if comicid:
        cmd += " AND comics.ComicID=?"
        args = (comicid,)
    issues, more = limited(select(cmd + " order by IssueAcquired DESC", args))
    for issue in issues:
        issue['Cover'] = thumbnail(issue.get('Cover'))
    return issues, more


def book_wall(downloaded: bool = False) -> tuple[list, bool]:
    """ The most recently added books that aren't ignored, or the most recently downloaded ones,
        and whether there were more """
    if downloaded:
        cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status='Open' order by BookLibrary DESC"
    else:
        cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status != 'Ignored' order by BookAdded DESC"
    books, more = limited(select(cmd))
    for book in books:
        if not book['BookLink']:
            book['BookLink'] = ''
        elif book['BookLink'].startswith('/works/OL'):
            book['BookLink'] = CONFIG['OL_URL'] + book['BookLink']
        book['BookImg'] = thumbnail(book.get('BookImg'))
    return books, more


def audio_wall() -> tuple[list, bool]:
    """ The most recently downloaded audiobooks, and whether there were more """
    books, more = limited(select('SELECT AudioFile,BookImg,BookID,BookName from books '
                                 'where AudioStatus="Open" order by AudioLibrary DESC'))
    for book in books:
        book['BookImg'] = thumbnail(book.get('BookImg'))
    return books, more


def author_wall(active: bool = True) -> list:
    """ The Active and Wanted authors, or the others, by name """
    cmd = "SELECT Status,AuthorImg,AuthorID,AuthorName,HaveBooks,TotalBooks from authors "
    if active:
        cmd += "where Status='Active' or Status='Wanted' order by AuthorName ASC"
    else:
        cmd += "where Status !='Active' and Status != 'Wanted' order by AuthorName ASC"
    authors = [dict(r) for r in select(cmd)]
    for author in authors:
        author['AuthorImg'] = thumbnail(author.get('AuthorImg'))
    return authors


def change_columns(count: str) -> int:
    """ One more (up) or fewer (down) columns on the walls, between 1 and 13. Returns how many there are now """
    columns = check_int(CONFIG.get_int('WALL_COLUMNS'), 6)
    if count == 'up' and columns <= 12:
        columns += 1
    elif count == 'down' and columns > 1:
        columns -= 1
    CONFIG.set_int('WALL_COLUMNS', columns)
    return columns
