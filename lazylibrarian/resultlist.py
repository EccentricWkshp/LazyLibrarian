#  This file is part of Lazylibrarian.
#
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

import logging
import traceback

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from lazylibrarian import database, quality
from lazylibrarian.common import only_punctuation
from lazylibrarian.config2 import CONFIG
from lazylibrarian.downloadmethods import (
    direct_dl_method,
    irc_dl_method,
    nzb_dl_method,
    tor_dl_method,
)
from lazylibrarian.formatter import check_int, get_list, now, plural, replace_all, unaccented
from lazylibrarian.notifiers import custom_notify_snatch, notify_snatch
from lazylibrarian.providers import get_searchterm
from lazylibrarian.scheduling import SchedulerCommand, schedule_job
from lazylibrarian.services import blocklist, profiles
from lazylibrarian.services.history import indexer_name
from lazylibrarian.webshare import valid_ident


def process_result_list(resultlist, book, searchtype, source):
    """ Separated this out into two functions
        1. get the "best" match
        2. if over match threshold, send it to downloader
        This lets us try several searchtypes and stop at the first successful one
        and we can combine results from tor/nzb searches in one task
        Return 0 if not found, 1 if already snatched, 2 if we found it
    """
    match = find_best_result(resultlist, book, searchtype, source)
    if match:
        score = match[0]
        # resultTitle = match[1]
        # newValueDict = match[2]
        # controlValueDict = match[3]
        # dlpriority = match[4]

        if score < CONFIG.get_int('MATCH_RATIO'):
            return 0
        return download_result(match, book)
    return 0


# Language tags that appear in release names, mapped to the set of
# IMP_PREFLANG values each one satisfies.  Only unambiguous indicators:
# two-letter codes (en, fr, de ...) are too common as English words.
_LANG_TO_PREFLANG = {
    'english': {'en', 'eng', 'english'},
    'eng': {'en', 'eng', 'english'},
    'french': {'fr', 'fre', 'fra', 'french'},
    'fre': {'fr', 'fre', 'fra', 'french'},
    'fra': {'fr', 'fre', 'fra', 'french'},
    'german': {'de', 'ger', 'deu', 'german'},
    'ger': {'de', 'ger', 'deu', 'german'},
    'deu': {'de', 'ger', 'deu', 'german'},
    'spanish': {'es', 'spa', 'spanish'},
    'spa': {'es', 'spa', 'spanish'},
    'italian': {'it', 'ita', 'italian'},
    'ita': {'it', 'ita', 'italian'},
    'swedish': {'sv', 'swe', 'swedish'},
    'swe': {'sv', 'swe', 'swedish'},
    'norwegian': {'no', 'nor', 'norwegian'},
    'nor': {'no', 'nor', 'norwegian'},
    'danish': {'da', 'dan', 'danish'},
    'dan': {'da', 'dan', 'danish'},
    'dutch': {'nl', 'dut', 'nld', 'dutch'},
    'dut': {'nl', 'dut', 'nld', 'dutch'},
    'nld': {'nl', 'dut', 'nld', 'dutch'},
    'portuguese': {'pt', 'por', 'portuguese'},
    'por': {'pt', 'por', 'portuguese'},
    'russian': {'ru', 'rus', 'russian'},
    'rus': {'ru', 'rus', 'russian'},
    'polish': {'pl', 'pol', 'polish'},
    'pol': {'pl', 'pol', 'polish'},
    'czech': {'cs', 'cze', 'ces', 'czech'},
    'cze': {'cs', 'cze', 'ces', 'czech'},
    'ces': {'cs', 'cze', 'ces', 'czech'},
    'finnish': {'fi', 'fin', 'finnish'},
    'fin': {'fi', 'fin', 'finnish'},
    'hungarian': {'hu', 'hun', 'hungarian'},
    'hun': {'hu', 'hun', 'hungarian'},
    'turkish': {'tr', 'tur', 'turkish'},
    'tur': {'tr', 'tur', 'turkish'},
    'japanese': {'ja', 'jpn', 'japanese'},
    'jpn': {'ja', 'jpn', 'japanese'},
    'chinese': {'zh', 'chi', 'zho', 'chinese'},
    'chi': {'zh', 'chi', 'zho', 'chinese'},
    'zho': {'zh', 'chi', 'zho', 'chinese'},
    'korean': {'ko', 'kor', 'korean'},
    'kor': {'ko', 'kor', 'korean'},
    'arabic': {'ar', 'ara', 'arabic'},
    'ara': {'ar', 'ara', 'arabic'},
    'romanian': {'ro', 'ron', 'romanian'},
    'ron': {'ro', 'ron', 'romanian'},
    'greek': {'el', 'ell', 'greek'},
    'ell': {'el', 'ell', 'greek'},
}


def evaluate_results(resultlist, book, searchtype, source) -> list[dict]:
    """ Every result from the search providers, scored and checked like the automatic search does,
        each with the reasons it would be rejected, as Sonarr's decision engine gives its
        interactive search. A result with no rejections can be downloaded.
        resultlist: collated results from search providers
        book:       the book we want to find
        searchtype: book, magazine, shortbook, audiobook etc.
        source:     nzb, tor, rss, irc, direct
        Each is {'title', 'provider', 'url', 'mode', 'size' (MB), 'seeders', 'priority', 'score',
        'rejections', 'new_value_dict', 'control_value_dict'}
    """
    logger = logging.getLogger(__name__)
    fuzzlogger = logging.getLogger('special.fuzz')
    evaluated = []
    db = database.DBConnection()
    try:
        # '0': '', '1': '', '2': '', '3': '', '4': '', '5': '', '6': '', '7': '', '8': '', '9': '',
        dictrepl = {'...': '', '.': ' ', ' & ': ' ', ' = ': ' ', '?': '', '$': 's', ' + ': ' ', '"': '',
                    ',': ' ', '*': '', '(': '', ')': '', '[': '', ']': '', '#': '', '\'': '',
                    ':': '', '!': '', '-': ' ', r'\s\s': ' '}

        dic = {'...': '', '.': ' ', ' & ': ' ', ' = ': ' ', '?': '', '$': 's', ' + ': ' ', '"': '',
               ',': '', '*': '', ':': '.', ';': '', '\'': '', '-': ' '}

        if source == 'rss':
            author, title = get_searchterm(book, searchtype)
        else:
            author = unaccented(replace_all(book['authorName'], dic), only_ascii=False)
            title = unaccented(replace_all(book['bookName'], dic), only_ascii=False)

        if 'short' in searchtype and '(' in title:
            title = title.split('(')[0].strip()

        if book['library'] == 'AudioBook':
            reject_list = get_list(CONFIG['REJECT_AUDIO'], ',')
            maxsize = CONFIG.get_int('REJECT_MAXAUDIO')
            minsize = CONFIG.get_int('REJECT_MINAUDIO')
            auxinfo = 'AudioBook'

        else:  # elif book['library'] == 'eBook':
            reject_list = get_list(CONFIG['REJECT_WORDS'], ',')
            maxsize = CONFIG.get_int('REJECT_MAXSIZE')
            minsize = CONFIG.get_int('REJECT_MINSIZE')
            auxinfo = 'eBook'

        preflang_lower = {v.strip().lower() for v in get_list(CONFIG['IMP_PREFLANG'], ',') if v.strip()}
        check_lang = preflang_lower and 'all' not in preflang_lower

        # the quality profile: which formats are wanted, best first, and the file there is already
        media_type = 'audiobook' if auxinfo == 'AudioBook' else 'ebook'
        profile = profiles.for_library(auxinfo, db)
        current = book.get('current_quality') or ''
        upgrade = bool(book.get('upgrade'))

        if source == 'nzb':
            prefix = 'nzb'
        else:  # rss and direct providers return same names as torrents
            prefix = 'tor_'

        logger.debug(f'Searching {len(resultlist)} {source} results for best {auxinfo} match')
        for res in resultlist:
            result_title = unaccented(replace_all(res[f"{prefix}title"], dictrepl),
                                      only_ascii=False).strip()
            result_title = ' '.join(result_title.split())  # remove extra whitespace
            only_title = result_title.replace(author, '')
            if not only_title or only_punctuation(only_title):
                book_match = fuzz.token_set_ratio(title, result_title, processor=default_process)
            else:
                book_match = fuzz.token_set_ratio(title.replace(author, ''), only_title, processor=default_process)
            if 'booksearch' in res and res['booksearch'] == 'bibliotik':
                # bibliotik only returns book title, not author name
                fuzzlogger.debug("bibliotik, ignoring author fuzz")
                author_match = 100
            else:
                author_match = fuzz.token_set_ratio(author, result_title, processor=default_process)

            fuzzlogger.debug(f"{source.upper()} author/book Match: {author_match}/{book_match} {result_title} "
                             f"at {res[prefix + 'prov']}")

            rejections = []
            url = res[f"{prefix}url"]
            if not url:
                rejections.append('No download link')

            if url and CONFIG.get_bool('BLACKLIST_FAILED'):
                blocked = blocklist.find(db, url, res[f"{prefix}title"], res[f"{prefix}prov"],
                                         irc=res.get('tor_type', '') == 'irc')
                if blocked:
                    rejections.append(f"Blocklisted, it failed before at {indexer_name(blocked['NZBprov'])}")

            if url and CONFIG.get_bool('BLACKLIST_PROCESSED'):
                # a download that failed is the blocklist's, taken off it it can be tried again
                cmd = "SELECT * from wanted WHERE NZBurl=? and Status NOT IN ('Failed','Aborted')"
                args = (url,)
                if res.get('tor_type', '') == 'irc':
                    cmd += " and NZBTitle=?"
                    args += (res['tor_title'],)
                downloaded = db.match(cmd, args)
                if not downloaded:
                    downloaded = db.match("SELECT * from wanted WHERE NZBprov=? and NZBtitle=? "
                                          "and Status NOT IN ('Failed','Aborted')",
                                          (res[f"{prefix}prov"], res[f"{prefix}title"]))
                if downloaded:
                    rejections.append(f"Already downloaded ({downloaded['Status']}) from "
                                      f"{indexer_name(downloaded['NZBprov'])}")

            if source == 'rss':
                if searchtype in ['book', 'shortbook'] and 'E' not in res['types']:
                    rejections.append(f"{res[prefix + 'prov']} isn't used for eBooks")
                if 'audio' in searchtype and 'A' not in res['types']:
                    rejections.append(f"{res[prefix + 'prov']} isn't used for AudioBooks")
                if 'mag' in searchtype and 'M' not in res['types']:
                    rejections.append(f"{res[prefix + 'prov']} isn't used for Magazines")

            if url:
                invalid = False
                if source == 'irc':
                    invalid = not url.startswith('!')
                elif res[prefix + 'prov'] in ['zlibrary', 'soulseek']:
                    invalid = '^' not in url
                elif res[prefix + 'prov'] == 'webshare':
                    invalid = not valid_ident(url)
                elif res[prefix + 'prov'] == 'annas':
                    # annas gives us an id in hex, verify we got hex digits
                    try:
                        _ = int(url, 16)
                    except ValueError:
                        invalid = True
                elif not url.startswith('http') and not url.startswith('magnet'):
                    invalid = True
                if invalid:
                    rejections.append(f"Not a download link it can use [{url}]")

            for word in reject_list:
                if word in get_list(result_title.lower()) and word not in get_list(author.lower()) \
                        and word not in get_list(title.lower()):
                    rejections.append(f"Contains {word}, one of the words to reject")
                    break

            if check_lang:
                title_words = get_list(title.lower())
                author_words = get_list(author.lower())
                # a three letter code only counts in capitals, as release names give them (GER, ITA),
                # so a narrator called Dan or Ron isn't taken for Danish or Romanian
                capitals = {word.lower() for word in get_list(result_title) if word.isupper()}
                for word in get_list(result_title.lower()):
                    if word in title_words or word in author_words:
                        continue
                    if len(word) == 3 and word not in capitals:
                        continue
                    mapped = _LANG_TO_PREFLANG.get(word)
                    if mapped and not mapped.intersection(preflang_lower):
                        rejections.append(f"Language '{word}' is not a preferred language")
                        break

            result_words = set(get_list(result_title.lower()))
            ebook_types = {t.lower() for t in get_list(CONFIG['EBOOK_TYPE'])}
            audio_types = {t.lower() for t in get_list(CONFIG['AUDIOBOOK_TYPE'])}
            format_tokens = result_words & (ebook_types | audio_types)
            if format_tokens:
                if auxinfo == 'eBook' and format_tokens <= audio_types:
                    rejections.append(f"An audiobook ({', '.join(sorted(format_tokens))}), not an eBook")
                elif auxinfo == 'AudioBook' and format_tokens <= ebook_types:
                    rejections.append(f"An eBook ({', '.join(sorted(format_tokens))}), not an audiobook")

            release_quality, quality_rank = quality.UNKNOWN, 0
            if profile:
                release_quality = profiles.release_quality(profile, quality.of_release(res[f"{prefix}title"],
                                                                                       media_type))
                quality_rank = profiles.rank(profile, release_quality)
                shown = quality.name(release_quality)
                if not quality.imported(media_type, release_quality):
                    rejections.append(f"{shown} files aren't imported, add {release_quality} to the "
                                      f"{'audiobook' if media_type == 'audiobook' else 'eBook'} types in Settings")
                elif not quality_rank:
                    rejections.append(f"{shown} isn't wanted by the {profile['name']} quality profile")
                if current and quality_rank:
                    current_rank = profiles.rank(profile, current)
                    if upgrade and quality_rank <= current_rank:
                        rejections.append(f"Not an upgrade for the {quality.name(current)} there is")
                    elif quality_rank < current_rank:
                        rejections.append(f"{shown} is worse than the {quality.name(current)} there is")

            size_temp = check_int(res[f"{prefix}size"], 1000)  # Need to cater for when this is NONE (Issue 35)
            size = round(float(size_temp) / 1048576, 2)

            if maxsize and size > maxsize:
                rejections.append(f"Too large, {size}MB is over the {maxsize}MB limit")
            if minsize and size < minsize:
                rejections.append(f"Too small, {size}MB is under the {minsize}MB limit")

            min_seeders = CONFIG.get_int('MIN_SEEDERS')
            seeders = check_int(res.get('seeders', -1), -1)
            if min_seeders and 0 <= seeders < min_seeders:
                rejections.append(f"Only {seeders} {plural(seeders, 'seeder')}, the minimum is {min_seeders}")

            if rejections:
                logger.debug(f"Rejecting {result_title}: {'; '.join(rejections)}")

            bookid = book['bookid']

            if source == 'nzb':
                mode = res.get('nzbmode', '')  # nzb, torznab
            else:
                mode = res.get('tor_type', '')  # torrent, magnet, nzb(from rss), direct, irc

            control_value_dict = {"NZBurl": url}
            new_value_dict = {
                "NZBprov": res[f"{prefix}prov"],
                "BookID": bookid,
                "NZBdate": now(),  # when we asked for it
                "NZBsize": size,
                "NZBtitle": res[f"{prefix}title"],  # was resultTitle,
                "NZBmode": mode,
                "AuxInfo": auxinfo,
                "Label": res.get('label', ''),
                "Status": "Matched"
            }
            if source == 'irc':
                new_value_dict['NZBprov'] = res['tor_feed']
                new_value_dict['NZBtitle'] = res[f"{prefix}title"]

            if author_match >= CONFIG.get_int('MATCH_RATIO'):
                score = book_match
            else:
                score = (book_match + author_match) / 2  # as a percentage
            # lose a point for each unwanted word in the title so we get the closest match
            # but for rss ignore anything at the end in square braces [keywords, genres etc]
            if source == 'rss':
                wordlist = get_list(result_title.rsplit('[', 1)[0].lower())
            else:
                wordlist = get_list(result_title.lower())
            words = [x for x in wordlist if x not in get_list(author.lower())]
            words = [x for x in words if x not in get_list(title.lower())]

            # a format word isn't noise
            if new_value_dict['AuxInfo'] == 'eBook':
                words = [x for x in words if x not in get_list(CONFIG['EBOOK_TYPE'])]
            elif new_value_dict['AuxInfo'] == 'AudioBook':
                words = [x for x in words if x not in get_list(CONFIG['AUDIOBOOK_TYPE'])]

            # Don't treat wanted language as noise, and ignore separator "words" (#3100)
            preferred_tags = {w for w, langs in _LANG_TO_PREFLANG.items() if langs & preflang_lower}
            words = [x for x in words if x not in preferred_tags and x not in ('by', '/', '-')]

            score -= len(words)
            # the format is the quality profile's, which chooses between the releases before the score does

            # add points for words in the "preferred words" list, more the nearer the left
            preferwords = get_list(CONFIG['PREFER_WORDS'])
            if preferwords:
                preferwords = list(reversed(preferwords))
                for word in wordlist:
                    for i in [i for i, x in enumerate(preferwords) if x == word]:
                        score += i + 1

            # now do the same for words in preferred language list, not weighted, 1 point if match
            if preferred_tags:
                for word in wordlist:
                    if word in preferred_tags:
                        score += 1
                        break

            evaluated.append({'title': res[f"{prefix}title"], 'provider': new_value_dict['NZBprov'], 'url': url,
                              'mode': mode, 'size': size, 'seeders': seeders, 'priority': res['priority'],
                              'score': score, 'quality': release_quality, 'quality_rank': quality_rank,
                              'rejections': rejections, 'new_value_dict': new_value_dict,
                              'control_value_dict': control_value_dict})
    finally:
        db.close()
    return evaluated


def find_best_result(resultlist, book, searchtype, source):
    """ resultlist: collated results from search providers
        book:       the book we want to find
        searchtype: book, magazine, shortbook, audiobook etc.
        source:     nzb, tor, rss, irc, direct
        return:     highest scoring match, or None if no match
    """
    # noinspection PyBroadException
    logger = logging.getLogger(__name__)
    highest = None
    try:
        matches = [[result['score'], result['new_value_dict'], result['control_value_dict'], result['priority'],
                    check_int(result['seeders'], 0) if result['seeders'] >= 0 else 0, result['quality_rank']]
                   for result in evaluate_results(resultlist, book, searchtype, source) if not result['rejections']]

        if matches:
            # of the ones good enough to take, the best quality to the profile, then the best match.
            # When none is good enough, the nearest, to say how near
            good = [match for match in matches if match[0] >= CONFIG.get_int('MATCH_RATIO')]
            if good:
                highest = max(good, key=match_key)
            else:
                highest = max(matches, key=lambda s: (weighted_score(s), check_int(s[3], 0), check_int(s[4], 0)))
            score = highest[0]
            new_value_dict = highest[1]
            # controlValueDict = highest[2]
            dlpriority = highest[3]

            if score < CONFIG.get_int('MATCH_RATIO'):
                logger.info(
                    f"Nearest match ({round(score, 2)}%): {new_value_dict['NZBtitle']} using {searchtype} search for "
                    f"{book['authorName']} {book['bookName']}")
            else:
                logger.info(
                    f"Best match ({round(score, 2)}%): {new_value_dict['NZBtitle']} using {searchtype} search, "
                    f"{new_value_dict['NZBprov']} priority {dlpriority}")
        else:
            logger.debug(f"No {source} found for [{book['searchterm']}] using searchtype {searchtype}")
    except Exception:
        logger.error(f'Unhandled exception in find_best_result: {traceback.format_exc()}')

    return highest


def match_key(s):
    """ How a match ranks against another the search would take, as Sonarr's decision engine
    prefers: the quality profile's order first, then the score with the provider's priority, then
    the provider's priority and seeders """
    return check_int(s[5], 0) if len(s) > 5 else 0, weighted_score(s), check_int(s[3], 0), check_int(s[4], 0)


def weighted_score(s):
    # priority is already 0-100-ish per provider; normalize it down to a modest bonus
    priority_bonus = (check_int(s[3], 0) / 100) * CONFIG.get_int('PRIORITY_WEIGHT')
    return check_int(s[0], 0) + priority_bonus


def download_result(match, book):
    """ match:  best result from search providers
        book:   book we are downloading (needed for reporting author name)
        return: 0 if failed to snatch
                1 if already snatched
                2 if we snatched it
    """
    # noinspection PyBroadException
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        new_value_dict = match[1]
        control_value_dict = match[2]

        # It's possible to get book and wanted tables "Snatched" status out of sync
        # for example if a user marks a book as "Wanted" after a search task snatches it and before postprocessor runs
        # so check status in both tables here
        snatched = db.match("SELECT BookID from wanted WHERE BookID=? and AuxInfo=? and Status='Snatched'",
                            (new_value_dict["BookID"], new_value_dict["AuxInfo"]))
        if snatched:
            logger.debug(
                f"{new_value_dict['AuxInfo']} {book['authorName']} {book['bookName']} "
                f"already marked snatched in wanted table")
            return 1  # someone else already found it

        if new_value_dict["AuxInfo"] == 'eBook':
            snatched = db.match("SELECT BookID from books WHERE BookID=? and Status='Snatched'",
                                (new_value_dict["BookID"],))
        else:
            snatched = db.match("SELECT BookID from books WHERE BookID=? and AudioStatus='Snatched'",
                                (new_value_dict["BookID"],))
        if snatched:
            logger.debug(
                f"{new_value_dict['AuxInfo']} {book['authorName']} {book['bookName']} "
                f"already marked snatched in book table")
            return 1  # someone else already found it

        db.upsert("wanted", new_value_dict, control_value_dict)
        label = new_value_dict.get('Label', '')
        if new_value_dict['NZBmode'] == 'direct':
            snatch, res = direct_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                           control_value_dict["NZBurl"], new_value_dict["AuxInfo"],
                                           new_value_dict['NZBprov'])
        elif new_value_dict['NZBmode'] == 'irc':
            snatch, res = irc_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                        control_value_dict["NZBurl"], new_value_dict["AuxInfo"],
                                        new_value_dict['NZBprov'])
        elif new_value_dict['NZBmode'] in ["torznab", "torrent", "magnet"]:
            snatch, res = tor_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                        control_value_dict["NZBurl"], new_value_dict["AuxInfo"], label,
                                        new_value_dict['NZBprov'])
        elif new_value_dict['NZBmode'] == 'nzb':
            snatch, res = nzb_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                        control_value_dict["NZBurl"], new_value_dict["AuxInfo"], label)
        else:
            res = f"Unhandled NZBmode [{new_value_dict['NZBmode']}] for {control_value_dict['NZBurl']}"
            logger.error(res)
            snatch = 0

        if snatch:
            logger.info(
                f"Downloading {new_value_dict['AuxInfo']} {new_value_dict['NZBtitle']} from "
                f"{new_value_dict['NZBprov']}")
            custom_notify_snatch(f"{new_value_dict['BookID']} {new_value_dict['AuxInfo']}")
            notify_snatch(
                f"{new_value_dict['AuxInfo']} {new_value_dict['NZBtitle']} from "
                f"{CONFIG.disp_name(new_value_dict['NZBprov'])} at {now()}")
            # at this point we could add NZBprov to the blocklist with a short timeout, a second or two?
            # This would implement a round-robin search system. Blocklist with an incremental counter.
            # If number of active providers == number blocklisted, so no unblocked providers are left,
            # either sleep for a while, or unblock the one with the lowest counter.
            schedule_job(SchedulerCommand.START, target='PostProcessor')
            return 2  # we found it
        db.action("UPDATE wanted SET status='Failed',DLResult=? WHERE NZBurl=?",
                  (res, control_value_dict["NZBurl"]))
        return 0
    except Exception:
        logger.error(f'Unhandled exception in download_result: {traceback.format_exc()}')
        return 0
    finally:
        db.close()
