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

""" What a magazine search result's name says: whether it is the magazine searched for, an issue of it
or set aside (several issues in one, a special, another country's edition), and which issue, as a
date or a number in the form the magazine's issues have. Names that give both a number and a date
pair the magazine's two numberings, so a name with only one of them can be put in the other """

import datetime
import html
import re

from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import (
    check_year,
    get_list,
    month2num,
    replace_all,
    two_months,
    unaccented,
)
from lazylibrarian.magazinescan import NOT_ISSUE_NUMBERS, get_dateparts

ISSUE = 'issue'
BUNDLE = 'bundle'
SPECIAL = 'special'
EDITION = 'edition'
UNDATED = 'undated'
SET_ASIDE = (BUNDLE, SPECIAL, EDITION)

WORD_BREAKS = {'.': ' ', '-': ' ', '/': ' ', '_': ' ', '(': ' ', ')': ' ', '[': ' ', ']': ' ', '{': ' ',
               '}': ' ', '<': ' ', '>': ' ', '#': ' # ', '!': ' ', ':': ' ', ',': ' ', ';': ' ', '&': ' and ',
               '+': ' and ', '"': '', "'": ''}
# words in a title or a name that it can have or not, "WOOD Magazine" is "Wood"
OPTIONAL = {'magazine', 'magazines', 'mag', 'magz', 'the'}
# words between the title and the issue that don't make it another publication
TAGS = OPTIONAL | {'truepdf', 'true', 'pdf', 'epub', 'cbz', 'cbr', 'hq', 'hybrid', 'retail', 'ebook', 'english',
                   'eng', 'en', 'digital', 'usa', 'us', 'edition', 'and', 'of', 'nzb', 'nfo', 'par2', 'rar'}
# YYYY-YYYY, several years' issues when they're more than a year apart
YEAR_RANGE = re.compile(r'\b((?:19|20)\d\d)\s*(?:-|to)\s*((?:19|20)\d\d)\b')
# what a stored search result that isn't an issue has for its issue
NO_ISSUE = '1970-01-01'


def words_of(text: str) -> list[str]:
    """ The words of a name or a title, as they are matched: lower case, no accents, '&' as 'and' """
    return [unaccented(word, only_ascii=False).lower() for word in replace_all(text, WORD_BREAKS).split()]


def _core(term: str) -> list[str]:
    return [word for word in words_of(term) if word not in OPTIONAL] or words_of(term)


def _title_end(low: list[str], core: list[str], pos: int) -> int:
    """ Where the title's words, from pos, end (words it can have or not between them), or -1 """
    for word in core:
        while pos < len(low) and low[pos] != word and low[pos] in OPTIONAL:
            pos += 1
        if pos >= len(low) or low[pos] != word:
            return -1
        pos += 1
    return pos


def _after_title(low: list[str], terms: list[str]) -> tuple[int, int]:
    """ Where the words after the magazine's title start in a name that starts with it (after a
    count or "MAGAZINE"), or -1: a title that comes later ("Lets Make") isn't the magazine. And where
    they end, where the name says it all again ("... 2082 MB 14 - MAGAZINE Popular Woodworking ...") """
    for term in terms:
        core = _core(term)
        if not core:
            continue
        pos = 0
        while pos < len(low) and low[pos] != core[0] and (low[pos].isdigit() or low[pos] in OPTIONAL):
            pos += 1
        start = _title_end(low, core, pos)
        if start < 0:
            continue
        end = next((pos for pos in range(start + 1, len(low)) if low[pos] == core[0] and
                    _title_end(low, core, pos) > 0), len(low))
        return start, end
    return -1, -1


def _nouns() -> tuple[list[str], list[str]]:
    return get_list(CONFIG['ISSUE_NOUNS']), get_list(CONFIG['VOLUME_NOUNS'])


def _is_issue_word(word: str, nouns: list[str]) -> bool:
    """ A word that starts the issue part of a name: a number, a month or season, "No"/"Vol"/"#" """
    if word.isdigit() or month2num(word) or all(two_months(word)):
        return True
    return re.split(r'(\d+)', word)[0].strip('.') in nouns


def _noun_number(low: list[str], nouns: list[str]) -> int:
    """ The number after one of these nouns, "No 276", "no219", "Vol.41" """
    for pos, word in enumerate(low):
        head, *tail = re.split(r'(\d+)', word)
        if head.strip('.') not in nouns:
            continue
        if tail and tail[0]:
            return int(tail[0])
        if pos + 1 < len(low) and low[pos + 1].isdigit() and len(low[pos + 1]) <= 4 and \
                not check_year(low[pos + 1]):
            return int(low[pos + 1])
    return 0


def _number(low: list[str]) -> int:
    """ The issue number a name gives: after "No", "Issue" or "#", or after the volume when there's
    none ("Make Volume 33"), or a number just after the title ("Popular Woodworking 212-August 2014",
    not a day "ShopNotes-18 May 2023" or a year). Only up to just after the year: what follows is the
    uploader's ("Usenet-Space-Cowboys online No 1 NZB source") """
    year = next((pos for pos, word in enumerate(low) if len(word) == 4 and check_year(word)), len(low))
    low = low[:year + 3]
    issue_nouns, volume_nouns = _nouns()
    number = _noun_number(low, issue_nouns) or _noun_number(low, volume_nouns)
    if number:
        return number
    words = [word for word in low if word not in TAGS]
    if words and words[0].isdigit() and len(words[0]) <= 4 and not check_year(words[0]):
        after = words[1] if len(words) > 1 else ''
        if int(words[0]) > 31 or not (after and (month2num(after) or all(two_months(after)))):
            return int(words[0])
    return 0


def _phrase(low: list[str], phrases: list[str]) -> str:
    text = f" {' '.join(low)} "
    return next((phrase for phrase in phrases if phrase and f" {' '.join(words_of(phrase))} " in text), '')


def _set_aside(name: str, rest: list[str]) -> tuple[str, str]:
    """ Why the words after the title aren't one issue of the magazine: several issues in one, another
    country's edition, or other words before the issue (a special, or another magazine whose title
    starts the same, "Wood Carving") """
    bundle = _phrase(rest, get_list(CONFIG['MAG_BUNDLE_WORDS'], ','))
    if bundle:
        return BUNDLE, f'Set aside: several issues in one ("{bundle}")'
    # not one winter's issue, "Winter 2011-2012"
    years = [(a, b) for a, b in YEAR_RANGE.findall(name) if abs(int(b) - int(a)) > 1]
    if years:
        return BUNDLE, f'Set aside: several issues in one ({years[0][0]}-{years[0][1]})'
    issue_nouns, volume_nouns = _nouns()
    words = [word for word in rest if word not in TAGS and word not in issue_nouns + volume_nouns]
    if len(words) > 2 and words[0].isdigit() and words[1].isdigit() and len(words[0]) <= 3 and \
            len(words[1]) <= 3 and int(words[1]) > int(words[0]) + 1 and not check_year(words[2]):
        return BUNDLE, f'Set aside: several issues in one ({words[0]}-{words[1]})'
    edition = _phrase(rest, get_list(CONFIG['MAG_EDITION_WORDS'], ','))
    if edition:
        return EDITION, f'Set aside: another edition ("{edition}")'
    nouns = issue_nouns + volume_nouns
    before = []
    for word in rest:
        if _is_issue_word(word, nouns):
            break
        if word not in TAGS:
            before.append(word)
    if before:
        return SPECIAL, f'Set aside: "{" ".join(before[:5])}" after the title, a special or another magazine'
    return '', ''


def _date(dateparts: dict) -> str:
    """ The issue's date, yyyy-mm-dd (the first of the month when the name has no day), or '' """
    month = (dateparts['months'] or [dateparts['month']])[0]
    if not dateparts['style'] or not dateparts['year'] or not month:
        return ''
    day = dateparts['day'] if dateparts['style'] in (3, 5, 6) and dateparts['day'] else 1
    try:
        return datetime.date(dateparts['year'], month, day).isoformat()
    except (ValueError, TypeError):
        return ''


def form_of(datetype: str, issue_dates: list[str]) -> str:
    """ What a magazine's issues are known by: 'date', 'number', 'year' (an annual), or '' when it
    can't be told. Its date type says, or most of the issues it has """
    datetype = (datetype or '').upper()
    if 'I' in datetype or 'V' in datetype:
        return 'number'
    if 'M' in datetype or 'D' in datetype:
        return 'date'
    if datetype == 'Y':
        return 'year'
    dated = sum(1 for d in issue_dates if re.match(r'^[12]\d{3}-\d\d-\d\d$', str(d or '')))
    numbered = sum(1 for d in issue_dates if str(d or '').isdigit() and len(str(d)) != 4)
    if dated or numbered:
        return 'date' if dated >= numbered else 'number'
    return ''


def pairs_of(readings: list[dict]) -> dict:
    """ The numbers and dates names give together, each month to its number and each number to its
    date; a month or a number given two ways is left out """
    by_month, by_number = {}, {}
    for reading in readings:
        if reading.get('kind') == ISSUE and reading['date'] and reading['number']:
            for table, key, value in ((by_month, reading['date'][:7], reading['number']),
                                      (by_number, reading['number'], reading['date'])):
                if table.get(key, value) != value:
                    value = None
                table[key] = value
    return {'month': {k: v for k, v in by_month.items() if v},
            'number': {k: v for k, v in by_number.items() if v}}


def read(name: str, terms: list[str], datetype: str = '', form: str = '', pairs: dict | None = None) -> dict:
    """ What a search result's name says about the magazine searched for by these terms (its title or
    search terms). kind is None when the name isn't the magazine's, else ISSUE, UNDATED or one of
    SET_ASIDE; reason says why it isn't an issue; issuedate is the issue as the magazine's issues
    are known (form, using pairs to put a number as a date or a date as a number) or '' """
    text = html.unescape(str(name))
    found = {'kind': None, 'reason': '', 'issuedate': '', 'date': '', 'number': 0, 'year': 0}
    # sizes and part counts are no issue's numbers
    low = words_of(NOT_ISSUE_NUMBERS.sub(' ', text))
    start, end = _after_title(low, terms)
    if start < 0:
        found['reason'] = "The magazine's title doesn't start the name"
        return found
    rest = low[start:end]
    if not [word for word in rest if word not in TAGS]:
        found['reason'] = 'Nothing but the title'
        return found
    found['kind'], found['reason'] = _set_aside(text, rest)
    found['kind'] = found['kind'] or ISSUE

    # the issue part as get_dateparts reads it, without the title
    remainder = ' '.join(rest)
    mdy = 'MDY' if 'MDY' in (datetype or '').upper() else ''
    dateparts = get_dateparts(remainder, datetype=mdy)
    if mdy and not dateparts['style']:
        dateparts = get_dateparts(remainder)
    found['number'] = _number(rest)
    if found['number'] and dateparts['day'] == found['number']:
        # the number before the month is the issue's, not the day: "Nuts and Volts No 7-July 2014"
        dateparts['day'] = 1
    found['year'] = dateparts['year']
    found['date'] = _date(dateparts)
    pairs = pairs or {'month': {}, 'number': {}}
    number, date, year = found['number'], found['date'], found['year']
    if number and not year and pairs['number'].get(number):
        year = int(pairs['number'][number][:4])
    number_key = (f"{year}{number:04d}" if year else f"{number:04d}") if number else ''

    if form == 'number':
        if number_key:
            found['issuedate'] = number_key
        elif date and pairs['month'].get(date[:7]):
            found['issuedate'] = f"{date[:4]}{pairs['month'][date[:7]]:04d}"
        elif date:
            found['why'] = f"Dated {date[:7]}, but the magazine's issues are numbered and no name gives that " \
                           f"month's number"
    elif form == 'date':
        if date:
            found['issuedate'] = date
        elif number and pairs['number'].get(number) and \
                (not found['year'] or abs(int(pairs['number'][number][:4]) - found['year']) <= 1):
            found['issuedate'] = pairs['number'][number]
        elif number:
            found['why'] = f"Numbered {number}, but the magazine's issues are dated and no name gives that " \
                           f"number's date"
    elif form == 'year':
        found['issuedate'] = str(year) if year else ''
    else:
        found['issuedate'] = date or number_key

    if found['kind'] == ISSUE and not found['issuedate']:
        found['kind'] = UNDATED
        if found.get('why'):
            found['reason'] = found['why']
        elif year and not number and not date:
            found['reason'] = 'Only a year, all of its issues or an annual'
        else:
            found['reason'] = 'No issue date or number in the name'
    found.pop('why', None)
    return found


def magazine_form(db, title: str, datetype: str) -> str:
    """ What the magazine's issues are known by, from its date type or the issues it has """
    return form_of(datetype, [row['IssueDate'] for row in
                              db.select('SELECT IssueDate from issues WHERE Title=?', (title,))])


def known_pairs(db, title: str, terms: list[str], names: list[str] = ()) -> dict:
    """ The number and date pairs in the names of the magazine's search results, the ones stored and
    these """
    rows = db.select('SELECT NZBtitle from pastissues WHERE BookID=? UNION SELECT NZBtitle from wanted '
                     'WHERE BookID=?', (title, title))
    return pairs_of([read(name, terms) for name in [row['NZBtitle'] for row in rows] + list(names)])


def reread(db, title: str, terms: list[str], datetype: str, form: str, pairs: dict) -> int:
    """ The magazine's stored search results that weren't wanted (Skipped, or Have when the issue is
    there) read again, for their issue and why they're set aside; ones that aren't the magazine's
    are forgotten. Returns how many changed """
    changed = 0
    for row in db.select("SELECT rowid AS RowID,NZBtitle,AuxInfo,Status,DLResult from pastissues "
                         "WHERE BookID=? AND Status IN ('Skipped','Have')", (title,)):
        found = read(row['NZBtitle'], terms, datetype, form, pairs)
        if found['kind'] is None:
            db.action('DELETE from pastissues WHERE rowid=?', (row['RowID'],))
            changed += 1
            continue
        issuedate = found['issuedate'] if found['kind'] == ISSUE else NO_ISSUE
        status = 'Have' if found['kind'] == ISSUE and db.match(
            'SELECT IssueID from issues WHERE Title=? AND IssueDate=?', (title, issuedate)) else 'Skipped'
        if (row['AuxInfo'], row['Status'], row['DLResult'] or '') != (issuedate, status, found['reason']):
            db.action('UPDATE pastissues SET AuxInfo=?,Status=?,DLResult=? WHERE rowid=?',
                      (issuedate, status, found['reason'], row['RowID']))
            changed += 1
    return changed
