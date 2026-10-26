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

""" The series list, series members and series edits """

import logging
import threading
import traceback

import cherrypy

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.auth import owner_id, require_auth
from lazylibrarian.bookwork import add_series_members
from lazylibrarian.common import get_readinglist, set_readinglist
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, get_list, surname_first
from lazylibrarian.scheduling import ensure_running
from lazylibrarian.web.common import BasePages, fold, mark_summary, serve_template


class SeriesPages(BasePages):
    """ The series list, series members and series edits """

    @cherrypy.expose
    @require_auth()
    def remove_series(self, seriesid):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        seriesdata = db.match("SELECT * from series WHERE seriesid=?", (seriesid,))
        if seriesdata:
            db.action("DELETE from series WHERE SeriesID=?", (seriesid,))
        else:
            logger.warning(f'Missing series: {seriesid}')
        db.close()
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def edit_series(self, seriesid):
        logger = logging.getLogger(__name__)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_SERIES')
        db = database.DBConnection()
        seriesdata = db.match("SELECT * from series WHERE seriesid=?", (seriesid,))
        if seriesdata:
            # use bookid to update seriesdata['Reason']
            seriesdata = dict(seriesdata)
            cmd = "select BookName,BookID from books where (bookid=?) or (gr_id=?) or (lt_workid=?)"
            reason = seriesdata['Reason']
            bookinfo = db.match(cmd, (reason, reason, reason))
            if bookinfo:
                seriesdata['Reason'] = f"{bookinfo['BookID']}: {bookinfo['BookName']}"

            cmd = "SELECT SeriesNum,BookName from member,books WHERE books.BookID=member.BookID and seriesid=?"
            memberdata = db.select(cmd, (seriesid,))
            # sort properly by seriesnum as sqlite doesn't (yet) have natural sort
            members = []
            for itm in memberdata:
                members.append(dict(itm))
            self.natural_sort(members, key=lambda y: y['SeriesNum'] if y['SeriesNum'] is not None else '')
            db.close()
            return serve_template(templatename="editseries.html", title=i18n.gettext("Edit Series"), config=seriesdata,
                                  members=members)
        logger.info(f'Missing series {seriesid}')
        db.close()
        raise cherrypy.HTTPError(404, f"Series {seriesid} not found")

    @cherrypy.expose
    @require_auth()
    def series_update(self, seriesid='', **kwargs):
        logger = logging.getLogger(__name__)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        db = database.DBConnection()
        if seriesid:
            old_data = db.match("SELECT * from series where seriesid=?", (seriesid,))
            if old_data:
                updated = False
                seriesname = old_data['SeriesName']
                seriesid = old_data['SeriesID']
                new_id = kwargs.get('new_id')
                if new_id and new_id != seriesid:
                    seriesid = new_id
                    updated = True
                new_name = kwargs.get('new_name')
                if new_name:
                    self.validate_param("new series name", new_name, ['<', '>', '='], 404)
                if new_name and new_name != seriesname:
                    seriesname = new_name
                    updated = True
                if updated:
                    db.action('PRAGMA foreign_keys = OFF')
                    db.action("UPDATE series SET SeriesID=?, SeriesName=? WHERE SeriesID=?",
                              (seriesid, seriesname, old_data['SeriesID']))
                    if seriesid != old_data['SeriesID']:
                        for table in ['member', 'seriesauthors']:
                            cmd = "UPDATE " + table + " SET SeriesID=? WHERE SeriesID=?"
                            db.action(cmd, (seriesid, old_data['SeriesID']))
                    db.action('PRAGMA foreign_keys = ON')
                    logger.debug(f"Updated series info for {seriesid}:{seriesname}")
            else:
                logger.debug(f"No match updating series {seriesid}")
                raise cherrypy.HTTPError(404, f"Series {seriesid} not found")
        db.close()
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def refresh_series(self, seriesid):
        logger = logging.getLogger(__name__)
        threadname = f'SERIESMEMBERS_{seriesid}'
        if threadname in [n.name for n in list(threading.enumerate())]:
            logger.warning(f"{threadname} is already running")
        else:
            threading.Thread(target=add_series_members, name=threadname, args=[seriesid, True]).start()
        raise cherrypy.HTTPRedirect(f"series_members?seriesid={seriesid}&ignored=False")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_series(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        filtered = []
        userid = None
        userprefs = 0
        cookie = cherrypy.request.cookie
        userid = owner_id()
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)

        # noinspection PyBroadException
        try:
            # kwargs is used by datatables to pass params
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            which_status = 'All'
            if kwargs['whichStatus']:
                which_status = kwargs['whichStatus']

            author_id = ''
            if kwargs['AuthorID']:
                author_id = kwargs['AuthorID']

            if not author_id or author_id == 'None':
                author_id = ''

            # We pass series.SeriesID twice for datatables as the render function modifies it,
            # and we need it in two columns. There is probably a better way...
            cmd = ("SELECT series.SeriesID,AuthorName,SeriesName,series.Status,seriesauthors.AuthorID,series."
                   "SeriesID,Have,Total,series.Reason from series,authors,seriesauthors,member where "
                   "authors.AuthorID=seriesauthors.AuthorID and series.SeriesID=seriesauthors.SeriesID and "
                   "member.seriesid=series.seriesid")  # and seriesnum=1"

            if 'active' in kwargs and kwargs['active'] and not author_id:
                cmd += " and authors.status IN ('Active', 'Wanted')"

            args = []
            if which_status == 'Empty':
                cmd += " and Have = 0"
            elif which_status == 'Partial':
                cmd += " and Have > 0"
            elif which_status == 'Complete':
                cmd += " and Have > 0 and Have = Total"
            elif which_status not in ['All', 'None']:
                cmd += " and series.Status=?"
                args.append(which_status)
            if author_id:
                cmd += " and seriesauthors.AuthorID=?"
                args.append(author_id)

            myseries = []
            db = database.DBConnection()
            if userid and userprefs & lazylibrarian.pref_myseries:
                res = db.select("SELECT WantID from subscribers WHERE Type='series' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} series")
                for series in res:
                    myseries.append(series['WantID'])
                if myseries:
                    cmd += " and series.seriesID in (?)"
                    args.append(", ".join(f"'{w}'" for w in myseries))
            cmd += " GROUP BY series.seriesID order by AuthorName,SeriesName"

            serversidelogger.debug(f"get_series {cmd}: {str(args)}")

            if args:
                rowlist = db.select(cmd, tuple(args))
            else:
                rowlist = db.select(cmd)
            db.close()

            # turn the sqlite rowlist into a list of lists
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)  # turn sqlite objects into lists

                    rows.append(entry)  # add the rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    q = fold(sSearch)
                    filtered = [x for x in rows if q in fold(x)]
                    # filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                for row in filtered:
                    row.append(row[0][:2])  # extract 2 letter source from seriesid
                    if CONFIG.get_bool('SORT_SURNAME'):
                        row[1] = surname_first(row[1], postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
                    have = check_int(row[6], 0)
                    total = check_int(row[7], 0)
                    if total:
                        percent = int((have * 100.0) / total)
                    else:
                        percent = 0

                    if percent > 100:
                        percent = 100

                    row.append(percent)

                if sortcolumn == 3:  # percent
                    sortcolumn = 9
                if sortcolumn == 4:  # status
                    sortcolumn = 3

                if sortcolumn == 9:  # sort on percent,-total
                    if sSortDir_0 == "desc":
                        filtered.sort(key=lambda y: (-int(y[10]), int(y[7])))
                    else:
                        filtered.sort(key=lambda y: (int(y[10]), -int(y[7])))
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

            serversidelogger.debug(f"get_series returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_series filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
            mydict = {'iTotalDisplayRecords': len(filtered),
                      'iTotalRecords': len(rowlist),
                      'aaData': rows,
                      }
            serversidelogger.debug(str(mydict))
            return mydict

        except Exception:
            logger.error(f'Unhandled exception in get_series: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []
            mydict = {'iTotalDisplayRecords': len(filtered),
                      'iTotalRecords': len(rowlist),
                      'aaData': rows,
                      }
            serversidelogger.debug(str(mydict))
            return mydict

    @cherrypy.expose
    @require_auth()
    def series(self, authorid=None, which_status=None, active=False):
        title = i18n.gettext('Series')
        if authorid:
            db = database.DBConnection()
            try:
                match = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
            finally:
                db.close()
            if match:
                title = i18n.gettext('%(author)s Series') % {'author': match['AuthorName']}
            if '&' in title and '&amp;' not in title:
                title = title.replace('&', '&amp;')

        return serve_template(templatename="series.html", title=title, authorid=authorid, series=[],
                              whichStatus=which_status, active=active)

    @cherrypy.expose
    @require_auth()
    def series_members(self, seriesid, ignored=False):
        db = database.DBConnection()
        cmd = ("SELECT SeriesName,series.SeriesID,AuthorName,seriesauthors.AuthorID from "
               "series,authors,seriesauthors where authors.AuthorID=seriesauthors.AuthorID and "
               "series.SeriesID=seriesauthors.SeriesID and series.SeriesID=?")
        series = db.match(cmd, (seriesid,))
        cmd = ("SELECT member.BookID,BookName,SeriesNum,BookImg,books.Status,AuthorName,authors.AuthorID,"
               "BookLink,WorkPage,AudioStatus,BookSub from member,series,books,authors where "
               "series.SeriesID=member.SeriesID and books.BookID=member.BookID and "
               "books.AuthorID=authors.AuthorID and ")
        if not ignored or ignored == 'False':
            cmd += "(books.Status != 'Ignored' and AudioStatus != 'Ignored')"
        else:
            cmd += "(books.Status == 'Ignored' or AudioStatus == 'Ignored')"
        cmd += " and series.SeriesID=? order by SeriesName"
        members = db.select(cmd, (seriesid,))
        # is it a multi-author series?
        multi = "False"
        authorid = ''
        for itm in members:
            if not authorid:
                authorid = itm['AuthorID']
            else:
                if authorid != itm['AuthorID']:
                    multi = "True"
                    break

        email = ''
        to_read = set()
        have_read = set()
        reading = set()
        abandoned = set()
        if owner_id():
            cmd = "SELECT UserName,Perms,SendTo from users where UserID=?"
            userid = owner_id()
            res = db.match(cmd, (userid,))
            if res:
                to_read = get_readinglist('ToRead', userid)
                have_read = get_readinglist('HaveRead', userid)
                reading = get_readinglist('Reading', userid)
                abandoned = get_readinglist('Abandoned', userid)
                email = res['SendTo']
                if not email:
                    email = ''
        db.close()
        # turn the sqlite rowlist into a list of lists
        rows = []

        if len(members):
            # the masterlist to be filled with the row data
            for row in members:  # iterate through the sqlite3.Row objects
                entry = list(row)
                if entry[0] in to_read:
                    flag = '&nbsp;<i class="far fa-bookmark"></i>'
                elif entry[0] in have_read:
                    flag = '&nbsp;<i class="fas fa-bookmark"></i>'
                elif entry[0] in reading:
                    flag = '&nbsp;<i class="fas fa-play-circle"></i>'
                elif entry[0] in abandoned:
                    flag = '&nbsp;<i class="fas fa-ban"></i>'
                else:
                    flag = ''
                if entry[10]:  # is there a subtitle
                    bk_name = f'{entry[1]}<br><small><i>{entry[10]}</i></small>'
                else:
                    bk_name = entry[1]
                newrow = {'BookID': entry[0], 'BookName': bk_name, 'SeriesNum': entry[2], 'BookImg': entry[3],
                          'Status': entry[4], 'AuthorName': entry[5], 'AuthorID': entry[6],
                          'BookLink': entry[7] if entry[7] else '', 'WorkPage': entry[8] if entry[8] else '',
                          'AudioStatus': entry[9], 'Flag': flag}

                rows.append(newrow)  # add the new dict to the masterlist

        return serve_template(templatename="members.html", title=series['SeriesName'],
                              members=rows, series=series, multi=multi, ignored=ignored, email=email)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_series_ajax(self, action=None, redirect=None, **args):
        # redirect is an explicit param (not left in **args) for the same reason
        # mark_books_ajax already declares it: series.html's #mark_series form has a
        # hidden `redirect` field (the authorid to bounce back to) that FormData sends
        # alongside the checked series - left in args it's iterated as if it were a
        # SeriesID, fails to match any series, and is counted as a failed item
        # (Issue #2850).
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        for arg in ['book_table_length', 'series_table_length', 'author_table_length', 'ignored', '_', 'action', 'which_status']:
            args.pop(arg, None)
        passed = 0
        failed = 0
        if redirect is None:
            redirect = ''
        if action:
            for seriesid in args:
                if action in ["Wanted", "Active", "Skipped", "Ignored", "Paused"]:
                    match = db.match('SELECT SeriesName from series WHERE SeriesID=?', (seriesid,))
                    if not match:
                        logger.debug(f"Failed to match {seriesid}")
                        failed += 1
                    else:
                        passed += 1
                        db.upsert("series", {'Status': action}, {'SeriesID': seriesid})
                        logger.debug(f'Status set to "{action}" for "{match["SeriesName"]}"')
                        if action in ['Wanted', 'Active']:
                            threadname = f'SERIESMEMBERS_{seriesid}'
                            if threadname not in [n.name for n in list(threading.enumerate())]:
                                threading.Thread(target=add_series_members, name=threadname,
                                                 args=[seriesid]).start()
                            ensure_running('series_update')
                        else:
                            # stop monitoring
                            db.action("UPDATE series SET Updated=0 WHERE SeriesID=?", (seriesid,))
                elif action in ["Unread", "Read", "ToRead", "Reading", "Abandoned"]:
                    userid = owner_id()
                    if userid:
                        to_read = set(get_readinglist('ToRead', userid))
                        have_read = set(get_readinglist('HaveRead', userid))
                        reading = set(get_readinglist('Reading', userid))
                        abandoned = set(get_readinglist('Abandoned', userid))
                        members = db.select('SELECT bookid from member where seriesid=?', (seriesid,))
                        if not members:
                            logger.debug(f"No members found for {seriesid}")
                            failed += 1
                        else:
                            for itm in members:
                                bookid = itm['bookid']
                                if action == "Unread":
                                    to_read.discard(bookid)
                                    have_read.discard(bookid)
                                    reading.discard(bookid)
                                    abandoned.discard(bookid)
                                    logger.debug(f'Status set to "unread" for "{bookid}"')
                                elif action == "Read":
                                    to_read.discard(bookid)
                                    reading.discard(bookid)
                                    abandoned.discard(bookid)
                                    have_read.add(bookid)
                                    logger.debug(f'Status set to "read" for "{bookid}"')
                                elif action == "ToRead":
                                    reading.discard(bookid)
                                    abandoned.discard(bookid)
                                    have_read.discard(bookid)
                                    to_read.add(bookid)
                                    logger.debug(f'Status set to "to read" for "{bookid}"')
                                elif action == "Reading":
                                    reading.add(bookid)
                                    abandoned.discard(bookid)
                                    have_read.discard(bookid)
                                    to_read.discard(bookid)
                                    logger.debug(f'Status set to "reading" for "{bookid}"')
                                elif action == "Abandoned":
                                    reading.discard(bookid)
                                    abandoned.add(bookid)
                                    have_read.discard(bookid)
                                    to_read.discard(bookid)
                                    logger.debug(f'Status set to "abandoned" for "{bookid}"')
                                passed += 1
                            set_readinglist('ToRead', userid, to_read)
                            set_readinglist('HaveRead', userid, have_read)
                            set_readinglist('Reading', userid, reading)
                            set_readinglist('Abandoned', userid, abandoned)

                elif action == 'Subscribe':
                    match = db.match('SELECT SeriesID from series WHERE SeriesID=?', (seriesid,))
                    if not match:
                        logger.debug(f"Subscribe failed, series {seriesid} not found")
                        failed += 1
                    else:
                        userid = owner_id()
                        if userid:
                            res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                           (userid, 'series', seriesid))
                            if res:
                                logger.debug(f"User {userid} is already subscribed to {seriesid}")
                                failed += 1
                            else:
                                db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                          (userid, 'series', seriesid))
                                logger.debug(f"Subscribe {userid} to series {seriesid}")
                                passed += 1
                        else:
                            logger.debug(f"No userid, cannot subscribe to {seriesid}")
                            failed += 1

                elif action == 'Unsubscribe':
                    userid = owner_id()
                    if userid:
                        db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                  (userid, 'series', seriesid))
                        passed += 1
                        res = db.select('SELECT bookid from series where seriesid=?', (seriesid, ))
                        for iss in res:
                            db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                      (userid, 'series', iss['bookid']))
                        logger.debug(f"Unsubscribe {userid} to series {seriesid}")

            if redirect:
                redirect = f"series?authorid={redirect}"
            else:
                redirect = "series"
        db.close()

        # Return JSON response instead of redirect
        total = passed + failed
        summary = mark_summary(i18n.gettext("Mark Series '%(action)s' completed.") % {
            'action': i18n.status_label(action)}, passed, failed)
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary,
            'redirect': redirect
        }
