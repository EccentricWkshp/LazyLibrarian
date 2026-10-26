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

import logging
import os
import subprocess

import cherrypy
from deluge_client import DelugeRPCClient

import lazylibrarian
from lazylibrarian import (
    deluge,
    grsync,
    hc,
    i18n,
    notifiers,
    nzbget,
    qbittorrent,
    rtorrent,
    sabnzbd,
    synology,
    transmission,
    utorrent,
)
from lazylibrarian.auth import require_auth
from lazylibrarian.calibre import calibre_test
from lazylibrarian.common import run_script
from lazylibrarian.config2 import CONFIG, wishlist_type
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import check_int, make_unicode, now, thread_name
from lazylibrarian.providers import test_provider
from lazylibrarian.web.common import BasePages


class ConnectionTestPages(BasePages):
    """ The settings page's test buttons: providers, sync accounts, notifiers, download clients and tools """

    @cherrypy.expose
    @require_auth()
    def testprovider(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("TESTPROVIDER")
        if 'name' in kwargs and kwargs['name']:
            host = ''
            api = ''
            if 'host' in kwargs and kwargs['host']:
                host = kwargs['host']
            if 'api' in kwargs and kwargs['api']:
                api = kwargs['api']
            fail = ''
            if not self.validate_param("provider name", kwargs['name'], ['<', '>', '='], None):
                fail += 'name '
            if not self.validate_param("provider host", host, ['<', '>'], None):
                fail += 'host '
            if not self.validate_param("provider api", api, ['<', '>'], None):
                fail += 'api '
            if fail:
                return i18n.gettext("%(name)s test FAILED, bad parameter: %(param)s") % {
                    'name': kwargs['name'], 'param': fail}

            result, name = test_provider(kwargs['name'], host=host, api=api)
            if result is False:
                msg = i18n.gettext("%(name)s test FAILED, check debug log") % {'name': name}
            elif result is True:
                msg = i18n.gettext("%(name)s test PASSED") % {'name': name}
                CONFIG.save_config_and_backup_old(section=kwargs['name'])
            else:
                wishtype = wishlist_type(host)
                if wishtype:
                    name = f'Wishlist {wishtype} {name}'
                msg = i18n.gettext("%(name)s test PASSED, found %(result)s") % {'name': name, 'result': result}
                CONFIG.save_config_and_backup_old(section=kwargs['name'])
        else:
            msg = i18n.gettext("Invalid or missing name in testprovider")
        return msg

    @cherrypy.expose
    @require_auth()
    def test_hcauth(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        if 'userid' in kwargs and 'hc_token' in kwargs:
            res = hc.test_auth(userid=kwargs['userid'], token=kwargs['hc_token'])
        elif 'userid' in kwargs:
            res = hc.test_auth(userid=kwargs['userid'], token=None)
        elif 'hc_token' in kwargs:
            res = hc.test_auth(userid=None, token=kwargs['hc_token'])
        else:
            res = hc.test_auth(userid=None, token=None)
        if str(res).isnumeric():
            res = f"Pass: whoami={res}"
        return res

    @cherrypy.expose
    @require_auth()
    def test_grauth(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'gr_api' in kwargs:
            if self.validate_param("goodreads api", kwargs['gr_api'], ['<', '>', '='], None):
                CONFIG.set_str('GR_API', kwargs['gr_api'])
            else:
                fail += "api "
        if 'gr_secret' in kwargs:
            if self.validate_param("goodreads secret", kwargs['gr_secret'], ['<', '>', '='], None):
                CONFIG.set_str('GR_SECRET', kwargs['gr_secret'])
            else:
                fail += 'secret '
        if 'gr_oauth_token' in kwargs:
            if self.validate_param("goodreads oauth token", kwargs['gr_oauth_token'], ['<', '>', '='], None):
                CONFIG.set_str('GR_OAUTH_TOKEN', kwargs['gr_oauth_token'])
            else:
                fail += 'oauth_token '
        if 'gr_oauth_secret' in kwargs:
            if self.validate_param("goodreads oauth secret", kwargs['gr_oauth_secret'], ['<', '>', '='], None):
                CONFIG.set_str('GR_OAUTH_SECRET', kwargs['gr_oauth_secret'])
            else:
                fail += "oauth_secret "
        if fail:
            res = i18n.gettext('%(name)s failed, bad parameter: %(param)s') % {'name': 'GoodReads', 'param': fail}
        else:
            res = grsync.test_auth()
        if res.startswith('Pass:'):
            CONFIG.save_config_and_backup_old(section='API')
        return res

    @cherrypy.expose
    @require_auth()
    def test_pushbullet(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'token' in kwargs:
            if self.validate_param("pushbullet token", kwargs['url'], ['<', '>'], None):
                CONFIG.set_str('PUSHBULLET_TOKEN', kwargs['token'])
            else:
                fail += 'token '
        if 'device' in kwargs:
            if self.validate_param("pushbullet device", kwargs['device'], ['<', '>'], None):
                CONFIG.set_str('PUSHBULLET_DEVICEID', kwargs['device'])
            else:
                fail += 'device '
        if fail:
            result = ''
        else:
            result = notifiers.pushbullet_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='PushBullet')
            return i18n.gettext("%(name)s notification successful") % {'name': 'Pushbullet'} + f",\n{result}"
        if fail:
            return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Pushbullet', 'param': fail}
        return i18n.gettext("%(name)s notification failed") % {'name': 'Pushbullet'}

    @cherrypy.expose
    @require_auth()
    def test_pushover(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'apitoken' in kwargs:
            if self.validate_param("pushover apitoken", kwargs['apitoken'], ['<', '>', '='], None):
                CONFIG.set_str('PUSHOVER_APITOKEN', kwargs['apitoken'])
            else:
                fail += 'apitoken '
        if 'keys' in kwargs:
            if self.validate_param("pushover keys", kwargs['keys'], ['<', '>', '='], None):
                CONFIG.set_str('PUSHOVER_KEYS', kwargs['keys'])
            else:
                fail += 'keys '
        if 'priority' in kwargs:
            res = check_int(kwargs['priority'], 0, positive=False)
            if res < -2 or res > 1:
                res = 0
            CONFIG.set_int('PUSHOVER_PRIORITY', res)
        if 'device' in kwargs:
            if self.validate_param("pushover device", kwargs['device'], ['<', '>', '='], None):
                CONFIG.set_str('PUSHOVER_DEVICE', kwargs['device'])
            else:
                fail += 'device '
        if fail:
            result = ''
        else:
            result = notifiers.pushover_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Pushover')
            return i18n.gettext("%(name)s notification successful") % {'name': 'Pushover'} + f",\n{result}"
        if fail:
            return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Pushover', 'param': fail}
        return i18n.gettext("%(name)s notification failed") % {'name': 'Pushover'}

    @cherrypy.expose
    @require_auth()
    def test_telegram(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'token' in kwargs:
            if self.validate_param("telegram token", kwargs['token'], ['<', '>', '='], None):
                CONFIG.set_str('TELEGRAM_TOKEN', kwargs['token'])
            else:
                fail += 'token '
        if 'userid' in kwargs:
            if self.validate_param("telegram userid", kwargs['userid'], ['<', '>', '='], None):
                CONFIG.set_str('TELEGRAM_USERID', kwargs['userid'])
            else:
                fail += 'userid '
        if fail:
            result = ''
        else:
            result = notifiers.telegram_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Telegram')
            return i18n.gettext("Test %(name)s notice sent successfully") % {'name': 'Telegram'}
        if fail:
            return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Telegram', 'param': fail}
        return i18n.gettext("Test %(name)s notice failed") % {'name': 'Telegram'}

    @cherrypy.expose
    @require_auth()
    def test_prowl(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'apikey' in kwargs:
            if self.validate_param("prowl apikey", kwargs['apikey'], ['<', '>', '='], None):
                CONFIG.set_str('PROWL_APIKEY', kwargs['apikey'])
            else:
                fail += 'apikey '
        if 'priority' in kwargs:
            if self.validate_param("prowl priority", kwargs['priority'], ['<', '>', '='], None):
                CONFIG.set_int('PROWL_PRIORITY', check_int(kwargs['priority'], 0))
            else:
                fail += 'priority '
        if fail:
            result = ''
        else:
            result = notifiers.prowl_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Prowl')
            return i18n.gettext("Test %(name)s notice sent successfully") % {'name': 'Prowl'}
        if fail:
            return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Prowl', 'param': fail}
        return i18n.gettext("Test %(name)s notice failed") % {'name': 'Prowl'}

    @cherrypy.expose
    @require_auth()
    def test_slack(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'token' in kwargs:
            if self.validate_param("slack token", kwargs['token'], ['<', '>', '='], None):
                CONFIG.set_str('SLACK_TOKEN', kwargs['token'])
            else:
                fail += 'token '
        if 'url' in kwargs:
            if self.validate_param("slack url", kwargs['url'], ['<', '>', '='], None):
                CONFIG.set_str('SLACK_URL', kwargs['url'])
            else:
                fail += 'url'
        if fail:
            result = ''
        else:
            result = notifiers.slack_notifier.test_notify()
        if result != "ok":
            return i18n.gettext("%(name)s notification failed") % {'name': 'Slack'} + f",\n{result}"
        if fail:
            return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Slack', 'param': fail}
        CONFIG.save_config_and_backup_old(section='Slack')
        return i18n.gettext("%(name)s notification successful") % {'name': 'Slack'}

    @cherrypy.expose
    @require_auth()
    def test_custom(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'script' in kwargs:
            if self.validate_param("custom script", kwargs['script'], ['<', '>', '='], None):
                CONFIG.set_str('CUSTOM_SCRIPT', kwargs['script'])
            else:
                fail = 'script'
        if fail:
            result = ''
        else:
            result = notifiers.custom_notifier.test_notify()
        if not result:
            return i18n.gettext("Custom notification failed")
        if fail:
            return i18n.gettext("Custom notification failed, bad parameter: %(param)s") % {'param': fail}
        CONFIG.save_config_and_backup_old(section='Custom')
        return i18n.gettext("Custom notification successful")

    @cherrypy.expose
    @require_auth()
    def test_email(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'tls' in kwargs:
            if kwargs['tls'] == 'True':
                CONFIG.set_bool('EMAIL_TLS', True)
            else:
                CONFIG.set_bool('EMAIL_TLS', False)
        if 'ssl' in kwargs:
            if kwargs['ssl'] == 'True':
                CONFIG.set_bool('EMAIL_SSL', True)
            else:
                CONFIG.set_bool('EMAIL_SSL', False)
        if 'sendfile' in kwargs:
            if kwargs['sendfile'] == 'True':
                CONFIG.set_bool('EMAIL_SENDFILE_ONDOWNLOAD', True)
            else:
                CONFIG.set_bool('EMAIL_SENDFILE_ONDOWNLOAD', False)
        if 'emailfrom' in kwargs:
            if self.validate_param("email from", kwargs['emailfrom'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_FROM', kwargs['emailfrom'])
            else:
                fail += 'emailfrom '
        if 'emailto' in kwargs:
            if self.validate_param("email to", kwargs['emailto'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_TO', kwargs['emailto'])
            else:
                fail += 'emailto '
        if 'server' in kwargs:
            if self.validate_param("email smtp server", kwargs['server'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_SMTP_SERVER', kwargs['server'])
            else:
                fail += 'server '
        if 'user' in kwargs:
            if self.validate_param("email smtp user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_SMTP_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'password' in kwargs:
        #    if self.validate_param("email password", kwargs['password'], ['<', '>'], None):
        #        CONFIG.set_str('EMAIL_SMTP_PASSWORD', kwargs['password'])
        #    else:
        #        fail += 'password '
        if 'port' in kwargs:
            if self.validate_param("email port", kwargs['port'], ['<', '>', '='], None):
                CONFIG.set_int('EMAIL_SMTP_PORT', check_int(kwargs['port'], 0))
            else:
                fail += 'port '
        if fail:
            result = ''
        else:
            result = notifiers.email_notifier.test_notify()
        if not result:
            return i18n.gettext("Email notification failed")
        if fail:
            return i18n.gettext("Email notification failed, bad parameter: %(param)s") % {'param': fail}
        CONFIG.save_config_and_backup_old(section='Email')
        return i18n.gettext("Email notification successful, check your email")

    @cherrypy.expose
    @require_auth()
    def test_deluge(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        dlcommslogger = logging.getLogger('special.dlcomms')
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("deluge host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'base' in kwargs:
            if self.validate_param("deluge base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'cert' in kwargs:
            if self.validate_param("deluge cert", kwargs['cert'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_CERT', kwargs['cert'])
            else:
                fail += 'cert '
        if 'port' in kwargs:
            CONFIG.set_int('DELUGE_PORT', check_int(kwargs['port'], 0))
        # if 'pwd' in kwargs:
        #    if self.validate_param("deluge pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('DELUGE_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'label' in kwargs:
            if self.validate_param("deluge label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if 'user' in kwargs:
            if self.validate_param("deluge user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_USER', kwargs['user'])
            else:
                fail += 'user '
        if fail:
            return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Deluge', 'param': fail}

        try:
            if not CONFIG['DELUGE_USER']:
                # no username, talk to the webui
                msg, ok = deluge.check_link()
                if not ok:
                    return msg
            else:
                # if there's a username, talk to the daemon directly
                # if daemon, no cert used
                CONFIG.set_str('DELUGE_CERT', '')
                # and host must not contain http:// or https://
                host = CONFIG['DELUGE_HOST']
                host = host.replace('https://', '').replace('http://', '')
                CONFIG.set_str('DELUGE_HOST', host)
                client = DelugeRPCClient(CONFIG['DELUGE_HOST'],
                                         check_int(CONFIG['DELUGE_PORT'], 0),
                                         CONFIG['DELUGE_USER'],
                                         CONFIG['DELUGE_PASS'])
                client.connect()
                msg = i18n.gettext("Deluge: Daemon connection successful") + "\n"
                if CONFIG['DELUGE_LABEL']:
                    labels = client.call('label.get_labels')
                    if labels:
                        dlcommslogger.debug(f"Valid labels: {str(labels)}")
                    else:
                        msg += i18n.gettext("Deluge daemon seems to have no labels set") + "\n"

                    mylabel = CONFIG['DELUGE_LABEL'].lower()
                    if mylabel != CONFIG['DELUGE_LABEL']:
                        CONFIG.set_str('DELUGE_LABEL', mylabel)

                    labels = [make_unicode(s) for s in labels]
                    if mylabel not in labels:
                        res = client.call('label.add', mylabel)
                        if not res:
                            msg += i18n.gettext("Label [%(label)s] was added") % {'label': CONFIG['DELUGE_LABEL']}
                        else:
                            msg = str(res)
                    else:
                        msg += i18n.gettext("Label [%(label)s] is valid") % {'label': CONFIG["DELUGE_LABEL"]}
            # success, save settings
            CONFIG.save_config_and_backup_old(section='DELUGE')
            return msg

        except Exception as e:
            msg = i18n.gettext("Deluge: Daemon connection FAILED") + "\n"
            if 'Connection refused' in str(e):
                msg += str(e)
                msg += i18n.gettext("Check Deluge daemon HOST and PORT settings")
            elif 'need more than 1 value' in str(e):
                msg += i18n.gettext("Invalid USERNAME or PASSWORD")
            else:
                msg += type(e).__name__ + ' ' + str(e)
            return msg

    @cherrypy.expose
    @require_auth()
    def test_sabnzbd(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("sab host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('SAB_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("sab user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("sab pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('SAB_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'api' in kwargs:
            if self.validate_param("sab api", kwargs['api'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_API', kwargs['api'])
            else:
                fail += 'api '
        if 'cat' in kwargs:
            if self.validate_param("sab cat", kwargs['cat'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_CAT', kwargs['cat'])
            else:
                fail += 'cat '
        if 'subdir' in kwargs:
            if self.validate_param("sab subdir", kwargs['subdir'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_SUBDIR', kwargs['subdir'])
            else:
                fail += 'subdir '
        if fail:
            msg = i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'SABnzbd', 'param': fail}
        else:
            msg, ok = sabnzbd.check_link()
            if ok:
                CONFIG.save_config_and_backup_old(section='sab_nzbd')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_nzbget(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("nzbget host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('NZBGET_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('NZBGET_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("nzbget user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('NZBGET_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("nzbget pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('NZBGET_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'cat' in kwargs:
            if self.validate_param("nzbget category", kwargs['cat'], ['<', '>', '='], None):
                CONFIG.set_str('NZBGET_CATEGORY', kwargs['cat'])
            else:
                fail += 'cat '
        if 'pri' in kwargs:
            CONFIG.set_int('NZBGET_PRIORITY', check_int(kwargs['pri'], 0))
        if fail:
            msg = i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'NZBGet', 'param': fail}
        else:
            msg, ok = nzbget.check_link()
            if ok:
                CONFIG.save_config_and_backup_old(section='NZBGet')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_transmission(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("transmission host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('TRANSMISSION_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'base' in kwargs:
            if self.validate_param("transmission base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('TRANSMISSION_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'port' in kwargs:
            CONFIG.set_int('TRANSMISSION_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("transmission user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('TRANSMISSION_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("transmission pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('TRANSMISSION_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if fail:
            msg = i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Transmission', 'param': fail}
        else:
            msg, ok = transmission.check_link()
            if ok:
                CONFIG.save_config_and_backup_old(section='TRANSMISSION')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_qbittorrent(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("qbit host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('QBITTORRENT_PORT', check_int(kwargs['port'], 0))
        if 'base' in kwargs:
            if self.validate_param("qbit base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'user' in kwargs:
            if self.validate_param("qbit user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("qbit password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('QBITTORRENT_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'label' in kwargs:
            if self.validate_param("qbit label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if 'ignore_ssl' in kwargs:
            CONFIG.set_bool('QBITTORRENT_IGNORE_SSL', kwargs['ignore_ssl'] == '1')
        if fail:
            msg = i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'qBittorrent', 'param': fail}
        else:
            msg, ok = qbittorrent.check_link()
            if ok:
                CONFIG.save_config_and_backup_old(section='QBITTORRENT')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_utorrent(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("utorrent host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('UTORRENT_PORT', check_int(kwargs['port'], 0))
        if 'base' in kwargs:
            if self.validate_param("utorrent base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'user' in kwargs:
            if self.validate_param("utorrent user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("utorrent password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('UTORRENT_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'label' in kwargs:
            if self.validate_param("utorrent label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if fail:
            msg = i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'uTorrent', 'param': fail}
        else:
            msg, ok = utorrent.check_link()
            if ok:
                CONFIG.save_config_and_backup_old(section='UTORRENT')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_rtorrent(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("rtorrent host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'dir' in kwargs:
            if self.validate_param("rtorrent dir", kwargs['dir'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_DIR', kwargs['dir'])
            else:
                fail += 'dir '
        if 'user' in kwargs:
            if self.validate_param("rtorrent user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("rtorrent password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('RTORRENT_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'psaaword '
        if 'label' in kwargs:
            if self.validate_param("rtorrent label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if fail:
            msg = i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'rTorrent', 'param': fail}
        else:
            msg, ok = rtorrent.check_link()
            if ok:
                CONFIG.save_config_and_backup_old(section='RTORRENT')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_synology(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("synology host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('SYNOLOGY_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('SYNOLOGY_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("synology user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('SYNOLOGY_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("synology password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('SYNOLOGY_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'dir' in kwargs:
            if self.validate_param("synology dir", kwargs['dir'], ['<', '>', '='], None):
                CONFIG.set_str('SYNOLOGY_DIR', kwargs['dir'])
            else:
                fail += 'dir '
        if fail:
            msg = i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'Synology', 'param': fail}
        else:
            msg, ok = synology.check_link()
            if ok:
                CONFIG.save_config_and_backup_old(section='SYNOLOGY')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_ffmpeg(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        postprocesslogger = logging.getLogger('special.postprocess')
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("ffmpeg program", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('FFMPEG', kwargs['prg'])
            else:
                return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'ffmpeg', 'param': 'program'}
        ffmpeg = CONFIG['FFMPEG']
        try:
            if postprocesslogger.isEnabledFor(logging.DEBUG):
                ffmpeg_env = os.environ.copy()
                ffmpeg_env["FFREPORT"] = DIRS.get_logfile(
                    f"ffmpeg-test-{now().replace(':', '-').replace(' ', '-')}.log")
                params = [ffmpeg, "-version", "-report"]
            else:
                params = [ffmpeg, "-version"]
                ffmpeg_env = None

            if os.name != 'nt':
                res = subprocess.check_output(params, preexec_fn=lambda: os.nice(10),
                                              stderr=subprocess.STDOUT, env=ffmpeg_env)
            else:
                res = subprocess.check_output(params, stderr=subprocess.STDOUT, env=ffmpeg_env)

            ff_ver = make_unicode(res).strip().split("Copyright")[0].split()[-1]
            lazylibrarian.FFMPEGVER = ff_ver
            return i18n.gettext("Found %(name)s version %(version)s") % {'name': 'ffmpeg', 'version': ff_ver}
        except Exception as e:
            lazylibrarian.FFMPEGVER = None
            return i18n.gettext("%(command)s failed: %(error)s") % {
                'command': 'ffmpeg -version', 'error': f'{type(e).__name__} {str(e)}'}

    @cherrypy.expose
    @require_auth()
    def test_ebook_convert(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("ebook convert", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('EBOOK_CONVERT', kwargs['prg'])
            else:
                return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'ebook-convert', 'param': 'program'}

        prg = CONFIG['EBOOK_CONVERT']
        try:
            params = [prg, "--version"]
            res = subprocess.check_output(params, stderr=subprocess.STDOUT)
            res = make_unicode(res).strip().split("(")[1].split(")")[0]
            return i18n.gettext("Found %(name)s version %(version)s") % {'name': 'ebook-convert', 'version': res}
        except Exception as e:
            return i18n.gettext("%(command)s failed: %(error)s") % {
                'command': 'ebook-convert --version', 'error': f'{type(e).__name__} {str(e)}'}

    @cherrypy.expose
    @require_auth()
    def test_calibredb(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("calibredb", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('IMP_CALIBREDB', kwargs['prg'])
            else:
                return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'calibredb', 'param': 'program'}
        return calibre_test()

    @cherrypy.expose
    @require_auth()
    def test_preprocessor(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("preprocessor", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('EXT_PREPROCESS', kwargs['prg'])
            else:
                return i18n.gettext("%(name)s failed, bad parameter: %(param)s") % {'name': 'preprocessor', 'param': 'program'}
        if len(CONFIG['EXT_PREPROCESS']):
            params = [CONFIG['EXT_PREPROCESS'], 'test', '']
            rc, res, err = run_script(params)
            if rc:
                return i18n.gettext('Preprocessor returned %(rc)s: res[%(res)s] err[%(err)s]') % {
                    'rc': rc, 'res': res, 'err': err}
        else:
            return i18n.gettext("No preprocessor set in config")
        return res
