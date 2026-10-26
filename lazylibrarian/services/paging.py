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

""" Searching, sorting and paging the record lists services return """

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lazylibrarian.formatter import fold, natural_sort


@dataclass
class Page:
    """ One page of a list: its records, how many records there are, and how many matched the search """
    items: list
    total: int
    matched: int


def page_of(records: list, search: str = '', search_fields: Sequence[str] = (), sort: str = '',
            descending: bool = False, natural: bool = False, offset: int = 0, limit: int | None = None,
            sort_key: Callable | None = None) -> Page:
    """ Filter records (dicts) on search, sort them on the sort field and return one page.

        The search ignores case and accents and matches anywhere in the search_fields.
        Missing values sort as empty strings; natural sorts numbers in text by value,
        so 'Book 2' comes before 'Book 10'. A limit of None or below 0 means the rest of the list.
    """
    total = len(records)
    if search:
        wanted = fold(search)
        records = [r for r in records if wanted in fold([r.get(f) for f in search_fields])]
    else:
        records = list(records)
    if sort_key is None and sort:
        def sort_key(r):
            value = r.get(sort)
            return '' if value is None else value
    if sort_key:
        if natural:
            natural_sort(records, key=lambda r: str(sort_key(r)), reverse=descending)
        else:
            records.sort(key=sort_key, reverse=descending)
    matched = len(records)
    if limit is None or limit < 0:
        items = records[offset:]
    else:
        items = records[offset:offset + limit]
    return Page(items=items, total=total, matched=matched)
