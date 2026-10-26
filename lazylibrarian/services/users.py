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

import logging
from urllib.parse import unquote_plus

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.auth import set_owner_credentials
from lazylibrarian.common import is_valid_email, pwd_check
from lazylibrarian.config2 import CONFIG, wishlist_type
from lazylibrarian.passwords import verify_password
from lazylibrarian.services import InvalidRequestError, NotFoundError

# the profile errors, worded as the translations know them
PASSWORDS_DIFFER = "Passwords do not match"
PASSWORD_TOO_WEAK = "Password must be at least 8 characters long\nand not contain spaces"


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


def preferred_type(userid) -> str:
    """ The ebook format the user would rather have, empty if they haven't said """
    if not userid:
        return ''
    db = database.DBConnection()
    try:
        res = db.match('SELECT BookType from users where UserID=?', (userid,))
    finally:
        db.close()
    return res['BookType'] or '' if res else ''


def valid_ui_lang(value: str) -> bool:
    """ Empty (use the global setting), auto, or a language we have a translation for """
    return value in ('', i18n.AUTO) or value in i18n.available_languages()


def plain_text(value, tokens) -> bool:
    """ Is the value free of these characters, even url-decoded """
    logger = logging.getLogger(__name__)
    if not value:
        return True
    unquoted = unquote_plus(value)
    for token in tokens:
        if token in unquoted:
            logger.warning(f"Invalid value: contains {token}")
            return False
    return True


def valid_theme(theme: str) -> bool:
    """ No theme (the default), legacy or one of the bookstrap themes """
    if not theme or theme == 'legacy':
        return True
    parts = theme.split('_', 1)
    return parts[0] == 'bookstrap' and len(parts) == 2 and parts[1] in lazylibrarian.BOOKSTRAP_THEMELIST


def get_profile(userid) -> dict:
    """ The user's settings, Theme empty when there isn't one, and their subscriptions as dicts of Type,
        WantID and Name (the author, series or comic name, empty if not known) """
    db = database.DBConnection()
    try:
        user = db.match('SELECT UserName,UserID,Name,Email,SendTo,BookType,Theme,hc_id,hc_token,'
                        'CalibreRead,CalibreToRead from users where UserID=?', (userid,))
        if not user:
            raise NotFoundError(f'No user {userid}')
        subscriptions = []
        for itm in db.select('SELECT Type,WantID from subscribers WHERE UserID=?', (userid,)):
            res = None
            if itm['Type'] == 'author':
                res = db.match('SELECT AuthorName as Name from authors WHERE authorid=?', (itm['WantID'],))
            elif itm['Type'] == 'series':
                res = db.match('SELECT SeriesName as Name from series WHERE seriesid=?', (itm['WantID'],))
            elif itm['Type'] == 'comic' and itm['WantID'].count('_') == 1:
                res = db.match('SELECT Title as Name from comics WHERE comicid=?', (itm['WantID'].split('_')[0],))
            subscriptions.append({'Type': itm['Type'], 'WantID': itm['WantID'], 'Name': res['Name'] if res else ''})
    finally:
        db.close()
    user = dict(user)
    user['Theme'] = user['Theme'] or ''
    return {'user': user, 'subscriptions': subscriptions}


def update_profile(userid, changes: dict, keep_token=None) -> list[str]:
    """ Change the user's settings: username, fullname, email, theme, ui_lang, sendto, booktype, hc_token,
        password (with password2 to confirm it), calread and caltoread. Values that are missing or not
        valid are left alone. A new password logs every other session out, keep_token stays logged in.
        Returns the names of what changed. InvalidRequestError if the passwords differ or are too weak """
    logger = logging.getLogger(__name__)
    password = changes.get('password')
    if password and 'password2' in changes and password != changes['password2']:
        raise InvalidRequestError(PASSWORDS_DIFFER)
    if password and not pwd_check(password):
        raise InvalidRequestError(PASSWORD_TOO_WEAK)
    changed = []
    db = database.DBConnection()
    try:
        user = db.match('SELECT UserName,Name,Email,Password,BookType,SendTo,Theme,hc_token,ui_lang,'
                        'CalibreRead,CalibreToRead from users where UserID=?', (userid,))
        if not user:
            raise NotFoundError(f'No user {userid}')

        def change(field, column, value, valid, problem):
            if not valid:
                logger.warning(problem)
                return
            changed.append(field)
            db.action(f'UPDATE users SET {column}=? WHERE UserID=?', (value, userid))

        username = changes.get('username')
        if username and user['UserName'] != username:
            if plain_text(username, ['<', '>', '=', ':']):
                changed.append('username')
                set_owner_credentials(db, username=username)
            else:
                logger.warning("Invalid username")
        fullname = changes.get('fullname')
        if fullname and user['Name'] != fullname:
            change('name', 'Name', fullname, plain_text(fullname, ['<', '>', '=']), "Invalid fullname")
        email = changes.get('email')
        if email and user['Email'] != email:
            change('email', 'email', email, is_valid_email(email), "Invalid email")
        if 'theme' in changes and user['Theme'] != changes['theme']:
            theme = '' if changes['theme'] in ['None', 'Default', ''] else changes['theme']
            change('Theme', 'Theme', theme, valid_theme(theme), f"Invalid user theme [{theme}]")
        # profile.html doesn't send ui_lang, only the admin users page does
        if 'ui_lang' in changes and (user['UI_Lang'] or '') != changes['ui_lang']:
            change('UI_Lang', 'UI_Lang', changes['ui_lang'], valid_ui_lang(changes['ui_lang']),
                   f"Invalid UI Language [{changes['ui_lang']}]")
        if 'sendto' in changes and user['SendTo'] != changes['sendto']:
            change('sendto', 'sendto', changes['sendto'], is_valid_email(changes['sendto']), "Invalid email")
        if 'booktype' in changes and user['BookType'] != changes['booktype']:
            change('BookType', 'BookType', changes['booktype'], True, '')
        if 'hc_token' in changes and user['hc_token'] != changes['hc_token']:
            change('hc_token', 'hc_token', changes['hc_token'], plain_text(changes['hc_token'], ['<', '>', '=']),
                   "Invalid hardcopy token")
        if password and not verify_password(password, user['password']):
            changed.append('password')
            # logs out everywhere else, but not this browser
            set_owner_credentials(db, password=password, keep_token=keep_token)
        for key, column in [('calread', 'CalibreRead'), ('caltoread', 'CalibreToRead')]:
            if key in changes and (user[column] or '') != changes[key]:
                change(column, column, changes[key], plain_text(changes[key], ['<', '>', '=']), f"Invalid {column}")
    finally:
        db.close()
    return changed


def save_prefs(userid, prefs: int):
    """ Remember the user's display preferences """
    db = database.DBConnection()
    try:
        db.action('UPDATE users SET prefs=? where UserID=?', (prefs, userid))
    finally:
        db.close()


def feed_choices(userid) -> list[dict]:
    """ The wishlist feeds the user can subscribe to, as dicts of their name and whether they're subscribed """
    db = database.DBConnection()
    try:
        feeds = {f['WantID'] for f in db.select("SELECT WantID from subscribers where Type='feed' and UserID=?",
                                                (userid,))}
    finally:
        db.close()
    return [{'name': provider['DISPNAME'], 'subscribed': provider['DISPNAME'] in feeds}
            for provider in CONFIG.providers('RSS') if wishlist_type(provider['HOST'])]


def set_feeds(userid, feeds: dict) -> int:
    """ Subscribe the user to the feeds (by name) that are True, and unsubscribe them from the others.
        Returns how many changed """
    logger = logging.getLogger(__name__)
    count = 0
    db = database.DBConnection()
    try:
        for feedname, subscribe in feeds.items():
            res = db.match('SELECT * from subscribers WHERE Type=? and UserID=? and WantID=?', ("feed", userid, feedname))
            if subscribe and res:
                logger.debug(f"{feedname} {userid} was already subscribed")
            elif subscribe:
                count += 1
                db.action('INSERT INTO subscribers (Type, UserID, WantID) VALUES (?, ?, ?)', ("feed", userid, feedname))
                logger.debug(f"Subscribed {userid} to {feedname}")
            elif res:
                count += 1
                db.action('DELETE from subscribers WHERE Type=? and UserID=? and WantID=?', ("feed", userid, feedname))
                logger.debug(f"Unsubscribed {userid} to {feedname}")
            else:
                logger.debug(f"{feedname} {userid} was already unsubscribed")
    finally:
        db.close()
    return count
