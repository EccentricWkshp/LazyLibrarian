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

""" The owner account: its settings and subscriptions """

from lazylibrarian import database


def send_to(userid) -> str:
    """ The address the user's books are emailed to, empty if none """
    if not userid:
        return ''
    db = database.DBConnection()
    try:
        res = db.match('SELECT SendTo from users where UserID=?', (userid,))
    finally:
        db.close()
    return res['SendTo'] if res and res['SendTo'] else ''
