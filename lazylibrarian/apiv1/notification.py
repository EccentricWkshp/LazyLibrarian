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

""" /api/v1/notification, like Sonarr's: the connections, webhooks for now """

from fastapi import APIRouter

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.services import notifications

router = APIRouter(prefix='/notification', tags=['Notification'])


class Header(ApiModel):
    key: str = ''
    value: str = ''


class WebhookSettings(ApiModel):
    url: str = ''
    method: str = 'POST'
    username: str = ''
    password: str = ''
    headers: list[Header] = []


class Notification(ApiModel):
    id: int = 0
    name: str
    implementation: str = 'Webhook'
    settings: WebhookSettings
    on_grab: bool = False
    on_download: bool = False
    on_upgrade: bool = False
    on_download_failure: bool = False
    on_manual_interaction_required: bool = False
    on_health_issue: bool = False
    include_health_warnings: bool = False
    on_health_restored: bool = False
    on_application_update: bool = False


class Message(ApiModel):
    message: str


@router.get('', response_model=list[Notification])
def list_notifications():
    """ The connections. A password is sent back masked, saving it masked keeps it """
    return notifications.list_notifications()


@router.get('/schema', response_model=list[Notification])
def schema():
    """ A new connection of each kind to fill in """
    return notifications.schema()


@router.post('/test', response_model=Message)
def test(notification: Notification):
    """ Send a test event to a connection as it is filled in, saved or not """
    notifications.test(notification.model_dump(), notification.id or None)
    return {'message': 'Sent'}


@router.get('/{notification_id}', response_model=Notification)
def get_notification(notification_id: int):
    return notifications.get(notification_id)


@router.post('', response_model=Notification, status_code=201)
def add_notification(notification: Notification):
    return notifications.save(notification.model_dump())


@router.put('/{notification_id}', response_model=Notification)
def update_notification(notification_id: int, notification: Notification):
    return notifications.save(notification.model_dump(), notification_id)


@router.delete('/{notification_id}', response_model=Message)
def delete_notification(notification_id: int):
    notifications.delete(notification_id)
    return {'message': 'Deleted'}
