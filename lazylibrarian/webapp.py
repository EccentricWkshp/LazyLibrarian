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
#   FastAPI routes get the same login, whitelist and cross-site checks as the pages, from
#   auth.py, and /api/v1 also takes the API keys.

import json
import logging
import os
import traceback
from http import HTTPStatus

from a2wsgi import WSGIMiddleware
from fastapi import APIRouter, Depends, FastAPI, Request, Security
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.staticfiles import StaticFiles

from lazylibrarian import apiv1, auth
from lazylibrarian.common import url_root
from lazylibrarian.config2 import CONFIG
from lazylibrarian.services import NotFoundError, ServiceError, system

# CherryPy's own server had a pool of 10 threads, the WSGI bridge gets as many
LEGACY_WORKERS = 10
# FastAPI has OpenTelemetry built in. LazyLibrarian sends no telemetry, so it stays off
# even if a provider or FASTAPI_OTEL_AUTO_CONFIGURE turns up in the environment
NO_TELEMETRY = {'tracing': False, 'metrics': False, 'logs': False, 'operation_spans': False,
                'auto_configure': False}

# the same two ways to send a key as the old /api, the header keeps it out of urls and logs
API_KEY_HEADER = APIKeyHeader(name='X-Api-Key', auto_error=False, description='The API key from Settings')
API_KEY_QUERY = APIKeyQuery(name='apikey', auto_error=False, description='The API key, if a header is no use')

# The single page front end, built from frontend/ into data/ui. Its pages are below these paths
UI_PAGES = ('activity', 'wanted', 'system', 'settings', 'add', 'authors', 'author', 'books', 'audio', 'magazines',
            'magazine', 'comics', 'comic', 'series', 'book', 'manage', 'read')
# Bootswatch themes the old pages can have that are dark, the new pages follow them
DARK_THEMES = frozenset(('slate', 'darkly', 'cyborg', 'superhero', 'solar', 'vapor', 'quartz'))


def ui_page(ui_dir: str, root: str) -> str:
    """ The front end's index.html, told where it is: the base its files are found from, and the
    settings it starts with """
    with open(os.path.join(ui_dir, 'index.html'), encoding='utf-8') as f:
        page = f.read()
    settings = {'urlBase': root, 'theme': 'dark' if CONFIG['BOOKSTRAP_THEME'] in DARK_THEMES else 'light',
                'tabs': {tab.lower(): CONFIG.get_bool(f'{tab}_TAB') for tab in ('EBOOK', 'AUDIO', 'SERIES', 'MAG',
                                                                                 'COMIC')},
                # the libraries' RSS feeds are there
                'rss': CONFIG.get_bool('RSS_ENABLED')}
    # </ can't end the script early, json.dumps leaves / alone
    script = json.dumps(settings).replace('</', '<\\/')
    return page.replace('<head>', f'<head>\n    <base href="{root}/ui/">\n'
                                  f'    <link rel="icon" href="{root}/favicon.ico">\n'
                                  f'    <script>window.LazyLibrarian = {script};</script>', 1)


def web_request(request: Request, root: str) -> auth.WebRequest:
    """ A FastAPI request as the checks in auth.py see it """
    path = request.url.path
    below = path[len(root):] if root and path.startswith(root) else path
    query = request.url.query
    return auth.WebRequest(method=request.method, path=below or '/', target=f"{path}?{query}" if query else path,
                           headers=request.headers, cookies=request.cookies,
                           peer_ip=request.client.host if request.client else '',
                           base=f"{request.url.scheme}://{request.url.netloc}")


def create_app(http_root: str, legacy_app, ui_dir: str = '') -> FastAPI:
    """ The FastAPI app, with the WSGI app legacy_app taking whatever it has no route for, and the
    front end built into ui_dir """
    root = url_root(http_root)
    app = FastAPI(title='LazyLibrarian', version='1', docs_url=None, redoc_url=None, openapi_url=None,
                  telemetry=NO_TELEMETRY)

    def api_access(request: Request, header_key: str | None = Security(API_KEY_HEADER),
                   query_key: str | None = Security(API_KEY_QUERY)) -> auth.Access:
        """ An API key, or the login the pages use. The read-only key can only read """
        key = header_key or query_key
        if not key:
            return auth.check_access(web_request(request, root), page_load=False)
        level = auth.api_key_access(key)
        if not level:
            raise auth.AccessDeniedError(401, 'Incorrect API key, or the API is not enabled')
        if level == 'read' and request.method not in ('GET', 'HEAD'):
            raise auth.AccessDeniedError(403, 'The read-only API key can only read')
        return auth.Access('apikey', None, False)

    def page_access(request: Request) -> auth.Access:
        """ The login the pages need, a browser that hasn't got one goes to the login page """
        return auth.check_access(web_request(request, root), page_load=True)

    @app.exception_handler(auth.AccessDeniedError)
    async def access_denied(request: Request, exc: auth.AccessDeniedError):
        if exc.redirect:
            return RedirectResponse(exc.redirect, status_code=303)
        return JSONResponse({'detail': exc.message or HTTPStatus(exc.status).phrase}, status_code=exc.status,
                            headers=exc.headers)

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError):
        return JSONResponse({'detail': str(exc)}, status_code=404)

    @app.exception_handler(ServiceError)
    async def bad_request(request: Request, exc: ServiceError):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        """ What went wrong, in the log with where, and to the page as a message it can show """
        logging.getLogger(__name__).error(f"{request.method} {request.url.path} failed: "
                                          f"{''.join(traceback.format_exception(exc))}")
        return JSONResponse({'detail': f"{type(exc).__name__}: {exc}. The log has more"}, status_code=500)

    router = APIRouter(prefix=root)

    @router.get('/ping', include_in_schema=False)
    def ping():
        """ Health check for Docker and monitoring tools, like Sonarr's /ping. It needs no
        login, so it only says whether LazyLibrarian is up and can read its database """
        if system.database_ok():
            return {'status': 'OK'}
        return JSONResponse({'status': 'Error'}, status_code=503)

    @router.get('/api/v1/openapi.json', include_in_schema=False, dependencies=[Depends(api_access)])
    def openapi():
        return app.openapi()

    @router.get('/api/v1/docs', include_in_schema=False, dependencies=[Depends(page_access)])
    def docs():
        return get_swagger_ui_html(openapi_url=f"{root}/api/v1/openapi.json", title='LazyLibrarian API')

    router.include_router(apiv1.router, dependencies=[Depends(api_access)])

    if ui_dir and os.path.isfile(os.path.join(ui_dir, 'index.html')):
        def ui(_page: str = '', _access=Depends(page_access)):
            return HTMLResponse(ui_page(ui_dir, root), headers={'Cache-Control': 'no-cache'})

        for page in UI_PAGES:
            router.add_api_route(f'/{page}', ui, include_in_schema=False)
            router.add_api_route(f'/{page}/{{_page:path}}', ui, include_in_schema=False)
    app.include_router(router)
    if ui_dir and os.path.isdir(os.path.join(ui_dir, 'assets')):
        # the scripts and styles, with a hash in each name. Like the old pages' files they need
        # no login, the login page itself will use them
        app.mount(f'{root}/ui/assets', StaticFiles(directory=os.path.join(ui_dir, 'assets')), name='ui')
    app.mount('/', WSGIMiddleware(legacy_app, workers=LEGACY_WORKERS))
    return app
