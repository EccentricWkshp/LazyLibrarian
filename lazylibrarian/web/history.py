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

""" Download history, the blocklist and the provider download counters """

import logging
import re
import traceback

import cherrypy

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.auth import require_auth
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.config2 import CONFIG
from lazylibrarian.download_client import get_download_progress
from lazylibrarian.formatter import date_format, fold, make_unicode, natural_sort, plural
from lazylibrarian.web.common import BasePages, serve_template


class HistoryPages(BasePages):
    """ Download history, the blocklist and the provider download counters """

    @cherrypy.expose
    @require_auth()
    def history(self):
        return serve_template(templatename="history.html", title=i18n.gettext("History"), history=[])

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_history(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        rows = []
        filtered = []
        rowlist = []
        self.label_thread('WEBSERVER')
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            snatching = 0
            cmd = "SELECT NZBTitle,AuxInfo,BookID,NZBProv,NZBDate,NZBSize,Status,Source,DownloadID,rowid from wanted "
            cmd += "where BookID is not null and AuxInfo is not null"
            rowlist = db.select(cmd)
            # turn the sqlite rowlist into a list of dicts
            if len(rowlist):
                # the masterlist to be filled with the row data
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)  # turn sqlite objects into lists
                    rows.append(entry)  # add the rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    q = fold(sSearch)
                    filtered = [x for x in rows if q in fold(x)]
                    #filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                # use rowid to get most recently added first (monitoring progress)
                if sortcolumn == 6:
                    sortcolumn = 9

                if sortcolumn == 5:
                    natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    nrows = filtered
                else:
                    nrows = filtered[displaystart:(displaystart + displaylength)]

                lazylibrarian.HIST_REFRESH = 0
                rows = []
                for row in nrows:
                    row = list(row)
                    row[8] = make_unicode(row[8])  # delugerpc returns bytes
                    # title needs spaces, not dots, for column resizing
                    title = row[0]  # type: str
                    if title:
                        title = title.replace('.', ' ')
                        row[0] = title
                    # provider name needs to be shorter and with spaces for column resizing
                    if row[3]:
                        row[3] = CONFIG.disp_name(row[3].strip('/'))
                    # separate out rowid and other additions, so we don't break legacy interface
                    rowid = row[9]
                    row = row[:9]
                    if row[6] == 'Snatched':
                        snatching += 1
                        if snatching <= 5:
                            progress, _ = get_download_progress(row[7], row[8])
                            row.append(progress)
                            if progress < 100:
                                lazylibrarian.HIST_REFRESH = CONFIG.get_int('HIST_REFRESH')
                        else:
                            row.append(-1)
                    else:
                        row.append(-1)
                    row.append(rowid)
                    row.append(row[4])  # keep full datetime for tooltip
                    row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

                    if row[1] in ['eBook', 'AudioBook']:
                        btn = '<button onclick="bookinfo(\'' + row[2]
                        btn += '\')" class="button btn-link text-left" type="button" '
                        btn += '>' + row[1] + '</button>'
                        row[1] = btn
                        auth = db.match('SELECT authorid from books where bookid=?', (row[2],))
                        if auth:
                            # noinspection PyBroadException
                            try:
                                btn = '<a href=\'author_page?authorid='
                                btn += auth['authorid']
                                btn += '\'">' + row[2] + '</a>'
                                row[2] = btn
                            except Exception:
                                logger.debug(f"Unexpected authorid [{auth}]")
                    elif row[1] == 'comic':
                        btn = '<a href=\'open_comic?comicid=' + row[2].split('_')[0] + '\'">' + row[2] + '</a>'
                        row[2] = btn
                    else:
                        # noinspection PyBroadException
                        try:
                            if row[1] and re.match(r"^[0-9.-]+$", row[1]) is not None:  # Magazine
                                btn = '<a href=\'open_mag?bookid=' + row[2] + '\'">' + row[2] + '</a>'
                                row[2] = btn
                        except Exception:
                            logger.debug(f"Unexpected auxinfo [{row[1]}] {row[2]}")
                            continue
                    rows.append(row)

            serversidelogger.debug(
                f"get_history returning {displaystart} to {displaystart + displaylength}, snatching {snatching}")
            serversidelogger.debug(f"get_history filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_history: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        db.close()
        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def dlinfo(self, target=None):
        if '^' not in target:
            return ''
        db = database.DBConnection()
        status, rowid = target.split('^')
        if status == 'Ignored':
            match = db.match('select ScanResult from books WHERE bookid=?', (rowid,))
            message = i18n.gettext('Reason: %(reason)s') % {'reason': match["ScanResult"]} + '<br>'
        else:
            cmd = ("select NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,DLResult,Source,"
                   "DownloadID from wanted where rowid=?")
            match = db.match(cmd, (rowid,))
            dltype = match['AuxInfo']
            if dltype not in ['eBook', 'AudioBook']:
                if not dltype:
                    dltype = 'eBook'
                else:
                    dltype = 'Magazine'
            lines = [
                i18n.gettext("Title: %(value)s") % {'value': match['NZBtitle']},
                i18n.gettext("Type: %(value)s") % {'value': f"{match['NZBmode']} {i18n.status_label(dltype)}"},
                i18n.gettext("Date: %(value)s") % {'value': match['NZBdate']},
                i18n.gettext("Size: %(value)s Mb") % {'value': match['NZBsize']},
                i18n.gettext("Provider: %(value)s") % {'value': CONFIG.disp_name(match['NZBprov'])},
                i18n.gettext("Downloader: %(value)s") % {'value': match['Source']},
                i18n.gettext("DownloadID: %(value)s") % {'value': match['DownloadID']},
                i18n.gettext("URL: %(value)s") % {'value': match['NZBurl']},
            ]
            message = '<br>'.join(lines) + '<br>'
            if status == 'Processed':
                message += i18n.gettext("File: %(value)s") % {'value': match['DLResult']} + '<br>'
            elif status == 'Seeding':
                message += i18n.status_label(status)
            else:
                message += i18n.gettext("Error: %(value)s") % {'value': match['DLResult']} + '<br>'
        db.close()
        return message

    @cherrypy.expose
    @require_auth()
    def deletehistory(self, rowid=None):
        logger = logging.getLogger(__name__)
        if not rowid:
            logger.warning("No rowid in deletehistory")
        else:
            db = database.DBConnection()
            try:
                match = db.match('SELECT NZBtitle,Status from wanted WHERE rowid=?', (rowid,))
                if match:
                    logger.debug(f'Deleting {match["Status"]} history item {match["NZBtitle"]}')
                    db.action('DELETE from wanted WHERE rowid=?', (rowid,))
                else:
                    logger.warning(f"No rowid {rowid} in history")
            finally:
                db.close()

    @cherrypy.expose
    @require_auth()
    def markhistory(self, rowid=None):
        logger = logging.getLogger(__name__)
        if not rowid:
            return
        db = database.DBConnection()
        match = db.match('SELECT NZBtitle,Status,BookID,AuxInfo from wanted WHERE rowid=?', (rowid,))
        logger.debug(f'Marking {match["Status"]} history item {match["NZBtitle"]} as Failed')
        db.action("UPDATE wanted SET Status='Failed' WHERE rowid=?", (rowid,))
        book_type = match['AuxInfo']
        if book_type not in ['AudioBook', 'eBook']:
            if not book_type:
                book_type = 'eBook'
            else:
                book_type = 'Magazine'
        if book_type == 'AudioBook':
            db.action("UPDATE books SET audiostatus='Wanted' WHERE BookID=?", (match["BookID"],))
        else:
            db.action("UPDATE books SET status='Wanted' WHERE BookID=?", (match["BookID"],))
        db.close()

    @cherrypy.expose
    @require_auth()
    def clearhistory(self, status=None):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        if not status or status == 'all':
            logger.info("Clearing all history")
            # Reset Snatched books back to Wanted so they get searched again
            status = "Snatched"
            cmd = "SELECT BookID,AuxInfo from wanted WHERE Status=?"
            rowlist = db.select(cmd, (status,))
            for book in rowlist:
                if book['BookID'] != 'unknown':
                    if book['AuxInfo'] == 'eBook':
                        db.action("UPDATE books SET Status='Wanted' WHERE Bookid=? AND Status=?",
                                  (book['BookID'], status))
                    elif book['AuxInfo'] == 'AudioBook':
                        db.action("UPDATE books SET AudioStatus='Wanted' WHERE Bookid=? AND AudioStatus=?",
                                  (book['BookID'], status))
            db.action("DELETE from wanted")
        else:
            logger.info(f"Clearing history where status is {status}")
            if status == 'Snatched':
                # Reset Snatched books back to Wanted so they get searched again
                cmd = "SELECT BookID,AuxInfo from wanted WHERE Status in ('Snatched', 'Matched')"
                rowlist = db.select(cmd)
                for book in rowlist:
                    if book['BookID'] != 'unknown':
                        if book['AuxInfo'] == 'eBook':
                            db.action("UPDATE books SET Status='Wanted' WHERE Bookid=? AND Status=?",
                                      (book['BookID'], status))
                        elif book['AuxInfo'] == 'AudioBook':
                            db.action("UPDATE books SET AudioStatus='Wanted' WHERE Bookid=? AND AudioStatus=?",
                                      (book['BookID'], status))
                db.action("DELETE from wanted WHERE Status='Matched'")
            db.action('DELETE from wanted WHERE Status=?', (status,))
        db.close()
        raise cherrypy.HTTPRedirect("history")

    @cherrypy.expose
    @require_auth()
    def clearblocked(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # clear any currently blocked providers
        num = BLOCKHANDLER.clear_all()
        logger.debug(f'Cleared {num} blocked {plural(num, "provider")}')
        return i18n.ngettext('Cleared %(count)s blocked provider', 'Cleared %(count)s blocked providers',
                             num) % {'count': num}

    @cherrypy.expose
    @require_auth()
    def showblocked(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # show any currently blocked providers
        result = BLOCKHANDLER.get_text_list_of_blocks()
        logger.debug(result)
        return result

    @cherrypy.expose
    @require_auth()
    def cleardownloads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # clear download counters
        db = database.DBConnection()
        try:
            count = db.match('SELECT COUNT(*) as counter FROM downloads')
            if count:
                num = count['counter']
            else:
                num = 0
            db.action('DELETE from downloads')
        finally:
            db.close()
        logger.debug(f'Deleted download counter for {num} {plural(num, "provider")}')
        return i18n.ngettext('Deleted download counter for %(count)s provider',
                             'Deleted download counter for %(count)s providers', num) % {'count': num}

    @cherrypy.expose
    @require_auth()
    def showdownloads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        # show provider download totals
        result = ''
        db = database.DBConnection()
        try:
            downloads = db.select('SELECT Count,Provider FROM downloads ORDER BY Count DESC')
        finally:
            db.close()
        for line in downloads:
            provname = CONFIG.disp_name(line['Provider'].strip('/'))
            new_entry = f"{line['Count']:4d} - {provname}\n"
            result += new_entry

        if result == '':
            result = i18n.gettext('No downloads')
        return result
