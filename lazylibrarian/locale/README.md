# Web UI translations

The web interface can be shown in other languages using standard gettext `.po` files.
Pick the language in **Config > Interface > Appearance > Interface language**. "Automatic" follows the
browser's `Accept-Language` header. The default is English, so nothing changes for
existing installs. Any string without a translation is shown in English, so a partial
translation is fine.

Log messages and the API stay in English.

## Files

```
lazylibrarian/locale/lazylibrarian.pot                    template, generated, do not edit
lazylibrarian/locale/<lang>/LC_MESSAGES/lazylibrarian.po  one catalog per language
```

The `.po` files are read directly by `lazylibrarian/i18n.py`. You don't need to compile
`.mo` files, and an edited `.po` file is picked up on the next page load.

## For translators

Translations are managed with standard `.po` files, so you can use any gettext tool
(Weblate, Poedit, Lokalize, ...). Please keep:

- `%(count)s` / `%(count)d` placeholders as they are, wherever they fit in your sentence
- the DataTables placeholders `_MENU_`, `_START_`, `_END_`, `_TOTAL_`, `_MAX_` as they are
- HTML-free text: the markup stays in the templates

To add a new language, create its catalog from the template (replace `sk` with your
language code):

```
pybabel init -D lazylibrarian -i lazylibrarian/locale/lazylibrarian.pot -d lazylibrarian/locale -l sk
```

## For developers

Templates get these helpers from `serve_template()` in `webServe.py`:

| Helper | Use |
|---|---|
| `${_('Text')}` | text in HTML |
| `${_('Text') \| h}` | text in an HTML attribute (`title`, `placeholder`, ...) |
| `${_js('Text')}` | a quoted string literal inside `<script>` |
| `${ngettext('one book', '%(count)s books', n) % {'count': n}}` | plurals with a count known on the server |
| `llNgettext(${_jsn('one book', '%(count)s books')}, n)` | plurals with a count only known in the browser |
| `llDataTablesLanguage` | shared DataTables labels: `"oLanguage": $.extend({}, llDataTablesLanguage, {...})` |

Notes:

- Translate whole sentences and use named placeholders. Don't glue fragments together,
  because word order differs between languages.
- Add a hint for translators with a Mako comment directly above the line:
  `## TRANSLATORS: _MAX_ is replaced by a number`

After adding or changing strings, regenerate the template and update the catalogs
(`pip install babel` first):

```
make translations
```

The translation platform (e.g. Hosted Weblate) watches the `.pot` file and the `.po`
files in the repository, so translators see new strings once the updated `.pot` file
is committed.
