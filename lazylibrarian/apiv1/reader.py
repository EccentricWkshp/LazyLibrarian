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

""" /api/v1/read: an eBook's, magazine issue's or comic issue's file to read in the browser or
download, its pages as pictures, and Send to Device. kind is book, issue or comic, a comic issue's
id is comicid_issueid """

from typing import Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from lazylibrarian.apiv1.models import ApiModel
from lazylibrarian.common import mime_type
from lazylibrarian.services import reader

router = APIRouter(prefix='/read', tags=['Read'])
Kind = Literal['book', 'issue', 'comic']


class Reading(ApiModel):
    title: str
    format: str
    # the other formats an eBook is there in
    formats: list[str]
    # pdf for the browser's PDF viewer, pages to show its pages as pictures, epub for the EPUB
    # reader, empty when it can't be read in the browser
    reader: str
    pages: int


class Message(ApiModel):
    message: str


@router.get('/{kind}/{item_id}', response_model=Reading)
def reading(kind: Kind, item_id: str, fmt: str = Query('', alias='format')):
    return reader.reading(kind, item_id, fmt)


@router.get('/{kind}/{item_id}/file')
def item_file(kind: Kind, item_id: str, fmt: str = Query('', alias='format'), download: bool = False):
    """ The file, to open in the browser, or to save when download """
    found = reader.open_file(kind, item_id, fmt)
    return FileResponse(found['path'], media_type=mime_type(found['path']), filename=found['name'],
                        content_disposition_type='attachment' if download else 'inline')


@router.get('/{kind}/{item_id}/page/{number}', responses={200: {'content': {'image/jpeg': {}}}})
def page(kind: Kind, item_id: str, number: int, width: int = 0):
    """ A page, counted from 1, as a JPEG no wider than width when it's given """
    return Response(reader.page(kind, item_id, number, width), media_type='image/jpeg',
                    headers={'Cache-Control': 'private, max-age=3600'})


@router.post('/{kind}/{item_id}/send', response_model=Message)
def send(kind: Kind, item_id: str, fmt: str = Query('', alias='format')):
    """ Email the file to the owner's send-to addresses """
    return {'message': reader.send(kind, item_id, fmt)}
