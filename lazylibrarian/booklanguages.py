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
        first in the order they appear in the value, then the common ones, then the rest sorted
        by their translated name.
        Each language also carries its value for the other language settings the picker fills in:
        'anna' for Anna's Archive ('' if not supported), 'zlib' for Z-Library.
        Returns {'languages': [{'name', 'label', 'codes', 'anna', 'zlib', 'selected', 'common'}],
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


# ISO 3166-1 alpha-2 codes for the GoogleBooks country setting, the browser shows their names
GB_COUNTRIES = [
    'AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AT', 'AU', 'AW', 'AX',
    'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ',
    'BR', 'BS', 'BT', 'BV', 'BW', 'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK',
    'CL', 'CM', 'CN', 'CO', 'CR', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ', 'DK', 'DM',
    'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK', 'FM', 'FO', 'FR',
    'GA', 'GB', 'GD', 'GE', 'GF', 'GG', 'GH', 'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS',
    'GT', 'GU', 'GW', 'GY', 'HK', 'HM', 'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN',
    'IO', 'IQ', 'IR', 'IS', 'IT', 'JE', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN',
    'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK', 'LR', 'LS', 'LT', 'LU', 'LV',
    'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH', 'MK', 'ML', 'MM', 'MN', 'MO', 'MP', 'MQ',
    'MR', 'MS', 'MT', 'MU', 'MV', 'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI',
    'NL', 'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK', 'PL', 'PM',
    'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS', 'RU', 'RW', 'SA', 'SB', 'SC',
    'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SV',
    'SX', 'SY', 'SZ', 'TC', 'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR',
    'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE', 'VG', 'VI',
    'VN', 'VU', 'WF', 'WS', 'YE', 'YT', 'ZA', 'ZM', 'ZW',
]


def country_picker(gb_country: str) -> dict:
    """ Countries for the GoogleBooks country select and the one to select.
        GoogleBooks takes a single country, anything else was ignored so it selects automatic ('').
        Returns {'countries': [codes], 'selected': str} """
    country = gb_country.strip().upper()
    return {'countries': GB_COUNTRIES, 'selected': country if country in GB_COUNTRIES else ''}


def magazine_language_picker(pref_maglang: str) -> dict:
    """ Languages for the default magazine language select, sorted by their translated name.
        Magazines take a single code, the ISO 639-1 one. A stored value that isn't one of these
        codes is returned as 'other' so the select can keep it and saving doesn't change it.
        Returns {'languages': [{'code', 'label'}], 'selected': str, 'other': str | None} """
    languages = sorted(({'code': codes[0], 'label': i18n.gettext(name)} for name, codes in BOOK_LANGUAGES),
                       key=lambda lang: lang['label'].lower())
    value = pref_maglang.strip()
    for lang in languages:
        if lang['code'].lower() == value.lower():
            return {'languages': languages, 'selected': lang['code'], 'other': None}
    return {'languages': languages, 'selected': value, 'other': value}
