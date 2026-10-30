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

""" Editing an author, book, magazine, issue, comic or series, for the edit dialogs of the new pages,
as Sonarr's Edit Series: what each can change, and saving it through the services the old edit pages
use. Each save returns what to tell the user """

import logging
import re
import uuid

import lazylibrarian
from lazylibrarian import database, magreleases, wikidata
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, plural
from lazylibrarian.services import (
    InvalidRequestError,
    NotFoundError,
    authors,
    books,
    comics,
    magazines,
    series,
)
from lazylibrarian.services.users import plain_text

# what a title or name can't have, as the old pages check
NAME_TOKENS = ('<', '>', '=')
# the covers a book can be given, as book_for_edit finds them
COVER_SOURCES = ('cover', 'goodreads', 'librarything', 'openlibrary', 'googleisbn', 'bing', 'googleimage')


def _text(value) -> str:
    return '' if value is None else str(value)


def _check_name(what: str, value: str):
    if not plain_text(value, NAME_TOKENS):
        raise InvalidRequestError(f"The {what} can't have {' '.join(NAME_TOKENS)} in it")


def _changes(changed: str, name: str) -> str:
    changed = changed.strip()
    return f"{name}: {changed} changed" if changed else f"{name} wasn't changed"


# --- authors

def author_sources(author: dict) -> list[dict]:
    """ The sources an author can be linked to, best first: each one's id for them, whether it's
    switched on, and whether it's the one their link and badge use. Without one chosen, the first
    one linked is, as the author page shows """
    from lazylibrarian.startup import prioritized_infosources  # noqa: PLC0415, it imports most of LazyLibrarian

    linkable = [(name, src) for name, src in prioritized_infosources() if src.get('author_link')]
    primary = author.get('PrimarySource') or next(
        (name for name, src in linkable if author.get(src['author_key'])), '')
    return [{'source': name, 'id': _text(author.get(src['author_key'])), 'enabled': bool(CONFIG[src['enabled']]),
             'primary': name == primary and bool(author.get(src['author_key']))} for name, src in linkable]


def author_for_edit(authorid) -> dict:
    author = authors.get_author(authorid)
    return {'id': author['AuthorID'], 'name': _text(author['AuthorName']), 'born': _text(author['AuthorBorn']),
            'died': _text(author['AuthorDeath']), 'aka': _text(author['AKA']),
            'amazon_url': _text(author['AmazonAuthorURL']), 'about': _text(author['About']),
            'locked': bool(check_int(author['Manual'], 0)), 'reason': _text(author['Reason']),
            'image': _text(author['AuthorImg']), 'sources': author_sources(author)}


def save_author(authorid, values: dict) -> str:
    """ Change an author. image is a link or file for their picture, 'none' for none; found is one of the
    pictures author_images found, which wins over image """
    author = authors.get_author(authorid)
    name = _text(values.get('name', author['AuthorName'])).strip()
    if not name:
        raise InvalidRequestError("An author needs a name")
    _check_name('name', name)
    if name != author['AuthorName']:
        db = database.DBConnection()
        try:
            if db.match('SELECT AuthorID from authors WHERE AuthorName=?', (name,)):
                raise InvalidRequestError(f"{name} is another author already")
        finally:
            db.close()
    found = _text(values.get('found'))
    image = _text(values.get('image')).strip()
    cover = found if found else ('manual' if image else 'current')

    def date(key, column):
        if key not in values:
            return author[column]
        return _text(values[key]).strip() or None

    edited = authors.update_author(
        authorid, name, date('born', 'AuthorBorn'), date('died', 'AuthorDeath'), image=image,
        about=_text(values.get('about', author['About'])),
        manual=bool(values['locked']) if 'locked' in values else bool(check_int(author['Manual'], 0)),
        aka=_text(values.get('aka', author['AKA'])), amazon_url=_text(values.get('amazon_url', author['AmazonAuthorURL'])),
        cover=cover)
    return _changes(edited, name)


def author_images(authorid) -> list[dict]:
    """ Pictures of the author found online, to choose one from """
    authors.get_author(authorid)
    return [{'name': name, 'path': path} for name, path in authors.author_images(authorid)]


# --- books

def _book_series(bookid) -> list[dict]:
    db = database.DBConnection()
    try:
        return [{'name': row['SeriesName'], 'number': _text(row['SeriesNum'])} for row in db.select(
            "SELECT SeriesName, SeriesNum from member,series WHERE series.SeriesID=member.SeriesID and BookID=?",
            (bookid,))]
    finally:
        db.close()


def _book_image(bookid) -> str:
    db = database.DBConnection()
    try:
        row = db.match('SELECT BookImg from books WHERE BookID=?', (bookid,))
    finally:
        db.close()
    return _text(row['BookImg']) if row else ''


def book_for_edit(bookid) -> dict:
    edit = books.book_for_edit(bookid, 'AudioBook')
    book = edit['book']
    return {'id': book['BookID'], 'title': _text(book['BookName']), 'subtitle': _text(book['BookSub']),
            'author': _text(book['AuthorName']), 'genre': _text(book['BookGenre']), 'language': _text(book['BookLang']),
            'release_date': _text(book['BookDate']), 'isbn': _text(book['BookIsbn']), 'work_id': _text(book['WorkID']),
            'narrator': _text(book.get('Narrator')), 'description': _text(book['BookDesc']),
            'locked': bool(check_int(book['Manual'], 0)),
            'added_by': f"{_text(book['BookAdded'])} {_text(book['ScanResult'])}".strip(),
            'source_ids': {name: _text(book.get(column)) for name, column in book_source_columns().items()},
            'own_source': next((name for name, column in book_source_columns().items()
                                if _text(book.get(column)) == _text(book['BookID'])), ''),
            'match_sources': match_sources(),
            'series': _book_series(bookid), 'image': _book_image(bookid),
            'author_series': [row['SeriesName'] for row in edit['series']],
            'authors': [row['AuthorName'] for row in edit['authors']],
            'opf_fields': [{'name': name, 'value': _text(value)} for name, value in edit['replaces']]}


def book_source_columns() -> dict[str, str]:
    """ Each info source's column of a book's id there, by the source's name """
    return {name: src['book_key'] for name, src in lazylibrarian.INFOSOURCES.items() if src.get('book_key')}


def match_sources() -> list[str]:
    """ The info sources switched on, the one searched first first """
    on = [name for name in book_source_columns() if CONFIG[lazylibrarian.INFOSOURCES[name]['enabled']]]
    return sorted(on, key=lambda name: name != CONFIG['BOOK_API'])


# the last Fix Match search's books, by (book, source, id), to apply the one chosen
_matches: dict[tuple, dict] = {}


def book_source_search(bookid, source: str, term: str = '') -> list[dict]:
    """ Fix Match, as Plex's Fix Match, Jellyfin's Identify or Audiobookshelf's Match: the books an info
    source finds for the book's author and title, or term (an ISBN too), each with what it would
    give the book. Apply one with match_book """
    from lazylibrarian.importer import search_for  # noqa: PLC0415, it imports most of LazyLibrarian
    if source not in book_source_columns():
        raise InvalidRequestError(f"The source is one of {', '.join(book_source_columns())}")
    current = book_for_edit(bookid)
    if not CONFIG[lazylibrarian.INFOSOURCES[source]['enabled']]:
        raise InvalidRequestError(f"{source} is switched off in Settings, Metadata")
    found = []
    # the best matches are on the first pages, a paged source has hundreds more
    for result in (search_for(term.strip() or f"{current['author']} {current['title']}", source,
                              max_pages=2) or [])[:25]:
        if not result.get('bookid'):
            continue
        publisher, date = _text(result.get('bookpub')), _text(result.get('bookdate'))
        if publisher.isdigit():  # OpenLibrary gives the year first published as the publisher
            publisher, date = '', date or publisher
        match = {'source': source, 'id': _text(result['bookid']), 'title': _text(result.get('bookname')),
                 'subtitle': _text(result.get('booksub')), 'author': _text(result.get('authorname')),
                 'date': date[:10], 'publisher': publisher, 'isbn': _text(result.get('bookisbn')),
                 'language': _text(result.get('booklang')), 'pages': check_int(result.get('bookpages'), 0),
                 'genres': _text(result.get('bookgenre')), 'description': _text(result.get('bookdesc')),
                 # OpenLibrary's search gives a thumbnail, its large size is the cover to take
                 'cover': re.sub(r'(covers\.openlibrary\.org/.*)-S\.jpg$', r'\1-L.jpg', _text(result.get('bookimg'))),
                 'link': _text(result.get('booklink'))}
        _matches[(bookid, source, match['id'])] = match
        found.append(match)
    return found


def match_book(bookid, source: str, match_id: str, details: bool = True, cover: bool = True) -> str:
    """ Apply the book a Fix Match search found: link the book to it at that source, and take its
    details (title, subtitle, description, date, publisher, ISBN, language, pages, genres) and its
    cover when asked. The cover is kept through refreshes, as one chosen in Edit is. A match at the
    source the book comes from can't be its own id, so the book is locked instead, and a refresh
    doesn't put the old match back. Returns what happened """
    from lazylibrarian.cache import ImageType, cache_img  # noqa: PLC0415, it imports most of LazyLibrarian
    found = _matches.get((bookid, source, match_id))
    if not found:
        raise NotFoundError('That match is no longer known, search again')
    current = book_for_edit(bookid)
    own = source == current['own_source']
    values: dict = {'locked': True} if own else {}
    if details:
        values.update({key: found[match] for key, match in (
            ('title', 'title'), ('subtitle', 'subtitle'), ('description', 'description'), ('isbn', 'isbn'),
            ('language', 'language'), ('genre', 'genres')) if found[match]})
        if found['date'] and books.valid_book_date(found['date']):
            values['release_date'] = found['date']
    message = save_book(bookid, values) if values else ''
    db = database.DBConnection()
    try:
        column = book_source_columns()[source]
        other = db.match(f"SELECT BookName FROM books WHERE ({column}=? OR BookID=?) AND BookID!=?",
                         (match_id, match_id, bookid))
        if other:
            raise InvalidRequestError(f"{other['BookName']} is {match_id} at {source} already, it's in the library")
        db.action(f"UPDATE books SET {column}=? WHERE BookID=?", (match_id, bookid))
        if details:
            if found['publisher']:
                db.action("UPDATE books SET BookPub=? WHERE BookID=?", (found['publisher'], bookid))
            if found['pages']:
                db.action("UPDATE books SET BookPages=? WHERE BookID=?", (found['pages'], bookid))
        if cover and found['cover'].startswith('http'):
            link, ok, _ = cache_img(ImageType.BOOK, uuid.uuid4().hex, found['cover'], refresh=True)
            if ok:
                db.action("UPDATE books SET BookImg=? WHERE BookID=?", (link, bookid))
    finally:
        db.close()
    said = f"{found['title'] or current['title']} is {match_id} at {source} now"
    if own:
        said += ", and locked so a refresh keeps it"
    return f"{said}. {message}" if message else said


def _save_source_ids(bookid, current: dict, asked: dict) -> str:
    """ Link a book to other books at the info sources, by their ids there, an empty one unlinks it.
    The id of the source it comes from is its own and stays. Returns what changed """
    columns = book_source_columns()
    changed = {name: _text(value).strip() for name, value in asked.items()
               if name in columns and _text(value).strip() != current['source_ids'].get(name, '')}
    if not changed:
        return ''
    if current['own_source'] in changed:
        raise InvalidRequestError(f"Its {current['own_source']} id is the book's own, Add New adds a different one")
    db = database.DBConnection()
    try:
        for name, value in changed.items():
            other = db.match(f"SELECT BookName FROM books WHERE {columns[name]}=? AND BookID!=?", (value, bookid)) \
                if value else None
            if other:
                raise InvalidRequestError(f"{other['BookName']} is {value} at {name} already")
        for name, value in changed.items():
            db.action(f"UPDATE books SET {columns[name]}=? WHERE BookID=?", (value or None, bookid))
    finally:
        db.close()
    return ' '.join(f"{name}ID" for name in changed)


def book_covers(bookid) -> list[dict]:
    """ Covers for the book found online, as the old edit page's Find Images: the current one first """
    edit = books.book_for_edit(bookid, 'eBook', images=True)
    return [{'source': source, 'path': path} for source, path in edit['covers']]


def save_book(bookid, values: dict) -> str:
    """ Change a book: its details, author, series (a list of name and number, all of them) and the
    fields of its opf file. cover is one of the sources book_covers found. import_from is a folder or
    file to import its files from first """
    current = book_for_edit(bookid)
    title = _text(values.get('title', current['title'])).strip()
    if not title:
        raise InvalidRequestError("A book needs a title")
    _check_name('title', title)
    author = _text(values.get('author', current['author']))
    if author not in current['authors'] and author != current['author']:
        raise InvalidRequestError(f"There's no author {author}, add them first")
    cover = _text(values.get('cover'))
    if cover and cover not in COVER_SOURCES and cover not in ('hardcover', 'none'):
        raise InvalidRequestError(f"There's no cover {cover}")
    series_list = values.get('series')
    if series_list is None:
        series_list = current['series']
    db = database.DBConnection()
    try:
        # a series without an id can't be added, set_series leaves it out
        unknown = [item['name'] for item in series_list if _text(item.get('number')).strip() and not db.match(
            'SELECT SeriesID from series WHERE SeriesName=?', (_text(item.get('name')).strip(),))]
    finally:
        db.close()
    if unknown:
        raise InvalidRequestError(f"There's no series {', '.join(unknown)}. A book can be added to a series "
                                  f"LazyLibrarian has, refresh the author to find new ones")
    opf = {field['name']: _text(field['value']) for field in values.get('opf_fields') or []}
    date = _text(values.get('release_date', current['release_date'])).strip()
    if date and date != current['release_date'] and date != '0000' and not books.valid_book_date(date):
        raise InvalidRequestError(f"{date} isn't a date: a year, year-month or year-month-day")
    edited = books.update_book(
        bookid, title, _text(values.get('subtitle', current['subtitle'])), _text(values.get('genre', current['genre'])),
        _text(values.get('language', current['language'])), date or '0000', bool(values.get('locked', current['locked'])),
        author, _text(values.get('description', current['description'])), _text(values.get('isbn', current['isbn'])),
        _text(values.get('work_id', current['work_id'])), cover=cover,
        series=[(_text(item.get('name')).strip(), _text(item.get('number')).strip()) for item in series_list],
        opf_values=opf, import_from=_text(values.get('import_from')).strip())
    if 'narrator' in values and _text(values['narrator']) != current['narrator']:
        books.set_narrator(bookid, _text(values['narrator']))
        edited += ' Narrator'
    if values.get('source_ids'):
        edited += ' ' + _save_source_ids(bookid, current, values['source_ids'])
    if author != current['author']:
        edited += ' Author'
    # update_book also counts an empty field it stored over a missing one
    reported = {'Title': 'title', 'Subtitle': 'subtitle', 'Description': 'description', 'Genre': 'genre',
                'Language': 'language', 'ISBN': 'isbn', 'WorkID': 'work_id'}
    edited = ' '.join(word for word in edited.split()
                      if word not in reported or _text(values.get(reported[word], current[reported[word]])) !=
                      current[reported[word]])
    return _changes(edited, title)


# --- magazines and their issues

MAGAZINE_FIELDS = {'reject': 'Reject', 'regex': 'Regex', 'genre': 'Genre', 'date_type': 'DateType',
                   'cover_page': 'CoverPage', 'language': 'Language'}


def magazine_for_edit(title) -> dict:
    magazine = magazines.get_magazine(title)
    return {'title': magazine['Title'], 'reject': _text(magazine['Reject']), 'regex': _text(magazine['Regex']),
            'genre': _text(magazine['Genre']), 'date_type': _text(magazine['DateType']),
            'cover_page': check_int(magazine['CoverPage'], 1),
            'language': _text(magazine['Language']) or CONFIG['PREF_MAGLANG'],
            'wikidata_id': _text(magazine.get('WikidataID')),
            'keep_issues': check_int(magazine.get('KeepIssues'), 0), 'keep_months': check_int(magazine.get('KeepMonths'), 0),
            'profile_id': check_int(magazine.get('ProfileID'), 0),
            'numbering': _text(magazine.get('Numbering')) if magazine.get('Numbering') in magreleases.SCHEMES else '',
            'numbering_found': _numbering_found(magazine['Title'])}


def _numbering_found(title: str) -> str:
    """ What a magazine's issues are known by without a numbering chosen, worked out from them """
    db = database.DBConnection()
    try:
        row = db.match('SELECT DateType from magazines WHERE Title=?', (title,))
        return magreleases.form_of(row['DateType'] if row else '', [issue['IssueDate'] for issue in db.select(
            'SELECT IssueDate from issues WHERE Title=?', (title,))])
    finally:
        db.close()


def _profile_id(media_type: str, value) -> int:
    """ A quality profile of the media type's, by its id, or 0 for the default """
    from lazylibrarian.services import profiles  # noqa: PLC0415, it reads the settings
    profile_id = check_int(value, 0)
    if profile_id and profiles.get(profile_id)['media_type'] != media_type:
        raise InvalidRequestError(f"That quality profile isn't one for a {media_type}")
    return profile_id


def magazine_wikidata(title: str, term: str = '') -> list[dict]:
    """ The periodicals on Wikidata a magazine's title, or term, finds """
    if term.strip():
        magazine = magazines.get_magazine(title)
        return wikidata.search(term, (_text(magazine.get('Language')) or CONFIG['PREF_MAGLANG'] or 'en')[:2])
    return magazines.wikidata_matches(title)


def save_magazine(title, values: dict) -> dict:
    """ Change a magazine's filters, and rename it (its issue files move to match). Returns the title it
    has now, and the message """
    from lazylibrarian.services import settings  # noqa: PLC0415, it imports most of LazyLibrarian

    current = magazine_for_edit(title)
    title = current['title']
    if any(key in values for key in MAGAZINE_FIELDS):
        filters = {column: values.get(key, current[key]) for key, column in MAGAZINE_FIELDS.items()}
        settings.update_magazine_filters({title: {column: value if column == 'CoverPage' else _text(value).strip()
                                                  for column, value in filters.items()}})
    message = f"{title} saved"
    kept = {column: max(check_int(values.get(key, current[key]), 0), 0)
            for key, column in (('keep_issues', 'KeepIssues'), ('keep_months', 'KeepMonths'))}
    profile_id = _profile_id('magazine', values.get('profile_id', current['profile_id']))
    numbering = _text(values.get('numbering', current['numbering'])).strip()
    if numbering and numbering not in magreleases.SCHEMES:
        raise InvalidRequestError(f"A magazine's issues are known by one of {', '.join(magreleases.SCHEMES)}")
    db = database.DBConnection()
    try:
        db.upsert('magazines', {**kept, 'ProfileID': profile_id, 'Numbering': numbering}, {'Title': title})
    finally:
        db.close()
    # fewer issues kept lets the others go now, a command so it shows how it went
    retention_changed = (kept['KeepIssues'], kept['KeepMonths']) != (current['keep_issues'], current['keep_months'])
    if 'wikidata_id' in values and _text(values['wikidata_id']).strip() != current['wikidata_id']:
        message = magazines.set_wikidata(title, _text(values['wikidata_id']).strip())
    cover_page = check_int(values.get('cover_page', current['cover_page']), 1)
    new_title = _text(values.get('title', title)).strip()
    if new_title and new_title != title:
        _check_name('title', new_title)
        moved, failed = magazines.rename_magazine(title, new_title)
        message = f"Renamed {title} to {new_title}, {moved} issue files moved"
        if failed:
            message += f", {failed} couldn't be, see the log"
        title = new_title
    # the covers of the issues there are follow a new cover page, 0 makes none
    if cover_page and cover_page != current['cover_page']:
        from lazylibrarian.services import commands  # noqa: PLC0415, it imports most of LazyLibrarian
        commands.start('IssueCovers', {'title': title, 'page': cover_page})
        message += f", its covers are being made from page {cover_page}"
    elif cover_page and (coverless := magazines.coverless_issues(title)):
        # the same page, and issues that came in without a cover get one
        from lazylibrarian.services import commands  # noqa: PLC0415, it imports most of LazyLibrarian
        commands.start('IssueCovers', {'ids': coverless, 'page': cover_page})
        message += f", covers are being made for the {len(coverless)} {plural(len(coverless), 'issue')} without one"
    # the issues there are follow a numbering chosen, a command as their files are renamed
    if numbering and numbering != current['numbering']:
        from lazylibrarian.services import commands  # noqa: PLC0415, it imports most of LazyLibrarian
        commands.start('RenumberIssues', {'title': title})
        message += f", its issues are being renumbered as {magreleases.SCHEMES[numbering].lower()}s"
    if retention_changed and (kept['KeepIssues'] or kept['KeepMonths']):
        from lazylibrarian.services import commands  # noqa: PLC0415, it imports most of LazyLibrarian
        commands.start('ApplyRetention', {'title': title})
        message += ", the issues it doesn't keep are being deleted"
    return {'title': title, 'message': message}


def issue_for_edit(issueid) -> dict:
    issue, tags = magazines.issue_for_edit(issueid)
    return {'id': issue['IssueID'], 'title': issue['Title'], 'issue_date': _text(issue['IssueDate']),
            'file': _text(issue['IssueFile']),
            'tags': [{'name': name, 'value': _text(value)} for name, value in (tags or {}).items()]}


def save_issue(issueid, values: dict) -> dict:
    """ Move an issue to another magazine or issue date, and change the tags in its pdf. Returns the
    magazine to show and the message """
    current = issue_for_edit(issueid)
    title = _text(values.get('title', current['title'])).strip()
    if not title:
        raise InvalidRequestError("An issue needs a magazine title")
    _check_name('magazine title', title)
    old_tags = {tag['name']: tag['value'] for tag in current['tags']}
    new_tags = dict(old_tags)
    new_tags.update({tag['name']: _text(tag['value']) for tag in values.get('tags') or [] if tag['name'] in old_tags})
    shown, message = magazines.update_issue(issueid, title, _text(values.get('issue_date', current['issue_date'])).strip(),
                                            new_tags, old_tags)
    return {'title': shown, 'message': message}


# --- comics

def comic_for_edit(comicid) -> dict:
    comic = comics.get_comic(comicid)
    return {'id': comic['ComicID'], 'title': _text(comic['Title']), 'aka': _text(comic['aka']),
            'description': _text(comic['Description']), 'genre': _text(comic['Genre']),
            'profile_id': check_int(comic.get('ProfileID'), 0)}


def save_comic(comicid, values: dict) -> dict:
    """ Change a comic, its id too if the new one isn't taken. Returns its id now and the message """
    current = comic_for_edit(comicid)
    title = _text(values.get('title', current['title'])).strip()
    if not title:
        raise InvalidRequestError("A comic needs a title")
    _check_name('title', title)
    new_id = _text(values.get('id', comicid)).strip() or comicid
    if new_id != comicid:
        _check_name('id', new_id)
        db = database.DBConnection()
        try:
            if db.match('SELECT ComicID from comics WHERE ComicID=?', (new_id,)):
                raise InvalidRequestError(f"{new_id} is another comic's id already")
        finally:
            db.close()
    comicid = comics.update_comic(comicid, title, new_id, _text(values.get('aka', current['aka'])),
                                  _text(values.get('description', current['description'])))
    if 'genre' in values and _text(values['genre']) != current['genre']:
        comics.set_genre(comicid, _text(values['genre']).strip())
    if 'profile_id' in values:
        db = database.DBConnection()
        try:
            db.action('UPDATE comics SET ProfileID=? WHERE ComicID=?', (_profile_id('comic', values['profile_id']),
                                                                          comicid))
        finally:
            db.close()
    return {'id': comicid, 'message': f"{title} saved"}


# --- series

def series_for_edit(seriesid) -> dict:
    edit = series.series_for_edit(seriesid)
    found = edit['series']
    return {'id': found['SeriesID'], 'name': _text(found['SeriesName']), 'reason': _text(found['Reason']),
            'members': [{'number': _text(member['SeriesNum']), 'title': _text(member['BookName'])}
                        for member in edit['members']]}


def save_series(seriesid, values: dict) -> dict:
    """ Rename a series, or change its id. Returns its id now and the message """
    current = series_for_edit(seriesid)
    name = _text(values.get('name', current['name'])).strip()
    if not name:
        raise InvalidRequestError("A series needs a name")
    _check_name('name', name)
    new_id = _text(values.get('id', current['id'])).strip() or current['id']
    if new_id != current['id']:
        _check_name('id', new_id)
        db = database.DBConnection()
        try:
            if db.match('SELECT SeriesID from series WHERE SeriesID=?', (new_id,)):
                raise InvalidRequestError(f"{new_id} is another series' id already")
        finally:
            db.close()
    changed = series.update_series(current['id'], new_id, name)
    logging.getLogger(__name__).debug(f"Series {current['id']} edited: {changed}")
    return {'id': new_id, 'message': f"{name} saved" if changed else f"{name} wasn't changed"}
