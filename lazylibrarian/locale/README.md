# Web UI translations

The web interface can be shown in other languages using standard gettext `.po` files.
Pick the language in **Config > Interface > Appearance > Interface language**. The default
is "Automatic", which follows the browser's `Accept-Language` header and falls back to English
when there is no translation for it. With user accounts, each user can also pick their own
language. Any string without a translation is shown in English, so a partial translation is fine.

Log messages and the API stay in English.

## Files

```
lazylibrarian/locale/lazylibrarian.pot                    template, generated, do not edit
lazylibrarian/locale/<lang>/LC_MESSAGES/lazylibrarian.po  one catalog per language
```

The `.po` files are read directly by `lazylibrarian/i18n.py`. You don't need to compile
`.mo` files, and an edited `.po` file is picked up on the next page load.

## For translators

Translations are done on Hosted Weblate:
https://hosted.weblate.org/projects/lazylibrarian/

[![Translation status](https://hosted.weblate.org/widget/lazylibrarian/webui/multi-auto.svg)](https://hosted.weblate.org/engage/lazylibrarian/)

Sign in, pick your language (or use "Start new translation" to add one) and translate
in the browser. No git or coding is needed. Weblate sends the translations back to this
repository as merge requests.

Please don't edit the `.po` files in the repository directly. Weblate keeps its own
copy, so changes made outside it lead to conflicts with its merge requests. If you
prefer an offline tool (Poedit, Lokalize, ...), download the file from Weblate and
upload it back there when you're done.

When translating, please keep:

- `%(count)s` / `%(count)d` placeholders as they are, wherever they fit in your sentence
- the DataTables placeholders `_MENU_`, `_START_`, `_END_`, `_TOTAL_`, `_MAX_` as they are
- HTML-free text: the markup stays in the templates

New languages are added in Weblate, which creates the `.po` file from the template.

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
- Python code that answers the browser (dialog texts, AJAX replies) uses `i18n.gettext()` /
  `i18n.ngettext()`. Log messages stay in English: when a message is both logged and shown,
  log the English text and return the translated one. `i18n.N_('Text')` marks a string for
  extraction without translating it, for messages that are translated later with `i18n.gettext()`.

After adding or changing strings, regenerate the template (`pip install babel` first):

```
make translations
```

Commit only the updated `.pot` file. Weblate watches the repository and merges the new
strings into every `.po` file itself (msgmerge add-on), so translators see them after the
push to `master`. Translations come back as merge requests from Weblate. Merging them
is all that's needed, there's no compile step.

The Weblate component is set up as:

| Setting | Value |
|---|---|
| Repository / branch | `https://gitlab.com/LazyLibrarian/LazyLibrarian.git`, `master` |
| File format | gettext PO file |
| File mask | `lazylibrarian/locale/*/LC_MESSAGES/lazylibrarian.po` |
| Template for new translations | `lazylibrarian/locale/lazylibrarian.pot` |
| Add-ons | "Update PO files to match POT (msgmerge)" |
