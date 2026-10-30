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
    check_int,
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


def _issue_words(low: list[str]) -> list[str]:
    """ A name's words up to just after its year: what follows is the uploader's ("Usenet-Space-Cowboys
    online No 1 NZB source") """
    year = next((pos for pos, word in enumerate(low) if len(word) == 4 and check_year(word)), len(low))
    return low[:year + 3]


def _number(low: list[str]) -> int:
    """ The issue number a name gives: after "No", "Issue" or "#", or after the volume when there's
    none ("Make Volume 33"), or a number just after the title ("Popular Woodworking 212-August 2014",
    not a day "ShopNotes-18 May 2023" or a year), up to just after the year """
    low = _issue_words(low)
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


# how a magazine's issues are known, chosen in its Edit: by date, by a number that runs on from issue
# to issue ("Make Volume 98"), by a number within the year ("Vol 45 No 5 2025"), by volume and number,
# or by year (an annual). Without one it's worked out from the issues there are, keeping their form
SCHEMES = {'date': 'Date', 'running': 'Running number', 'yearly': 'Number within the year',
           'volume': 'Volume and number', 'year': 'Year, an annual'}
NO_KEY = 'No issue date or number in the name'
# a key as it's kept: 0098, 2026, 20260098, 00450005, 2026-03-01
KEY = re.compile(r'^(\d{4}|\d{8}|\d{4}-\d\d-\d\d)$')


def form_of(datetype: str, issue_dates: list[str]) -> str:
    """ What a magazine's issues are known by when no numbering was chosen: 'date', 'number' (with the
    year in front when there is one, as numbered issues have been), 'year' (an annual), or '' when it
    can't be told. Its date type says, or most of the issues it has """
    datetype = (datetype or '').upper()
    if 'I' in datetype or 'V' in datetype:
        return 'number'
    if 'M' in datetype or 'D' in datetype:
        return 'date'
    if datetype == 'Y':
        return 'year'
    # not an issue filed as 1970-01-01 when it had none
    dated = sum(1 for d in issue_dates if re.match(r'^[12]\d{3}-\d\d-\d\d$', str(d or '')) and d != NO_ISSUE)
    # a year's number, or a running one (0034) that no year starts with
    numbered = sum(1 for d in issue_dates if str(d or '').isdigit() and (len(str(d)) != 4 or str(d)[0] == '0'))
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


def _paired_date(number: int, year: int, pairs: dict) -> str:
    """ The date a name gave with this number, when it's that year's or near it """
    paired = pairs['number'].get(number, '') if number else ''
    return paired if paired and (not year or abs(int(paired[:4]) - year) <= 1) else ''


def key_of(parts: dict, scheme: str, pairs: dict | None = None) -> tuple[str, str]:
    """ An issue's key as its magazine's issues are known (scheme, one of SCHEMES or what form_of
    works out), from what a name or a key says: its date, number, volume, issue (the number after
    "No"/"Issue"), year. Pairs put a date as a number or a number as a date. Returns the key, or ''
    and why there's none """
    pairs = pairs or {'month': {}, 'number': {}}
    date, number, year = parts['date'], parts['number'], parts['year']
    if scheme == 'date':
        paired = date or _paired_date(number, year, pairs)
        if paired:
            return paired, ''
        return '', (f"Numbered {number}, but the magazine's issues are dated and no name gives that number's "
                    f"date" if number else NO_KEY)
    if scheme in ('running', 'yearly', 'number'):
        if not number and date and pairs['month'].get(date[:7]):
            number, year = pairs['month'][date[:7]], year or int(date[:4])
        if not number:
            return '', (f"Dated {date[:7]}, but the magazine's issues are numbered and no name gives that "
                        f"month's number" if date else NO_KEY)
        if scheme == 'running':
            return f"{number:04d}", ''
        year = year or int((_paired_date(number, 0, pairs) or '0')[:4])
        if scheme == 'yearly' and not year:
            return '', f"Number {number}, but the magazine's numbers start again each year and there's no year"
        return (f"{year}{number:04d}" if year else f"{number:04d}"), ''
    if scheme == 'volume':
        if parts['volume'] and parts['issue']:
            return f"{parts['volume']:04d}{parts['issue']:04d}", ''
        return '', "No volume and number in the name"
    if scheme == 'year':
        return (str(year), '') if year else ('', NO_KEY)
    # not known: a date, else a number as numbered issues have been
    if date:
        return date, ''
    if number:
        year = year or int((_paired_date(number, 0, pairs) or '0')[:4])
        return (f"{year}{number:04d}" if year else f"{number:04d}"), ''
    return '', NO_KEY


def parts_of_key(key: str) -> dict:
    """ What an issue's key says, as key_of takes it: 20260098, 0098, 00980001, 2026-03-01, 2026 """
    dateparts = get_dateparts(str(key))
    if not dateparts['style']:
        return {'date': '', 'number': 0, 'issue': 0, 'volume': 0, 'year': 0}
    issue, volume = check_int(dateparts['issue'], 0), check_int(dateparts['volume'], 0)
    return {'date': _date(dateparts), 'number': issue or volume, 'issue': issue, 'volume': volume,
            'year': check_int(dateparts['year'], 0)}


def convert(key: str, scheme: str, pairs: dict | None = None) -> str:
    """ A key in the numbering chosen for its magazine (one of SCHEMES): Make's 20260098 as a running
    number is 0098. The key as it is when no numbering was chosen, or it can't be put in it """
    if scheme not in SCHEMES or not key or key == NO_ISSUE:
        return key
    converted, _ = key_of(parts_of_key(key), scheme, pairs)
    return converted or key


def _posted_year(month: int, posted: str) -> int:
    """ The year of an issue named by its month alone, from when it was posted: an issue comes out up
    to two months ahead of its date and is posted within ten months after it. 0 without a real date """
    try:
        when = datetime.date.fromisoformat(str(posted)[:10])
    except ValueError:
        return 0
    if when.year < 2000:  # the date put on a result that came without one
        return 0
    # the nearest of those that can be
    ahead = {year: (year * 12 + month) - (when.year * 12 + when.month) for year in range(when.year - 1, when.year + 2)}
    return min((year for year, months in ahead.items() if -10 <= months <= 2), key=lambda year: abs(ahead[year]))


def _as_named(text: str, phrase: str) -> str:
    """ A phrase as the name has it, "South Africa" for "south africa" """
    pattern = r'[\W_]+'.join(re.escape(word) for word in words_of(phrase))
    found = re.search(pattern, text, re.IGNORECASE)
    return ' '.join(re.split(r'[\W_]+', found.group(0))) if found else phrase


def read(name: str, terms: list[str], datetype: str = '', scheme: str = '', pairs: dict | None = None,
         posted: str = '') -> dict:
    """ What a search result's name says about the magazine searched for by these terms (its title or
    search terms). kind is None when the name isn't the magazine's, else ISSUE, UNDATED or one of
    SET_ASIDE; reason says why it isn't an issue; issuedate is the issue as the magazine's issues
    are known (scheme, using pairs to put a number as a date or a date as a number) or ''; edition is
    another edition's words, as the name has them. A month without a year is the one around posted,
    when the result was posted (yyyy-mm-dd) """
    text = html.unescape(str(name))
    found = {'kind': None, 'reason': '', 'issuedate': '', 'date': '', 'number': 0, 'issue': 0, 'volume': 0,
             'year': 0, 'edition': ''}
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
    if found['kind'] == EDITION:
        found['edition'] = _as_named(text, _phrase(rest, get_list(CONFIG['MAG_EDITION_WORDS'], ',')))
    found['kind'] = found['kind'] or ISSUE

    # the issue part as get_dateparts reads it, without the title
    remainder = ' '.join(rest)
    mdy = 'MDY' if 'MDY' in (datetype or '').upper() else ''
    dateparts = get_dateparts(remainder, datetype=mdy)
    if mdy and not dateparts['style']:
        dateparts = get_dateparts(remainder)
    found['number'] = _number(rest)
    # for a magazine known by volume and number, the two apart: "Vol 45 No 5 2025"
    issue_nouns, volume_nouns = _nouns()
    window = _issue_words(rest)
    found['volume'] = _noun_number(window, volume_nouns)
    found['issue'] = _noun_number(window, issue_nouns)
    if found['number'] and dateparts['day'] == found['number']:
        # the number before the month is the issue's, not the day: "Nuts and Volts No 7-July 2014"
        dateparts['day'] = 1
    if not dateparts['year'] and dateparts['months'] and not found['number'] and posted:
        # "Popular Mechanics USA-October": the October around when it was posted
        dateparts['year'] = _posted_year(dateparts['months'][0], posted)
        dateparts['style'] = dateparts['style'] or (4 if dateparts['year'] else 0)
    found['year'] = dateparts['year']
    found['date'] = _date(dateparts)
    found['issuedate'], why = key_of(found, scheme, pairs)

    if found['kind'] == ISSUE and not found['issuedate']:
        found['kind'] = UNDATED
        if why == NO_KEY and found['year'] and not found['number'] and not found['date']:
            found['reason'] = 'Only a year, all of its issues or an annual'
        else:
            found['reason'] = why
    return found


def chosen_scheme(db, title: str) -> str:
    """ The numbering chosen for a magazine in its Edit, one of SCHEMES, or '' """
    row = db.match('SELECT Numbering from magazines WHERE Title=? COLLATE NOCASE', (title,))
    return row['Numbering'] if row and row['Numbering'] in SCHEMES else ''


def scheme_of(db, title: str) -> str:
    """ What the magazine's issues are known by: the numbering chosen for it, or what its date type or
    the issues it has say """
    row = db.match('SELECT Numbering,DateType from magazines WHERE Title=? COLLATE NOCASE', (title,))
    if row and row['Numbering'] in SCHEMES:
        return row['Numbering']
    return form_of(row['DateType'] if row else '', [issue['IssueDate'] for issue in
                                                     db.select('SELECT IssueDate from issues WHERE Title=?', (title,))])


def known_pairs(db, title: str, terms: list[str], names: list[str] = ()) -> dict:
    """ The number and date pairs in the names of the magazine's search results, the ones stored and
    these """
    rows = db.select('SELECT NZBtitle from pastissues WHERE BookID=? UNION SELECT NZBtitle from wanted '
                     'WHERE BookID=?', (title, title))
    return pairs_of([read(name, terms) for name in [row['NZBtitle'] for row in rows] + list(names)])


def reread(db, title: str, terms: list[str], datetype: str, scheme: str, pairs: dict) -> int:
    """ The magazine's stored search results that weren't wanted (Skipped, or Have when the issue is
    there) read again, for their issue and why they're set aside; ones that aren't the magazine's
    are forgotten. Returns how many changed """
    changed = 0
    for row in db.select("SELECT rowid AS RowID,NZBtitle,NZBdate,AuxInfo,Status,DLResult from pastissues "
                         "WHERE BookID=? AND Status IN ('Skipped','Have')", (title,)):
        found = read(row['NZBtitle'], terms, datetype, scheme, pairs, row['NZBdate'] or '')
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


def issue_of(db, title: str, name: str, posted: str = '') -> dict:
    """ What a search result's name says about a magazine, read as its searches read it """
    magazine = db.match('SELECT Regex,DateType from magazines WHERE Title=?', (title,))
    terms = get_list(magazine['Regex'] if magazine else '', ',') or [title]
    datetype = (magazine['DateType'] if magazine else '') or ''
    return read(name, terms, datetype, scheme_of(db, title), known_pairs(db, title, terms), posted)


def chosen_issue(db, title: str, name: str, posted: str = '') -> tuple[str, str]:
    """ The issue to file a search result someone chose under, and '' with why when there's none: no
    date or number in its name, or one set aside (a special, say) whose date is an issue there is,
    which it would replace """
    found = issue_of(db, title, name, posted)
    issuedate = found['issuedate']
    if not issuedate:
        return '', found['reason'] or 'No issue date or number in the name'
    if found['kind'] != ISSUE and db.match('SELECT IssueID from issues WHERE Title=? AND IssueDate=?',
                                           (title, issuedate)):
        return '', f"{found['reason']}, and its date is issue {issuedate}'s, which it would replace"
    return issuedate, ''


def entered(db, title: str, entry: str, strict: bool = True) -> tuple[str, str]:
    """ The key for what's typed as an issue's date or number in its Edit, read as a name with the
    magazine's title would be ("34", "Volume 34", "No 98 2026", "March 2026", "2026-03") or a key as
    it's kept (0034, 20260098), in the form the magazine's issues are known by; not strict, as it's
    typed when it can't be put in that form (a date for numbered issues no name gives a number for).
    Returns it, or '' and why there's none """
    entry = entry.strip()
    magazine = db.match('SELECT Regex,DateType from magazines WHERE Title=? COLLATE NOCASE', (title,))
    datetype = (magazine['DateType'] if magazine else '') or ''
    scheme = scheme_of(db, title)
    if KEY.match(entry):
        parts = parts_of_key(entry)
    else:
        name = entry if words_of(entry)[:len(words_of(title))] == words_of(title) else f'{title} {entry}'
        parts = read(name, [title], datetype)
        if not (parts['date'] or parts['number'] or parts['year']):
            parts = parts_of_key(get_dateparts(entry, datetype=datetype)['dbdate'] or '')
    terms = get_list(magazine['Regex'] if magazine else '', ',') or [title]
    key, why = key_of(parts, scheme, known_pairs(db, title, terms))
    if not key and not strict:
        key = key_of(parts, '')[0]
    if not key and parts['year'] and not parts['number'] and not parts['date'] and scheme in ('', 'year'):
        key = str(parts['year'])  # an annual's
    if key:
        return key, ''
    if why == NO_KEY:
        return '', f'"{entry}" is no date (2026-03, March 2026) or number (34, Volume 34, No 98 2026)'
    return '', (f'"{entry}" can\'t be an issue of {title}: {why[0].lower()}{why[1:]}. How its issues are known '
                f'is chosen in the magazine\'s Edit')
