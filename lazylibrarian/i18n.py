#  This file is part of Lazylibrarian.
#
# Purpose:
#    Translation of the web UI using standard gettext .po files.
#    The .po files are read directly, so no compile step (.mo) is needed and
#    translations edited on Weblate are picked up as soon as the file changes.
#
#    Catalogs live in lazylibrarian/locale/<lang>/LC_MESSAGES/lazylibrarian.po,
#    the template for new languages is lazylibrarian/locale/lazylibrarian.pot
#    Untranslated strings fall back to the English source text.

import ast
import gettext as _gettext
import json
import logging
import os
import threading

DOMAIN = 'lazylibrarian'
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locale')
DEFAULT_LANGUAGE = 'en'
AUTO = 'auto'

_local = threading.local()
_catalogs = {}  # lang -> (mtime, translations)
_lock = threading.Lock()


class POTranslations(_gettext.NullTranslations):
    """ gettext translations loaded straight from a .po file """

    def __init__(self, filename):
        super().__init__()
        self._catalog = {}
        self.plural = lambda n: int(n != 1)
        self.plural_expr = 'n != 1'
        self.nplurals = 2
        self._parse(filename)

    def _parse(self, filename):
        entries = []
        entry = {}
        fuzzy = False
        field = None

        def finish():
            nonlocal entry, fuzzy, field
            if entry and not fuzzy:
                entries.append(entry)
            entry = {}
            fuzzy = False
            field = None

        with open(filename, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    finish()
                    continue
                if line.startswith('#'):
                    if line.startswith('#,') and 'fuzzy' in line:
                        if 'msgid' in entry:
                            finish()
                        fuzzy = True
                    elif 'msgid' in entry:
                        finish()
                    continue
                if line.startswith('"'):
                    if field:
                        entry[field] += ast.literal_eval(line)
                    continue
                key, _, value = line.partition(' ')
                if key in ('msgctxt', 'msgid') and any(k.startswith('msgstr') for k in entry):
                    finish()  # next entry without a blank line in between
                field = key
                entry[field] = ast.literal_eval(value)
            finish()

        for entry in entries:
            msgid = entry.get('msgid')
            if msgid is None:
                continue
            if 'msgctxt' in entry:
                msgid = f"{entry['msgctxt']}\x04{msgid}"
            if msgid == '':
                self._parse_header(entry.get('msgstr', ''))
                continue
            if 'msgid_plural' in entry:
                idx = 0
                while f'msgstr[{idx}]' in entry:
                    if entry[f'msgstr[{idx}]']:
                        self._catalog[(msgid, idx)] = entry[f'msgstr[{idx}]']
                    idx += 1
            elif entry.get('msgstr'):
                self._catalog[msgid] = entry['msgstr']

    def _parse_header(self, header):
        for line in header.splitlines():
            name, _, value = line.partition(':')
            if name.strip().lower() == 'plural-forms':
                for part in value.split(';'):
                    part = part.strip()
                    if part.startswith('nplurals='):
                        try:
                            self.nplurals = int(part[len('nplurals='):])
                        except ValueError:
                            pass
                    elif part.startswith('plural='):
                        expr = part[len('plural='):].strip()
                        try:
                            # c2py also validates the expression, so it is safe to reuse in javascript
                            # noinspection PyProtectedMember,PyUnresolvedReferences
                            self.plural = _gettext.c2py(expr)
                            self.plural_expr = expr
                        except (ValueError, SyntaxError):
                            pass

    def gettext(self, message):
        return self._catalog.get(message) or message

    def ngettext(self, msgid1, msgid2, n):
        tmsg = self._catalog.get((msgid1, self.plural(n)))
        if tmsg:
            return tmsg
        return msgid1 if n == 1 else msgid2

    def pgettext(self, context, message):
        return self._catalog.get(f"{context}\x04{message}") or message

    def plural_forms(self, msgid1):
        """ All translated plural forms of msgid1, or None if any are missing """
        forms = [self._catalog.get((msgid1, idx)) for idx in range(self.nplurals)]
        return forms if all(forms) else None

    def npgettext(self, context, msgid1, msgid2, n):
        tmsg = self._catalog.get((f"{context}\x04{msgid1}", self.plural(n)))
        if tmsg:
            return tmsg
        return msgid1 if n == 1 else msgid2


def _po_file(lang):
    return os.path.join(LOCALE_DIR, lang, 'LC_MESSAGES', f'{DOMAIN}.po')


def available_languages():
    """ Return a sorted list of language codes that have a translation, plus English """
    langs = {DEFAULT_LANGUAGE}
    if os.path.isdir(LOCALE_DIR):
        for lang in os.listdir(LOCALE_DIR):
            if os.path.isfile(_po_file(lang)):
                langs.add(lang)
    return sorted(langs)


def language_name(lang):
    """ Human-readable name for a language code, for the config page """
    try:
        from iso639 import Lang
        return Lang(lang.split('_')[0]).name
    except Exception:
        return lang


def get_translations(lang):
    """ Return the translations for lang, reloading if the .po file has changed """
    if not lang or lang == DEFAULT_LANGUAGE:
        return _gettext.NullTranslations()
    filename = _po_file(lang)
    try:
        mtime = os.path.getmtime(filename)
    except OSError:
        return _gettext.NullTranslations()
    with _lock:
        cached = _catalogs.get(lang)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            translations = POTranslations(filename)
        except Exception as e:
            logging.getLogger(__name__).error(f"Unable to load translation {filename}: {e}")
            translations = _gettext.NullTranslations()
        _catalogs[lang] = (mtime, translations)
        return translations


def match_accept_language(header, languages=None):
    """ Pick the best available language from an Accept-Language header """
    if not header:
        return DEFAULT_LANGUAGE
    if languages is None:
        languages = available_languages()
    lookup = {lang.lower().replace('-', '_'): lang for lang in languages}
    requested = []
    for pos, part in enumerate(header.split(',')):
        code, _, params = part.strip().partition(';')
        quality = 1.0
        params = params.strip()
        if params.startswith('q='):
            try:
                quality = float(params[2:])
            except ValueError:
                quality = 0.0
        if code and quality > 0:
            requested.append((-quality, pos, code.strip().lower().replace('-', '_')))
    for _, _, code in sorted(requested):
        if code in lookup:
            return lookup[code]
        primary = code.split('_')[0]
        if primary in lookup:
            return lookup[primary]
    return DEFAULT_LANGUAGE


def resolve_language(setting, accept_header=''):
    """ Turn the UI_LANGUAGE setting into a language code we have a translation for """
    setting = (setting or '').strip()
    if not setting or setting.lower() == AUTO:
        return match_accept_language(accept_header)
    if setting in available_languages():
        return setting
    return DEFAULT_LANGUAGE


def set_language(lang):
    """ Set the language used by gettext() and friends for the current thread (request) """
    _local.lang = lang or DEFAULT_LANGUAGE
    _local.translations = get_translations(_local.lang)


def get_language():
    return getattr(_local, 'lang', DEFAULT_LANGUAGE)


def _current():
    translations = getattr(_local, 'translations', None)
    if translations is None:
        translations = _gettext.NullTranslations()
    return translations


def gettext(message):
    return _current().gettext(message)


def ngettext(singular, plural, n):
    return _current().ngettext(singular, plural, n)


def pgettext(context, message):
    return _current().pgettext(context, message)


def npgettext(context, singular, plural, n):
    return _current().npgettext(context, singular, plural, n)


def js_string(text):
    """ text (or a dict/list) as a javascript literal, safe to use inside <script> blocks """
    return json.dumps(text).replace('</', '<\\/')


def gettext_js(message):
    """ Translated message as a quoted javascript string literal """
    return js_string(gettext(message))


def ngettext_js(singular, plural):
    """ Plural forms for llNgettext() in base.html, for when the count is only known in the browser.
        Returns a javascript object literal: f = the forms, t = true if translated """
    translations = _current()
    forms = translations.plural_forms(singular) if isinstance(translations, POTranslations) else None
    if forms:
        return js_string({'f': forms, 't': True})
    return js_string({'f': [singular, plural], 't': False})


def plural_expression():
    """ The C plural expression of the current language, which is also valid javascript """
    translations = _current()
    if isinstance(translations, POTranslations):
        return translations.plural_expr
    return 'n != 1'


_ = gettext
