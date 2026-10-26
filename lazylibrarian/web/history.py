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
from lazylibrarian import i18n
from lazylibrarian.auth import require_auth
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import date_format, plural
from lazylibrarian.services import NotFoundError, history
from lazylibrarian.web.common import BasePages, serve_template

# history.html's columns, the progress column sorts by rowid to put the newest first
HISTORY_COLUMNS = history.HISTORY_FIELDS[:6] + ('rowid',) + history.HISTORY_FIELDS[7:] + ('rowid',)


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
        self.label_thread('WEBSERVER')
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        page = None
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            sortcolumn = int(iSortCol_0)
            serversidelogger.debug(f"filter {sSearch} sortcolumn {sortcolumn}")
            page = history.list_history(search=sSearch, sort=HISTORY_COLUMNS[sortcolumn],
                                        descending=sSortDir_0 == "desc", offset=displaystart, limit=displaylength)
            lazylibrarian.HIST_REFRESH = 0
            for item in page.items:
                if item['Progress'] is not None and item['Progress'] < 100:
                    lazylibrarian.HIST_REFRESH = CONFIG.get_int('HIST_REFRESH')
                rows.append(self.history_row(item))
            serversidelogger.debug(f"get_history returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_history filtered {page.matched} from {page.total}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_history: {traceback.format_exc()}')
            rows = []
            page = None

        mydict = {'iTotalDisplayRecords': page.matched if page else 0,
                  'iTotalRecords': page.total if page else 0,
                  'aaData': rows,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @staticmethod
    def history_row(item) -> list:
        """ A history item as the row history.html shows: its fields, progress, rowid and the full date """
        row = [item[field] for field in history.HISTORY_FIELDS]
        # title needs spaces, not dots, for column resizing
        if row[0]:
            row[0] = row[0].replace('.', ' ')
        # provider name needs to be shorter and with spaces for column resizing
        if row[3]:
            row[3] = CONFIG.disp_name(row[3].strip('/'))
        row.append(-1 if item['Progress'] is None else item['Progress'])
        row.append(item['rowid'])
        row.append(row[4])  # keep full datetime for tooltip
        row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

        if row[1] in history.BOOK_TYPES:
            row[1] = (f'<button onclick="bookinfo(\'{row[2]}\')" class="button btn-link text-left" type="button" >'
                      f'{row[1]}</button>')
            if item['AuthorID']:
                row[2] = f'<a href=\'author_page?authorid={item["AuthorID"]}\'">{row[2]}</a>'
        elif row[1] == 'comic':
            row[2] = f'<a href=\'open_comic?comicid={row[2].split("_")[0]}\'">{row[2]}</a>'
        elif row[1] and re.match(r"^[0-9.-]+$", str(row[1])) is not None:  # Magazine
            row[2] = f'<a href=\'open_mag?bookid={row[2]}\'">{row[2]}</a>'
        return row

    @cherrypy.expose
    @require_auth()
    def dlinfo(self, target=None):
        if not target or '^' not in target:
            return ''
        status, rowid = target.split('^')
        try:
            if status == 'Ignored':
                return i18n.gettext('Reason: %(reason)s') % {'reason': history.ignored_reason(rowid)} + '<br>'
            match = history.get_history_item(rowid)
        except NotFoundError:
            return ''
        dltype = history.item_type(match['AuxInfo'])
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
        return message

    @cherrypy.expose
    @require_auth()
    def deletehistory(self, rowid=None):
        logger = logging.getLogger(__name__)
        if not rowid:
            logger.warning("No rowid in deletehistory")
            return
        try:
            history.delete_history_item(rowid)
        except NotFoundError:
            logger.warning(f"No rowid {rowid} in history")

    @cherrypy.expose
    @require_auth()
    def markhistory(self, rowid=None):
        if rowid:
            try:
                history.mark_failed(rowid)
            except NotFoundError:
                logging.getLogger(__name__).warning(f"No rowid {rowid} in history")

    @cherrypy.expose
    @require_auth()
    def clearhistory(self, status=None):
        history.clear_history(status or 'all')
        raise cherrypy.HTTPRedirect("history")

    @cherrypy.expose
    @require_auth()
    def clearblocked(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        num = history.clear_blocked()
        logging.getLogger(__name__).debug(f'Cleared {num} blocked {plural(num, "provider")}')
        return i18n.ngettext('Cleared %(count)s blocked provider', 'Cleared %(count)s blocked providers',
                             num) % {'count': num}

    @cherrypy.expose
    @require_auth()
    def showblocked(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        result = history.blocked_text()
        logging.getLogger(__name__).debug(result)
        return result

    @cherrypy.expose
    @require_auth()
    def cleardownloads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        num = history.clear_download_counts()
        logging.getLogger(__name__).debug(f'Deleted download counter for {num} {plural(num, "provider")}')
        return i18n.ngettext('Deleted download counter for %(count)s provider',
                             'Deleted download counter for %(count)s providers', num) % {'count': num}

    @cherrypy.expose
    @require_auth()
    def showdownloads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        result = ''.join(f"{line['Count']:4d} - {CONFIG.disp_name(line['Provider'].strip('/'))}\n"
                         for line in history.download_counts())
        return result or i18n.gettext('No downloads')
