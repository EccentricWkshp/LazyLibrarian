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

""" Magazines on Wikidata, free and open: finding a magazine's item by its title, and what the item
says about it, with the opening of its Wikipedia article as the description """

import logging
import re
from urllib.parse import quote, urlencode

from lazylibrarian.cache import json_request

API = 'https://www.wikidata.org/w/api.php'
SPARQL = 'https://query.wikidata.org/sparql'
# periodical literature: magazines, journals and newspapers are all kinds of it
PERIODICAL = 'Q1002697'
# the units of a publication interval, in days
UNIT_DAYS = {'Q573': 1, 'Q23387': 7, 'Q5151': 30, 'Q577': 365}
# how often a magazine is published, from the kind of periodical it is when it gives no interval
KIND_DAYS = (('daily', 1), ('biweekly', 14), ('fortnightly', 14), ('weekly', 7), ('bimonthly', 61),
             ('monthly', 30), ('quarterly', 91), ('biannual', 182), ('semiannual', 182), ('annual', 365))


def _get(params: dict, url: str = API):
    result, _ = json_request(f"{url}?{urlencode({**params, 'format': 'json'})}")
    return result or {}


def _label(entity: dict, language: str) -> str:
    labels = entity.get('labels') or {}
    found = labels.get(language) or labels.get('en') or next(iter(labels.values()), {})
    return found.get('value', '') if isinstance(found, dict) else ''


def _description(entity: dict, language: str) -> str:
    descriptions = entity.get('descriptions') or {}
    found = descriptions.get(language) or descriptions.get('en') or {}
    return found.get('value', '')


def search(title: str, language: str = 'en') -> list[dict]:
    """ The periodicals a title finds, best first: each its id, label, description and the year it
    started """
    logger = logging.getLogger(__name__)
    title = re.sub(r'\s+', ' ', title or '').strip()
    if not title:
        return []
    # nothing in it ends the query's string
    quoted = re.sub(r'["\\]', ' ', title)
    query =f"""SELECT ?item ?itemLabel ?itemDescription (MIN(?started) AS ?start) (MIN(?ordinal) AS ?rank) WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:api "EntitySearch"; wikibase:endpoint "www.wikidata.org";
                    mwapi:search "{quoted}"; mwapi:language "{language}".
    ?item wikibase:apiOutputItem mwapi:item. ?ordinal wikibase:apiOrdinal true.
  }}
  ?item wdt:P31/wdt:P279* wd:{PERIODICAL}.
  OPTIONAL {{ ?item wdt:P571 ?started. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{language},en". }}
}} GROUP BY ?item ?itemLabel ?itemDescription ORDER BY ?rank"""
    result = _get({'query': query}, SPARQL)
    found = []
    for row in (result.get('results') or {}).get('bindings') or []:
        item_id = row['item']['value'].rsplit('/', 1)[-1]
        found.append({'id': item_id, 'label': row.get('itemLabel', {}).get('value', ''),
                      'description': row.get('itemDescription', {}).get('value', ''),
                      'started': row.get('start', {}).get('value', '')[:4]})
    if not result:
        logger.debug(f"Wikidata found nothing for {title}, or couldn't be reached")
    # the one called exactly that first, the search's order after
    return sorted(found, key=lambda item: item['label'].casefold() != title.casefold())


def _claims(entity: dict, prop: str) -> list:
    """ The values of a property, its preferred ones if it has any """
    statements = (entity.get('claims') or {}).get(prop) or []
    preferred = [s for s in statements if s.get('rank') == 'preferred']
    values = []
    for statement in preferred or [s for s in statements if s.get('rank') != 'deprecated']:
        value = ((statement.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if value is not None:
            values.append(value)
    return values


def _entities(ids: list[str], props: str) -> dict:
    found = {}
    for start in range(0, len(ids), 50):
        result = _get({'action': 'wbgetentities', 'ids': '|'.join(ids[start:start + 50]), 'props': props})
        found.update(result.get('entities') or {})
    return found


def _wikipedia_extract(entity: dict, language: str) -> str:
    """ The opening of the item's Wikipedia article, in the language if there's one in it """
    sitelinks = entity.get('sitelinks') or {}
    for lang in dict.fromkeys((language, 'en')):
        link = sitelinks.get(f"{lang}wiki")
        if link:
            result = _get({}, f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                              f"{quote(link['title'].replace(' ', '_'), safe='')}")
            if result.get('extract'):
                return result['extract']
    return ''


def _frequency(entity: dict, kinds: list[str]) -> int:
    """ Days between issues, from the publication interval, else the kind of periodical it is """
    for value in _claims(entity, 'P2896'):
        unit = str(value.get('unit', '')).rsplit('/', 1)[-1]
        try:
            amount = float(value.get('amount', 0))
        except (TypeError, ValueError):
            continue
        if unit in UNIT_DAYS and amount > 0:
            return round(amount * UNIT_DAYS[unit])
    for kind in kinds:
        for word, days in KIND_DAYS:
            if word in kind.lower():
                return days
    return 0


def details(item_id: str, language: str = 'en') -> dict:
    """ What a periodical's item says about it: label, description, publisher, ISSN, country, how
    many days between issues (0 when it doesn't say), website, logo (a picture's URL), the date it
    started and its subjects. Empty if there's no such item """
    entity = _entities([item_id], 'labels|descriptions|claims|sitelinks').get(item_id) or {}
    if not entity or 'missing' in entity:
        return {}
    linked = [value['id'] for prop in ('P123', 'P495', 'P31', 'P921', 'P136')
              for value in _claims(entity, prop) if isinstance(value, dict) and 'id' in value]
    labels = {key: _label(value, language) for key, value in
              (_entities(list(dict.fromkeys(linked)), 'labels') if linked else {}).items()}

    def names(prop: str) -> list[str]:
        return [labels[value['id']] for value in _claims(entity, prop)
                if isinstance(value, dict) and labels.get(value.get('id'))]

    started = next((value.get('time', '') for value in _claims(entity, 'P571') if isinstance(value, dict)), '')
    picture = next(iter(_claims(entity, 'P154') or _claims(entity, 'P18')), '')
    return {'id': item_id, 'label': _label(entity, language),
            'description': _wikipedia_extract(entity, language) or _description(entity, language),
            'publisher': ', '.join(names('P123')), 'issn': ', '.join(dict.fromkeys(_claims(entity, 'P236'))),
            'country': ', '.join(names('P495')), 'frequency': _frequency(entity, names('P31')),
            'website': next(iter(_claims(entity, 'P856')), ''),
            'logo': f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(picture.replace(' ', '_'))}?width=400"
                    if picture else '',
            'started': started.lstrip('+')[:4] if started else '',
            'subjects': list(dict.fromkeys(names('P921') + names('P136')))}
