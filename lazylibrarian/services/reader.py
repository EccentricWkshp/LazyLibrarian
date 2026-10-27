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

""" Reading in the browser: the file of an eBook, magazine issue or comic issue, to open in the
browser or download, its pages as pictures, and sending it to the owner's devices by email """

from lazylibrarian import database, pages
from lazylibrarian.filesystem import path_isfile, splitext
from lazylibrarian.services import InvalidRequestError, NotFoundError, delivery, users

KINDS = ('book', 'issue', 'comic')
# how the reader shows a format: the browser's own PDF viewer, pages as pictures, or the EPUB reader
READERS = {'pdf': 'pdf', 'cbz': 'pages', 'cbr': 'pages', 'cb7': 'pages', 'epub': 'epub'}


def _owner():
    from lazylibrarian.auth import owner_id  # noqa: PLC0415, auth imports the services
    return owner_id()


def item_file(kind: str, item_id: str, fmt: str = '') -> dict:
    """ The file of an eBook (in format fmt, or the one the owner prefers, else the first there),
    a magazine issue, or a comic issue (comicid_issueid): its path, the name to give it, its title
    and format. NotFoundError if there's no such item or file """
    if kind not in KINDS:
        raise InvalidRequestError(f"The kind is one of {', '.join(KINDS)}")
    db = database.DBConnection()
    try:
        if kind == 'book':
            row = db.match('SELECT BookFile, BookName FROM books WHERE BookID=?', (item_id,))
            if not row or not row['BookFile'] or not path_isfile(row['BookFile']):
                raise NotFoundError(f"No eBook file for {item_id}")
            formats = delivery.ebook_formats(row['BookFile'])
            if fmt and fmt not in formats:
                raise NotFoundError(f"{row['BookName']} isn't there as {fmt}, only {', '.join(formats)}")
            preferred = users.preferred_type(_owner())
            fmt = fmt or (preferred if preferred in formats else formats[0] if formats else '')
            path = f"{splitext(row['BookFile'])[0]}.{fmt}" if fmt else row['BookFile']
            title = row['BookName']
        elif kind == 'issue':
            row = db.match('SELECT Title, IssueDate, IssueFile FROM issues WHERE IssueID=?', (item_id,))
            if not row or not row['IssueFile'] or not path_isfile(row['IssueFile']):
                raise NotFoundError(f"No file for issue {item_id}")
            path, title = row['IssueFile'], f"{row['Title']} {row['IssueDate']}"
            formats = []
        else:
            comic_id, _, issue_id = item_id.partition('_')
            row = db.match('SELECT Title, IssueFile FROM comics JOIN comicissues ON comics.ComicID=comicissues.ComicID '
                           'WHERE comics.ComicID=? AND IssueID=?', (comic_id, issue_id))
            if not row or not row['IssueFile'] or not path_isfile(row['IssueFile']):
                raise NotFoundError(f"No file for comic issue {item_id}")
            path, title = row['IssueFile'], f"{row['Title']} {issue_id}"
            formats = []
    finally:
        db.close()
    extension = splitext(path)[1]
    return {'path': path, 'name': f"{title}{extension}", 'title': title, 'format': extension.lstrip('.').lower(),
            'formats': formats}


def open_file(kind: str, item_id: str, fmt: str = '') -> dict:
    """ The item's file, as item_file, remembered as opened as the old pages do """
    found = item_file(kind, item_id, fmt)
    if _owner():
        delivery.record_sent(_owner(), 'Open', found['name'])
    return found


def reading(kind: str, item_id: str, fmt: str = '') -> dict:
    """ What the reader needs: the item's title and format, the other formats it's there in, how to
    show it (pdf, pages or epub, empty when it can't be read in the browser) and how many pages it
    has, when it's a PDF or comic archive that pages can be drawn from """
    found = item_file(kind, item_id, fmt)
    return {'title': found['title'], 'format': found['format'], 'formats': found['formats'],
            'reader': READERS.get(found['format'], ''),
            'pages': pages.page_count(found['path']) if pages.is_paged(found['path']) else 0}


def page(kind: str, item_id: str, number: int, width: int = 0) -> bytes:
    """ A page of an issue, comic or PDF eBook as a JPEG, NotFoundError if there's no such page """
    found = item_file(kind, item_id)
    image = pages.page_image(found['path'], number, min(max(width, 0), 3000))
    if not image:
        raise NotFoundError(f"{found['title']} has no page {number}")
    return image


def send(kind: str, item_id: str, fmt: str = '') -> str:
    """ Email an item's file to the owner's send-to addresses, as Send to Device. Returns what
    happened, InvalidRequestError when it couldn't be sent """
    found = item_file(kind, item_id, fmt)
    if not users.send_to(_owner()):
        raise InvalidRequestError('There are no addresses to send to, add them in Settings, Connect')
    sent, not_sent = delivery.email_file(_owner(), found['path'], found['title'])
    if not sent:
        raise InvalidRequestError(f"Sending {found['title']} failed, see the log")
    message = f"Sent {found['title']} to {', '.join(sent)}"
    if not_sent:
        message += f", sending to {', '.join(not_sent)} failed"
    return message
