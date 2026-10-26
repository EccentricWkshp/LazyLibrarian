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

""" Series: the series list, a series and its members, edits and marking series """

import logging

from lazylibrarian import database
from lazylibrarian.bookwork import add_series_members
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, get_list, natural_sort, surname_first
from lazylibrarian.scheduling import ensure_running
from lazylibrarian.services import NotFoundError, books
from lazylibrarian.services.paging import Page, page_of
from lazylibrarian.services.system import start_task

SERIES_STATUSES = ("Wanted", "Active", "Skipped", "Ignored", "Paused")
# the series list fields, in the order the search has always matched them
SEARCH_FIELDS = ('SeriesID', 'AuthorName', 'SeriesName', 'Status', 'AuthorID', 'SeriesID', 'Have', 'Total', 'Reason')


def remove_series(seriesid):
    db = database.DBConnection()
    try:
        if not db.match("SELECT SeriesID from series WHERE SeriesID=?", (seriesid,)):
            raise NotFoundError(f'Missing series: {seriesid}')
        db.action("DELETE from series WHERE SeriesID=?", (seriesid,))
    finally:
        db.close()


def series_for_edit(seriesid) -> dict:
    """ A series, with Reason showing the book it was found from when it was, and its members in order """
    db = database.DBConnection()
    try:
        series = db.match("SELECT * from series WHERE seriesid=?", (seriesid,))
        if not series:
            raise NotFoundError(f"Series {seriesid} not found")
        series = dict(series)
        reason = series['Reason']
        bookinfo = db.match("select BookName,BookID from books where (bookid=?) or (gr_id=?) or (lt_workid=?)",
                            (reason, reason, reason))
        if bookinfo:
            series['Reason'] = f"{bookinfo['BookID']}: {bookinfo['BookName']}"
        members = [dict(m) for m in db.select("SELECT SeriesNum,BookName from member,books WHERE "
                                              "books.BookID=member.BookID and seriesid=?", (seriesid,))]
    finally:
        db.close()
    # sort properly by seriesnum as sqlite doesn't (yet) have natural sort
    natural_sort(members, key=lambda y: y['SeriesNum'] if y['SeriesNum'] is not None else '')
    return {'series': series, 'members': members}


def update_series(seriesid, new_id: str = '', new_name: str = '') -> bool:
    """ Change a series' id and/or name, returns whether anything changed """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        old_data = db.match("SELECT * from series where seriesid=?", (seriesid,))
        if not old_data:
            logger.debug(f"No match updating series {seriesid}")
            raise NotFoundError(f"Series {seriesid} not found")
        seriesid = old_data['SeriesID']
        seriesname = old_data['SeriesName']
        updated = False
        if new_id and new_id != seriesid:
            seriesid = new_id
            updated = True
        if new_name and new_name != seriesname:
            seriesname = new_name
            updated = True
        if updated:
            db.action('PRAGMA foreign_keys = OFF')
            db.action("UPDATE series SET SeriesID=?, SeriesName=? WHERE SeriesID=?",
                      (seriesid, seriesname, old_data['SeriesID']))
            if seriesid != old_data['SeriesID']:
                for table in ['member', 'seriesauthors']:
                    db.action(f"UPDATE {table} SET SeriesID=? WHERE SeriesID=?", (seriesid, old_data['SeriesID']))
            db.action('PRAGMA foreign_keys = ON')
            logger.debug(f"Updated series info for {seriesid}:{seriesname}")
        return updated
    finally:
        db.close()


def refresh_series(seriesid) -> bool:
    """ Look for the series' members again, in the background """
    return start_task(f'SERIESMEMBERS_{seriesid}', add_series_members, seriesid, True)


def list_series(search: str = '', sort: str = 'AuthorSort', descending: bool = False, offset: int = 0,
                limit: int | None = None, status: str = 'All', authorid: str = '', active_only: bool = False,
                subscriber=None) -> Page:
    """ A page of series, by author and name unless sorted otherwise.

        status is a series status, All, or Empty, Partial or Complete for how many of the books we have.
        authorid limits it to one author's series, active_only (without an author) to series of
        authors that are Active or Wanted, subscriber to the series that user subscribes to.
        Each item has the series columns, its author's AuthorName and AuthorID, plus Source (the two
        letters at the start of the SeriesID), AuthorSort (surname first if set) and Percent, how many of
        its books we have. Sorting on Percent breaks ties on Total the other way round, so the bigger
        series come first going up and last going down.
    """
    serversidelogger = logging.getLogger('special.serverside')
    cmd = ("SELECT series.SeriesID,AuthorName,SeriesName,series.Status,seriesauthors.AuthorID,Have,Total,"
           "series.Reason from series,authors,seriesauthors,member where authors.AuthorID=seriesauthors.AuthorID "
           "and series.SeriesID=seriesauthors.SeriesID and member.seriesid=series.seriesid")
    if active_only and not authorid:
        cmd += " and authors.status IN ('Active', 'Wanted')"
    args = []
    if status == 'Empty':
        cmd += " and Have = 0"
    elif status == 'Partial':
        cmd += " and Have > 0"
    elif status == 'Complete':
        cmd += " and Have > 0 and Have = Total"
    elif status not in ['All', 'None']:
        cmd += " and series.Status=?"
        args.append(status)
    if authorid:
        cmd += " and seriesauthors.AuthorID=?"
        args.append(authorid)
    db = database.DBConnection()
    try:
        if subscriber:
            res = db.select("SELECT WantID from subscribers WHERE Type='series' and UserID=?", (subscriber,))
            serversidelogger.debug(f"User subscribes to {len(res)} series")
            if res:
                cmd += f" and series.seriesID in ({', '.join('?' * len(res))})"
                args.extend(s['WantID'] for s in res)
        cmd += " GROUP BY series.seriesID order by AuthorName,SeriesName"
        serversidelogger.debug(f"list_series {cmd}: {str(args)}")
        rows = db.select(cmd, tuple(args))
    finally:
        db.close()

    postfixes = get_list(CONFIG.get_csv('NAME_POSTFIX'))
    found = []
    for row in rows:
        series = dict(row)
        series['Source'] = series['SeriesID'][:2]
        series['AuthorSort'] = series['AuthorName']
        if CONFIG.get_bool('SORT_SURNAME'):
            series['AuthorSort'] = surname_first(series['AuthorName'], postfixes=postfixes)
        have = check_int(series['Have'], 0)
        total = check_int(series['Total'], 0)
        series['Percent'] = min(int((have * 100.0) / total), 100) if total else 0
        found.append(series)
    sort_key = None
    if sort == 'Percent':
        def sort_key(s):
            return s['Percent'], -check_int(s['Total'], 0)
    return page_of(found, search=search, search_fields=SEARCH_FIELDS, sort=sort, sort_key=sort_key,
                   descending=descending, offset=offset, limit=limit)


def series_page(seriesid, ignored: bool = False, userid=None) -> dict:
    """ A series with its author (the first, for a series by more than one), its members (the ignored
        ones, or the others) with the reading list each one is on, and whether it has more than one author """
    db = database.DBConnection()
    try:
        series = db.match("SELECT SeriesName,series.SeriesID,AuthorName,seriesauthors.AuthorID from "
                          "series,authors,seriesauthors where authors.AuthorID=seriesauthors.AuthorID and "
                          "series.SeriesID=seriesauthors.SeriesID and series.SeriesID=?", (seriesid,))
        if not series:
            raise NotFoundError(f"Series {seriesid} not found")
        which = ("(books.Status == 'Ignored' or AudioStatus == 'Ignored')" if ignored else
                 "(books.Status != 'Ignored' and AudioStatus != 'Ignored')")
        members = db.select("SELECT member.BookID,BookName,SeriesNum,BookImg,books.Status,AuthorName,authors.AuthorID,"
                            "BookLink,WorkPage,AudioStatus,BookSub from member,series,books,authors where "
                            "series.SeriesID=member.SeriesID and books.BookID=member.BookID and "
                            f"books.AuthorID=authors.AuthorID and {which} and series.SeriesID=? order by SeriesName",
                            (seriesid,))
    finally:
        db.close()
    lists = books.reading_lists(userid)
    found = []
    for row in members:
        member = dict(row)
        member['ReadingList'] = next((name for name in books.READING_LISTS if member['BookID'] in lists[name]), None)
        found.append(member)
    multi = len({m['AuthorID'] for m in found}) > 1
    return {'series': dict(series), 'members': found, 'multi': multi}


def mark_series(action: str, seriesids, userid=None) -> tuple[int, int]:
    """ Set a status on series (Wanted and Active look for their members and monitor them, the others
        stop monitoring them), put all their books on one of the user's reading lists or take them off
        them all (books.READING_ACTIONS), or subscribe or unsubscribe the user. Returns (passed, failed) """
    logger = logging.getLogger(__name__)
    passed = failed = 0
    if not action:
        return passed, failed
    db = database.DBConnection()
    try:
        for seriesid in seriesids:
            if action in SERIES_STATUSES:
                match = db.match('SELECT SeriesName from series WHERE SeriesID=?', (seriesid,))
                if not match:
                    logger.debug(f"Failed to match {seriesid}")
                    failed += 1
                    continue
                passed += 1
                db.upsert("series", {'Status': action}, {'SeriesID': seriesid})
                logger.debug(f'Status set to "{action}" for "{match["SeriesName"]}"')
                if action in ['Wanted', 'Active']:
                    start_task(f'SERIESMEMBERS_{seriesid}', add_series_members, seriesid)
                    ensure_running('series_update')
                else:
                    # stop monitoring
                    db.action("UPDATE series SET Updated=0 WHERE SeriesID=?", (seriesid,))
            elif action in books.READING_ACTIONS and userid:
                members = [m['bookid'] for m in db.select('SELECT bookid from member where seriesid=?', (seriesid,))]
                if not members:
                    logger.debug(f"No members found for {seriesid}")
                    failed += 1
                else:
                    passed += books.mark_books(action, members, userid=userid)['passed']
            elif action == 'Subscribe':
                if not db.match('SELECT SeriesID from series WHERE SeriesID=?', (seriesid,)):
                    logger.debug(f"Subscribe failed, series {seriesid} not found")
                    failed += 1
                elif not userid:
                    logger.debug(f"No userid, cannot subscribe to {seriesid}")
                    failed += 1
                elif db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                              (userid, 'series', seriesid)):
                    logger.debug(f"User {userid} is already subscribed to {seriesid}")
                    failed += 1
                else:
                    db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                              (userid, 'series', seriesid))
                    logger.debug(f"Subscribe {userid} to series {seriesid}")
                    passed += 1
            elif action == 'Unsubscribe' and userid:
                db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?', (userid, 'series', seriesid))
                logger.debug(f"Unsubscribe {userid} to series {seriesid}")
                passed += 1
    finally:
        db.close()
    return passed, failed
