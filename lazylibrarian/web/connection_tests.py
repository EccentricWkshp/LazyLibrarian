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

""" The settings page's test buttons: providers, sync accounts, notifiers, download clients and tools """

import cherrypy

from lazylibrarian import i18n
from lazylibrarian.auth import require_auth
from lazylibrarian.formatter import thread_name
from lazylibrarian.services import InvalidRequestError, ServiceError, connections
from lazylibrarian.web.common import BasePages

# how each notifier's test result is reported: its name, and whether it says "notification" or "notice"
NOTIFIER_NAMES = {'pushbullet': 'Pushbullet', 'pushover': 'Pushover', 'telegram': 'Telegram', 'prowl': 'Prowl',
                  'slack': 'Slack'}
CLIENT_NAMES = {'sabnzbd': 'SABnzbd', 'nzbget': 'NZBGet', 'transmission': 'Transmission',
                'qbittorrent': 'qBittorrent', 'utorrent': 'uTorrent', 'rtorrent': 'rTorrent', 'synology': 'Synology'}


def no_cache():
    cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
    thread_name("WEBSERVER")


def bad_parameter(name: str, bad: list) -> str:
    return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': name,
                                                                         'param': ''.join(f'{b} ' for b in bad)}


class ConnectionTestPages(BasePages):
    """ The settings page's test buttons: providers, sync accounts, notifiers, download clients and tools """

    @cherrypy.expose
    @require_auth()
    def testprovider(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("TESTPROVIDER")
        if not kwargs.get('name'):
            return i18n.gettext("Invalid or missing name in testprovider")
        found = connections.test_provider(kwargs['name'], host=kwargs.get('host') or '', api=kwargs.get('api') or '')
        if found['bad']:
            return i18n.gettext("%(name)s test FAILED, bad parameter: %(param)s") % {
                'name': kwargs['name'], 'param': ''.join(f'{b} ' for b in found['bad'])}
        if found['result'] is False:
            return i18n.gettext("%(name)s test FAILED, check debug log") % {'name': found['name']}
        if found['result'] is True:
            return i18n.gettext("%(name)s test PASSED") % {'name': found['name']}
        return i18n.gettext("%(name)s test PASSED, found %(result)s") % {'name': found['name'],
                                                                         'result': found['result']}

    @cherrypy.expose
    @require_auth()
    def test_hcauth(self, **kwargs):
        no_cache()
        return connections.test_hardcover_auth(userid=kwargs.get('userid'), token=kwargs.get('hc_token'))

    @cherrypy.expose
    @require_auth()
    def test_grauth(self, **kwargs):
        no_cache()
        found = connections.test_goodreads_auth(kwargs)
        if found['bad']:
            return i18n.gettext('%(name)s failed, bad parameter: %(param)s') % {
                'name': 'GoodReads', 'param': ''.join(f"{b.removeprefix('gr_')} " for b in found['bad'])}
        return found['result']

    def notifier_test(self, name, kwargs):
        no_cache()
        found = connections.test_notifier(name, kwargs)
        shown = NOTIFIER_NAMES.get(name, name)
        if found['bad']:
            if name == 'custom':
                return i18n.gettext("Custom notification failed, bad parameter: %(param)s") % {
                    'param': ' '.join(found['bad'])}
            if name == 'email':
                return i18n.gettext("Email notification failed, bad parameter: %(param)s") % {
                    'param': ''.join(f'{b} ' for b in found['bad'])}
            return bad_parameter(shown, found['bad'])
        if name in ('telegram', 'prowl'):
            if found['ok']:
                return i18n.gettext("Test %(name)s notice sent successfully") % {'name': shown}
            return i18n.gettext("Test %(name)s notice failed") % {'name': shown}
        if name == 'custom':
            return i18n.gettext("Custom notification successful") if found['ok'] else \
                i18n.gettext("Custom notification failed")
        if name == 'email':
            return i18n.gettext("Email notification successful, check your email") if found['ok'] else \
                i18n.gettext("Email notification failed")
        if name == 'slack':
            if found['ok']:
                return i18n.gettext("%(name)s notification successful") % {'name': shown}
            return i18n.gettext("%(name)s notification failed") % {'name': shown} + f",\n{found['result']}"
        if found['ok']:
            return i18n.gettext("%(name)s notification successful") % {'name': shown} + f",\n{found['result']}"
        return i18n.gettext("%(name)s notification failed") % {'name': shown}

    @cherrypy.expose
    @require_auth()
    def test_pushbullet(self, **kwargs):
        return self.notifier_test('pushbullet', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_pushover(self, **kwargs):
        return self.notifier_test('pushover', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_telegram(self, **kwargs):
        return self.notifier_test('telegram', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_prowl(self, **kwargs):
        return self.notifier_test('prowl', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_slack(self, **kwargs):
        return self.notifier_test('slack', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_custom(self, **kwargs):
        return self.notifier_test('custom', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_email(self, **kwargs):
        return self.notifier_test('email', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_deluge(self, **kwargs):
        no_cache()
        found = connections.test_deluge(kwargs)
        if found['bad']:
            return bad_parameter('Deluge', found['bad'])
        if 'error' in found:
            error = found['error']
            msg = i18n.gettext("Deluge: Daemon connection FAILED") + "\n"
            if 'Connection refused' in str(error):
                return msg + str(error) + i18n.gettext("Check Deluge daemon HOST and PORT settings")
            if 'need more than 1 value' in str(error):
                return msg + i18n.gettext("Invalid USERNAME or PASSWORD")
            return msg + type(error).__name__ + ' ' + str(error)
        if not found['daemon']:
            return found['webui']
        msg = i18n.gettext("Deluge: Daemon connection successful") + "\n"
        if found['checked'] and not found['labels']:
            msg += i18n.gettext("Deluge daemon seems to have no labels set") + "\n"
        for label in found['checked']:
            if label['error']:
                msg += label['error'] + "\n"
            elif label['added']:
                msg += i18n.gettext("Label [%(label)s] was added") % {'label': label['label']} + "\n"
            else:
                msg += i18n.gettext("Label [%(label)s] is valid") % {'label': label['label']} + "\n"
        return msg

    def client_test(self, name, kwargs):
        no_cache()
        found = connections.test_client(name, kwargs)
        if found['bad']:
            return bad_parameter(CLIENT_NAMES[name], found['bad'])
        return found['message']

    @cherrypy.expose
    @require_auth()
    def test_sabnzbd(self, **kwargs):
        return self.client_test('sabnzbd', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_nzbget(self, **kwargs):
        return self.client_test('nzbget', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_transmission(self, **kwargs):
        return self.client_test('transmission', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_qbittorrent(self, **kwargs):
        return self.client_test('qbittorrent', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_utorrent(self, **kwargs):
        return self.client_test('utorrent', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_rtorrent(self, **kwargs):
        return self.client_test('rtorrent', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_synology(self, **kwargs):
        return self.client_test('synology', kwargs)

    @staticmethod
    def tool_version(test, name, command, kwargs):
        no_cache()
        try:
            version = test(kwargs.get('prg'))
        except InvalidRequestError:
            return bad_parameter(name, ['program']).rstrip()
        except ServiceError as e:
            return i18n.gettext("%(command)s failed: %(error)s") % {'command': command, 'error': str(e)}
        return i18n.gettext("Found %(name)s version %(version)s") % {'name': name, 'version': version}

    @cherrypy.expose
    @require_auth()
    def test_ffmpeg(self, **kwargs):
        return self.tool_version(connections.test_ffmpeg, 'ffmpeg', 'ffmpeg -version', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_ebook_convert(self, **kwargs):
        return self.tool_version(connections.test_ebook_convert, 'ebook-convert', 'ebook-convert --version', kwargs)

    @cherrypy.expose
    @require_auth()
    def test_calibredb(self, **kwargs):
        no_cache()
        try:
            return connections.test_calibredb(kwargs.get('prg'))
        except InvalidRequestError:
            return bad_parameter('calibredb', ['program']).rstrip()

    @cherrypy.expose
    @require_auth()
    def test_preprocessor(self, **kwargs):
        no_cache()
        try:
            found = connections.test_preprocessor(kwargs.get('prg'))
        except InvalidRequestError:
            return bad_parameter('preprocessor', ['program']).rstrip()
        if found is None:
            return i18n.gettext("No preprocessor set in config")
        rc, res, err = found
        if rc:
            return i18n.gettext('Preprocessor returned %(rc)s: res[%(res)s] err[%(err)s]') % {
                'rc': rc, 'res': res, 'err': err}
        return res
