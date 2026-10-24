#  This file is part of Lazylibrarian.
#
# Purpose:
#    Table of book languages for the language picker on the config page.
#    Metadata sources report languages in different ways (GoodReads "eng", GoogleBooks "en",
#    others the English name) so each language in the picker stands for all of its codes,
#    and selecting it adds every code to IMP_PREFLANG.

from lazylibrarian import i18n
from lazylibrarian.formatter import get_list
from lazylibrarian.i18n import N_

# Name, then the codes that mean this language: ISO 639-1, ISO 639-2 (B and T), regional
# variants and the English name. The name is translated for display only, the config stores codes.
# The first entries are the most common book languages, shown before "Show all".
BOOK_LANGUAGES = [
    (N_('English'), ['en', 'eng', 'en-US', 'en-GB', 'English']),
    (N_('Spanish'), ['es', 'spa', 'Spanish']),
    (N_('French'), ['fr', 'fre', 'fra', 'French']),
    (N_('German'), ['de', 'ger', 'deu', 'German']),
    (N_('Italian'), ['it', 'ita', 'Italian']),
    (N_('Portuguese'), ['pt', 'por', 'pt-BR', 'pt-PT', 'Portuguese']),
    (N_('Russian'), ['ru', 'rus', 'Russian']),
    (N_('Chinese'), ['zh', 'chi', 'zho', 'zh-CN', 'zh-TW', 'Chinese']),
    (N_('Japanese'), ['ja', 'jpn', 'Japanese']),
    (N_('Dutch'), ['nl', 'dut', 'nld', 'Dutch']),
    (N_('Polish'), ['pl', 'pol', 'Polish']),
    (N_('Czech'), ['cs', 'cze', 'ces', 'Czech']),
    (N_('Slovak'), ['sk', 'slo', 'slk', 'Slovak']),
    (N_('Swedish'), ['sv', 'swe', 'Swedish']),
    (N_('Danish'), ['da', 'dan', 'Danish']),
    (N_('Norwegian'), ['no', 'nor', 'nb', 'nob', 'nn', 'nno', 'Norwegian']),
    (N_('Finnish'), ['fi', 'fin', 'Finnish']),
    (N_('Hungarian'), ['hu', 'hun', 'Hungarian']),
    (N_('Turkish'), ['tr', 'tur', 'Turkish']),
    (N_('Korean'), ['ko', 'kor', 'Korean']),
    (N_('Arabic'), ['ar', 'ara', 'Arabic']),
    (N_('Hebrew'), ['he', 'iw', 'heb', 'Hebrew']),
    (N_('Greek'), ['el', 'gre', 'ell', 'Greek']),
    (N_('Ukrainian'), ['uk', 'ukr', 'Ukrainian']),
    (N_('Afrikaans'), ['af', 'afr', 'Afrikaans']),
    (N_('Albanian'), ['sq', 'alb', 'sqi', 'Albanian']),
    (N_('Armenian'), ['hy', 'arm', 'hye', 'Armenian']),
    (N_('Basque'), ['eu', 'baq', 'eus', 'Basque']),
    (N_('Belarusian'), ['be', 'bel', 'Belarusian']),
    (N_('Bengali'), ['bn', 'ben', 'Bengali']),
    (N_('Bosnian'), ['bs', 'bos', 'Bosnian']),
    (N_('Bulgarian'), ['bg', 'bul', 'Bulgarian']),
    (N_('Catalan'), ['ca', 'cat', 'Catalan']),
    (N_('Croatian'), ['hr', 'hrv', 'Croatian']),
    (N_('Esperanto'), ['eo', 'epo', 'Esperanto']),
    (N_('Estonian'), ['et', 'est', 'Estonian']),
    (N_('Filipino'), ['tl', 'tgl', 'fil', 'Filipino', 'Tagalog']),
    (N_('Galician'), ['gl', 'glg', 'Galician']),
    (N_('Georgian'), ['ka', 'geo', 'kat', 'Georgian']),
    (N_('Hindi'), ['hi', 'hin', 'Hindi']),
    (N_('Icelandic'), ['is', 'ice', 'isl', 'Icelandic']),
    (N_('Indonesian'), ['id', 'ind', 'Indonesian']),
    (N_('Irish'), ['ga', 'gle', 'Irish']),
    (N_('Latin'), ['la', 'lat', 'Latin']),
    (N_('Latvian'), ['lv', 'lav', 'Latvian']),
    (N_('Lithuanian'), ['lt', 'lit', 'Lithuanian']),
    (N_('Macedonian'), ['mk', 'mac', 'mkd', 'Macedonian']),
    (N_('Malay'), ['ms', 'may', 'msa', 'Malay']),
    (N_('Persian'), ['fa', 'per', 'fas', 'Persian']),
    (N_('Romanian'), ['ro', 'rum', 'ron', 'Romanian']),
    (N_('Serbian'), ['sr', 'srp', 'Serbian']),
    (N_('Slovenian'), ['sl', 'slv', 'Slovenian']),
    (N_('Swahili'), ['sw', 'swa', 'Swahili']),
    (N_('Tamil'), ['ta', 'tam', 'Tamil']),
    (N_('Thai'), ['th', 'tha', 'Thai']),
    (N_('Urdu'), ['ur', 'urd', 'Urdu']),
    (N_('Vietnamese'), ['vi', 'vie', 'Vietnamese']),
    (N_('Welsh'), ['cy', 'wel', 'cym', 'Welsh']),
    (N_('Yiddish'), ['yi', 'yid', 'Yiddish']),
]
COMMON_COUNT = 24  # BOOK_LANGUAGES entries shown without "Show all"


def language_picker(preflang: str) -> dict:
    """ Split an IMP_PREFLANG value into picker languages and the entries the picker doesn't know.
        A language is selected if any of its codes is in the value. Selected languages are listed
        first in the order they appear in the value, as the first one is used where only one
        language is allowed. Then the common ones, then the rest sorted by their translated name.
        Each language also carries its value for the other language settings the picker fills in:
        'code' for magazines, 'anna' for Anna's Archive ('' if not supported), 'zlib' for Z-Library.
        Returns {'languages': [{'name', 'label', 'codes', 'code', 'anna', 'zlib', 'selected', 'common'}],
                 'other': str} """
    from lazylibrarian.annas import Language as AnnaLanguage

    wanted = [item for item in get_list(preflang, ',') if item]
    position = {}
    for idx, item in enumerate(wanted):
        position.setdefault(item.lower(), idx)
    known = set()
    languages = []
    for idx, (name, codes) in enumerate(BOOK_LANGUAGES):
        lower_codes = {code.lower() for code in codes}
        known.update(lower_codes)
        found = [position[code] for code in lower_codes if code in position]
        anna = codes[0].upper()
        languages.append({
            'name': name,
            'label': i18n.gettext(name),
            'codes': ', '.join(codes),
            'code': codes[0],
            'anna': anna if anna in AnnaLanguage.__members__ else '',
            'zlib': name.lower(),
            'selected': bool(found),
            'position': min(found) if found else 0,
            'common': idx < COMMON_COUNT,
        })
    common = [lang for lang in languages if lang['common']]
    rest = sorted((lang for lang in languages if not lang['common']), key=lambda lang: lang['label'].lower())
    selected = sorted((lang for lang in common + rest if lang['selected']), key=lambda lang: lang['position'])
    ordered = selected + [lang for lang in common + rest if not lang['selected']]
    other = [item for item in wanted if item.lower() not in known]
    return {'languages': ordered, 'other': ', '.join(other)}
