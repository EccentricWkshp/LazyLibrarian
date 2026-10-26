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
#
# Purpose:
#   The web application uvicorn serves. New routes are FastAPI, the CherryPy pages are mounted
#   inside it as a WSGI app and get every request FastAPI has no route for, until the single
#   page front end replaces them. Everything sits below HTTP_ROOT, as it always has.

from a2wsgi import WSGIMiddleware
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from lazylibrarian.services import system

# CherryPy's own server had a pool of 10 threads, the WSGI bridge gets as many
LEGACY_WORKERS = 10
# FastAPI has OpenTelemetry built in. LazyLibrarian sends no telemetry, so it stays off
# even if a provider or FASTAPI_OTEL_AUTO_CONFIGURE turns up in the environment
NO_TELEMETRY = {'tracing': False, 'metrics': False, 'logs': False, 'operation_spans': False,
                'auto_configure': False}


def url_root(http_root: str) -> str:
    """ HTTP_ROOT as a path prefix: '' or '/something' """
    root = (http_root or '').strip().rstrip('/')
    if root and not root.startswith('/'):
        root = f"/{root}"
    return root


def create_app(http_root: str, legacy_app) -> FastAPI:
    """ The FastAPI app, with the WSGI app legacy_app taking whatever it has no route for """
    app = FastAPI(title='LazyLibrarian', docs_url=None, redoc_url=None, openapi_url=None, telemetry=NO_TELEMETRY)
    router = APIRouter(prefix=url_root(http_root))

    @router.get('/ping', include_in_schema=False)
    def ping():
        """ Health check for Docker and monitoring tools, like Sonarr's /ping. It needs no
        login, so it only says whether LazyLibrarian is up and can read its database """
        if system.database_ok():
            return {'status': 'OK'}
        return JSONResponse({'status': 'Error'}, status_code=503)

    app.include_router(router)
    app.mount('/', WSGIMiddleware(legacy_app, workers=LEGACY_WORKERS))
    return app
