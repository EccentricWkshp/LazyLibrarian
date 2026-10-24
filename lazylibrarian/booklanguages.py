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
        first, then the common ones, then the rest sorted by their translated name.
        Returns {'languages': [{'name', 'label', 'codes', 'selected', 'common'}], 'other': str} """
    wanted = [item for item in get_list(preflang, ',') if item]
    wanted_lower = {item.lower() for item in wanted}
    known = set()
    languages = []
    for idx, (name, codes) in enumerate(BOOK_LANGUAGES):
        lower_codes = {code.lower() for code in codes}
        known.update(lower_codes)
        languages.append({
            'name': name,
            'label': i18n.gettext(name),
            'codes': ', '.join(codes),
            'selected': bool(lower_codes & wanted_lower),
            'common': idx < COMMON_COUNT,
        })
    common = [lang for lang in languages if lang['common']]
    rest = sorted((lang for lang in languages if not lang['common']), key=lambda lang: lang['label'].lower())
    ordered = common + rest
    ordered = [lang for lang in ordered if lang['selected']] + [lang for lang in ordered if not lang['selected']]
    other = [item for item in wanted if item.lower() not in known]
    return {'languages': ordered, 'other': ', '.join(other)}
