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

""" Updates, like Sonarr's System, Updates: the version running, what has changed since, from the
scheduled check for updates, and installing it, or how to when LazyLibrarian can't do it itself """

import datetime

import lazylibrarian
from lazylibrarian import database
from lazylibrarian.common import docker
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import InvalidRequestError, system

# versioncheck marks a change that has to be installed by hand like this
MANUAL = '** MANUAL **'


def why_not_install() -> str:
    """ Why LazyLibrarian can't update itself, '' when it can """
    install = CONFIG['INSTALL_TYPE'] or ''
    if docker():
        return 'LazyLibrarian is running in Docker. Pull the new image and recreate the container to update it'
    if install.startswith('package'):
        return 'LazyLibrarian was installed as a package. Update it with your package manager'
    if install == 'win':
        return "Updating the Windows version isn't supported, download the new version instead"
    if install not in ('git', 'source'):
        return "LazyLibrarian doesn't know how it was installed. Run it with --update to find out"
    return ''


def _last_checked() -> str | None:
    db = database.DBConnection()
    try:
        row = db.match("SELECT Finish FROM jobs WHERE Name='VERSIONCHECK'")
    finally:
        db.close()
    if not row or not row['Finish']:
        return None
    return datetime.datetime.fromtimestamp(row['Finish']).astimezone().isoformat(timespec='seconds')


def info() -> dict:
    """ The version running and what's new, as the last check for updates found it """
    behind = CONFIG.get_int('COMMITS_BEHIND')
    lines = [line.strip() for line in (lazylibrarian.COMMIT_LIST or '').splitlines() if line.strip()]
    manual = any(MANUAL in line for line in lines)
    why_not = why_not_install()
    if behind > 0 and manual and not why_not:
        why_not = 'This update has to be installed by hand, see the changes'
    return {'version': CONFIG['CURRENT_VERSION'], 'latest_version': CONFIG['LATEST_VERSION'],
            'branch': CONFIG['GIT_BRANCH'], 'install_type': CONFIG['INSTALL_TYPE'], 'behind': behind,
            # newest first. When the version isn't known, they say so instead
            'changes': lines if behind > 0 else [], 'message': '' if behind >= 0 else ' '.join(lines),
            'can_install': behind > 0 and not why_not, 'why_not': why_not, 'last_checked': _last_checked(),
            'repo': f"https://{CONFIG['GIT_HOST']}/{CONFIG['GIT_USER']}/{CONFIG['GIT_REPO']}"}


def install() -> str:
    """ Update now: LazyLibrarian backs up, updates and restarts itself """
    found = info()
    if not found['can_install']:
        raise InvalidRequestError(found['why_not'] or 'LazyLibrarian is up to date')
    system.request_stop('update')
    return 'Updating, LazyLibrarian will restart'
