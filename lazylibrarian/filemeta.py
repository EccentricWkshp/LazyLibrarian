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

""" What an issue's or book's file says about itself: a PDF's document info, an EPUB's package
metadata and a comic archive's ComicInfo.xml. Each gives what it has of title, series, number,
volume, date (YYYY-MM-DD, or as much of it as there is), description, publisher, language and
pages; LazyLibrarian's own tags, written when it tags a PDF, win over the rest """

import logging
import re
import zipfile
from xml.etree import ElementTree

import lazylibrarian
from lazylibrarian import pages
from lazylibrarian.filesystem import splitext, syspath

FIELDS = ('title', 'series', 'number', 'volume', 'date', 'description', 'publisher', 'language', 'pages')


def _text(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _plain(html: str) -> str:
    """ A description without its markup """
    return _text(re.sub(r'<[^>]+>', ' ', html or ''))


def _date(value) -> str:
    """ A date as far as it goes, YYYY, YYYY-MM or YYYY-MM-DD, from an ISO date or a PDF's D:YYYYMMDD """
    value = _text(value)
    if value.startswith('D:'):
        value = value[2:]
    found = re.match(r'(\d{4})(?:-?(\d{2}))?(?:-?(\d{2}))?', value)
    if not found or not 1000 < int(found.group(1)) < 3000:
        return ''
    return '-'.join(part for part in found.groups() if part and part != '00')


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def pdf_metadata(path) -> dict:
    from pypdf import PdfReader  # noqa: PLC0415, only PDFs need it
    found = {}
    reader = PdfReader(syspath(path))
    info = dict(reader.metadata or {})
    found['title'] = _text(info.get('/Title'))
    found['description'] = _text(info.get('/Subject'))
    found['publisher'] = _text(info.get('/Author'))
    found['date'] = _date(info.get('/CreationDate'))
    found['language'] = _text(info.get('/Languages'))
    # tagged by LazyLibrarian
    if info.get('/LL_Title'):
        found['series'] = _text(info.get('/LL_Title'))
    if info.get('/LL_Issue'):
        issue = _text(info.get('/LL_Issue'))
        found['date' if _date(issue) and '-' in issue else 'number'] = issue
    found['pages'] = len(reader.pages)
    return found


def epub_metadata(path) -> dict:
    found = {}
    with zipfile.ZipFile(syspath(path)) as epub:
        _name, opf = pages.epub_package(epub)
    for element in opf.iter():
        tag, value = _local(element.tag), element.text
        if tag == 'title' and not found.get('title'):
            found['title'] = _text(value)
        elif tag == 'description':
            found['description'] = _plain(value)
        elif tag == 'publisher':
            found['publisher'] = _text(value)
        elif tag == 'date' and not found.get('date'):
            found['date'] = _date(value)
        elif tag == 'language' and not found.get('language'):
            found['language'] = _text(value)
        elif tag == 'meta':
            name, content = element.get('name') or element.get('property') or '', element.get('content')
            content = content if content is not None else value
            if name in ('calibre:series', 'belongs-to-collection'):
                found['series'] = _text(content)
            elif name in ('calibre:series_index', 'group-position'):
                number = _text(content)
                found['number'] = number[:-2] if number.endswith('.0') else number
    return found


def _comicinfo(names: list[str], read) -> dict:
    name = next((name for name in names if name.lower().rsplit('/', 1)[-1] == 'comicinfo.xml'), '')
    if not name:
        return {}
    info = {_local(element.tag): _text(element.text) for element in ElementTree.fromstring(read(name))}
    date = '-'.join(f"{int(part):02d}" if index else part for index, part in
                    enumerate(info[key] for key in ('Year', 'Month', 'Day') if info.get(key, '').isdigit()))
    found = {'title': info.get('Title', ''), 'series': info.get('Series', ''), 'number': info.get('Number', ''),
             'volume': info.get('Volume', ''), 'date': _date(date), 'description': _plain(info.get('Summary', '')),
             'publisher': info.get('Publisher', ''), 'language': info.get('LanguageISO', '')}
    if info.get('PageCount', '').isdigit():
        found['pages'] = int(info['PageCount'])
    return found


def archive_metadata(path) -> dict:
    extn = splitext(path)[1].lower()
    if extn == '.cbz':
        with zipfile.ZipFile(syspath(path)) as archive:
            found = _comicinfo(archive.namelist(), archive.read)
    elif extn == '.cbr' and lazylibrarian.UNRARLIB == 1:
        archive = lazylibrarian.RARFILE.RarFile(syspath(path))
        found = _comicinfo(archive.namelist(), archive.read)
    elif extn == '.cbr' and lazylibrarian.UNRARLIB == 2:
        archive = lazylibrarian.RARFILE(syspath(path))
        found = _comicinfo([member.filename for member in archive.infoiter()],
                           lambda name: archive.read_files(name)[0][1])
    else:
        found = {}
    if not found.get('pages'):
        found['pages'] = pages.page_count(path)
    return found


def issue_details(meta: dict, issuedate: str = '') -> tuple[str, int, str]:
    """ An issue's Description, Pages and IssueNumber columns from what its file says. The number is
    left out when the issue is known by its number already """
    number = '' if str(issuedate).isdigit() else meta['number']
    if number and meta['volume']:
        number = f"Vol {meta['volume']} #{number}"
    return meta['description'], meta['pages'], number


def read_metadata(path) -> dict:
    """ What a file says about itself, every field in FIELDS, empty (0 for pages) where it says nothing
    or can't be read """
    found = {}
    extn = splitext(str(path))[1].lower()
    try:
        if extn == '.pdf':
            found = pdf_metadata(path)
        elif extn == '.epub':
            found = epub_metadata(path)
        elif extn in pages.ARCHIVES:
            found = archive_metadata(path)
    except Exception as why:
        logging.getLogger(__name__).debug(f"Can't read the metadata of {path}: {type(why).__name__} {why}")
    return {field: found.get(field) or (0 if field == 'pages' else '') for field in FIELDS}
