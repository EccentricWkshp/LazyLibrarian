#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing functionality in dbk.py (Databáze knih) without network access

from queue import Queue
from unittest import mock

from lazylibrarian import dbk
from lazylibrarian.config2 import CONFIG
from lazylibrarian.dbupgrade import has_column
from lazylibrarian.database import DBConnection
from unittests.unittesthelpers import LLTestCaseWithStartup

# Shortened copies of real pages from https://www.databazeknih.cz
BOOK_PAGE = r"""<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Book",
  "name": "Krev elfů",
  "url": "https://www.databazeknih.cz/prehled-knihy/zaklinac-saga-krev-elfu-30482",
    "isbn": "80-85951-05-3",
    "author": [
          {
        "@type": "Person",
        "name": "Andrzej Sapkowski"
      }      ],
  "image": "https:\/\/www.databazeknih.cz\/img\/books\/30_\/30482\/bmid_krev-elfu-Jqe-30482.jpg",
    "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.6",
    "ratingCount": "5790",
    "bestRating": "5",
    "worstRating": "1"
  },
    "description": "První část…",
    "publisher": [
          {
        "@type": "Organization",
        "name": "Leonardo"
      }      ],
    "inLanguage": "cs",
  "genre": [
          "Literatura světová",          "Romány",          "Fantasy"      ]}
</script></head><body>
<div class="lora book_detail_serie_info">
    <p class="inline">
        <a class="odright_pet" href='/serie/zaklinac-saga---7063?lang=cz' title='Zaklínač: sága'>
            Zaklínač: sága
        </a> série</p>
    <span class="nowrap">
        <span class="odright_pet">1. díl</span>
    </span>
    <br />
    <p class="inline">
        <a class="odright_pet" href='/serie/zaklinac-zaklinac-13665?lang=cz' title='Zaklínač'>
            Zaklínač
        </a> série</p>
    3. díl
</div>
<h1 class="oddown_zero">Krev elfů</h1>
<div class="lora lineHeightMid">
    <a href='/zanry/fantasy-21'>Fantasy</a><br />
    1998
    <span class='pozn'>,</span> <a href='/nakladatelstvi/leonardo-338'>Leonardo</a>
</div>
<div id='left'>
    <h2>O knize <em class="nobold">Krev elfů</em></h2>
    <p class='new2 odtop'>První část ságy o Zaklínači.
Geralt, Ciri, Yennefer a další.</p>
</div>
</body></html>"""

MORE_INFO = """
<div class='book-details__row'><dt>Originální název</dt><dd>Krew elfów, 1994</dd></div>
<div class='book-details__row'><dt>Počet stran</dt><dd><span itemprop='numberOfPages'>308</span></dd></div>
<div class='book-details__row'><dt>Jazyk vydání</dt><dd>český</dd></div>
<div class='book-details__row'><dt>ISBN</dt><dd>80-85951-05-3</dd></div>
"""

SEARCH_PAGE = """<html><body>
<p class='new'>
    <a href="/prehled-knihy/zaklinac-saga-krev-elfu-30482"><picture>
        <img src="https://www.databazeknih.cz/img/books/30_/30482/krev-elfu-Jqe-30482.jpg?v=1577582533"
             alt="Obálka knihy Krev elfů" class="img_39_left odtopm" /></picture></a>
    <img src='img/content/squares/red.gif' title='91%' alt='91%' class='odr' /><a class='new' type='book'
        href='/prehled-knihy/zaklinac-saga-krev-elfu-30482'>Krev elfů</a>
    <br /><span class='pozn'>
        1998,
        Andrzej Sapkowski
    </span>
</p>
<p class='new'>
    <img src='img/content/squares/blue.gif' title='47%' alt='47%' class='odr' /><a class='new' type='book'
        href='/prehled-knihy/john-sinclair-na-stope-hruzy-zaklinac-40113'>Zaklínač</a>
    <br /><span class='pozn'>
        1998,
        Jason Dark (p)
    </span>
</p>
<div class="pager"><div class="pagination">
    <span class="current">1</span>
    <span class="next"><a rel="next" href="/vyhledavani/knihy?q=krev&amp;page=2">&gt;</a></span>
</div></div>
</body></html>"""

AUTHOR_BOOKS_PAGE = """<html><body>
<h3 class='midlRowHeight oddown'>
    <a href='/prehled-knihy/krev-elfu-433' title='Krev elfů'>Krev elfů</a>
    <span class='pozn odl'> 2011 (1. vydání 1994) </span>
</h3>
<h3 class='midlRowHeight oddown'>
    <a href='/prehled-knihy/magicke-stripky-30500' title='Magické střípky'>Magické střípky</a>
    <span class='pozn odl'> 2002 (1. vydání) </span>
</h3>
<h3>Až vyjde nová kniha autora</h3>
<div class="pager"><div class="pagination"></div></div>
</body></html>"""

SERIES_PAGE = """<html><body>
<div itemprop="hasPart" itemscope itemtype="https://schema.org/Book">
    <span class="gray odright_pet">2. v sérii</span>
    <a class='biggest odr' href='/prehled-knihy/zaklinac-saga-cas-opovrzeni-30399' title='Čas opovržení'>Čas opovržení</a>
    <span class='pozn odtop'><a href="/serie-autora/andrzej-sapkowski-269">Andrzej Sapkowski</a>, 2007</span>
</div>
<div itemprop="hasPart" itemscope itemtype="https://schema.org/Book">
    <span class="gray odright_pet">1. v sérii</span>
    <a class='biggest odr' href='/prehled-knihy/krev-elfu-433' title='Krev elfů'>Krev elfů</a>
    <span class='pozn odtop'><a href="/serie-autora/andrzej-sapkowski-269">Andrzej Sapkowski</a>, 2011</span>
</div>
</body></html>"""

AUTHOR_SEARCH_PAGE = """<html><body>
<a href="autori/andrzej-sapkowski-269">Andrzej Sapkowski</a>
<a href="autori/andrzej-sapkowski-ml-99999">Andrzej Nowak</a>
</body></html>"""


class DBKTest(LLTestCaseWithStartup):

    @classmethod
    def setUpClass(cls) -> None:
        rc = super().setUpClass()
        cls.dbk_api = CONFIG.get_bool('DBK_API')
        cls.preflang = CONFIG.get_csv('IMP_PREFLANG')
        CONFIG.set_bool('DBK_API', True)
        CONFIG.set_csv('IMP_PREFLANG', 'cs, Czech')
        return rc

    @classmethod
    def tearDownClass(cls) -> None:
        CONFIG.set_bool('DBK_API', cls.dbk_api)
        CONFIG.set_csv('IMP_PREFLANG', cls.preflang)
        return super().tearDownClass()

    def test_id_from_link(self):
        self.assertEqual(dbk.DBK._id_from_link('/prehled-knihy/krev-elfu-433'), '433')
        self.assertEqual(dbk.DBK._id_from_link('/serie/zaklinac-saga---7063?lang=cz'), '7063')
        self.assertEqual(dbk.DBK._id_from_link('autori/andrzej-sapkowski-269'), '269')
        self.assertEqual(dbk.DBK._id_from_link('/prehled-knihy/'), '')

    def test_parse_book(self):
        book = dbk.DBK()._parse_book(BOOK_PAGE, MORE_INFO)
        self.assertEqual(book['bookid'], '30482')
        self.assertEqual(book['bookname'], 'Krev elfů')
        self.assertEqual(book['authorname'], 'Andrzej Sapkowski')
        self.assertEqual(book['bookisbn'], '8085951053')
        self.assertEqual(book['bookpub'], 'Leonardo')
        # first publication from the original title, not this edition's 1998
        self.assertEqual(book['bookdate'], '1994')
        self.assertEqual(book['booklang'], 'Czech')
        self.assertEqual(book['bookpages'], 308)
        self.assertEqual(book['bookrate'], 4.6)
        self.assertEqual(book['bookrate_count'], 5790)
        self.assertEqual(book['bookgenre'], 'Literatura světová,Romány,Fantasy')
        self.assertTrue(book['bookimg'].startswith('https://www.databazeknih.cz/img/books/'))
        # the whole description from the page, not the shortened json-ld one
        self.assertTrue(book['bookdesc'].startswith('První část ságy o Zaklínači.\nGeralt'))
        self.assertEqual(book['series'], [('Zaklínač: sága', 'DBK7063', '1'), ('Zaklínač', 'DBK13665', '3')])
        self.assertEqual(book['source'], 'DBK')

    def test_parse_book_without_more_info(self):
        book = dbk.DBK()._parse_book(BOOK_PAGE)
        self.assertEqual(book['bookdate'], '1998')
        self.assertEqual(book['bookpages'], 0)

    def test_parse_book_not_a_book(self):
        self.assertEqual(dbk.DBK()._parse_book(SEARCH_PAGE), {})

    def test_parse_search(self):
        results, next_page = dbk.DBK()._parse_search(SEARCH_PAGE)
        self.assertEqual([r['bookid'] for r in results], ['30482', '40113'])
        self.assertEqual(results[0]['authors'], ['Andrzej Sapkowski'])
        self.assertEqual(results[0]['bookdate'], '1998')
        self.assertEqual(results[0]['bookrate'], 4.55)
        # pseudonym marker removed
        self.assertEqual(results[1]['authors'], ['Jason Dark'])
        self.assertEqual(results[1]['bookimg'], 'images/nocover.png')
        self.assertEqual(next_page, '/vyhledavani/knihy?q=krev&page=2')

    def test_parse_book_list(self):
        books, next_page = dbk.DBK()._parse_book_list(AUTHOR_BOOKS_PAGE)
        self.assertEqual(books, [('433', 'Krev elfů', '1994'), ('30500', 'Magické střípky', '2002')])
        self.assertEqual(next_page, '')

    def test_series_members(self):
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(SERIES_PAGE, True)) as fetch:
            members = dbk.DBK().get_series_members('DBK7063', 'Zaklínač: sága')
            self.assertEqual(fetch.call_args[0][0], 'https://www.databazeknih.cz/serie/serie-7063')
        self.assertEqual(members, [('1', 'Krev elfů', 'Andrzej Sapkowski', '', '433', '2011'),
                                   ('2', 'Čas opovržení', 'Andrzej Sapkowski', '', '30399', '2007')])

    def test_search_language(self):
        dbk_api = dbk.DBK()
        try:
            for prefs, expected in [('cs, Czech', 'cz'), ('sk', 'sk'), ('Czech, Slovak', 'czsk'),
                                    ('en, eng, en-US, en-GB, English', 'en'), ('All', ''), ('Czech, German', '')]:
                CONFIG.set_csv('IMP_PREFLANG', prefs)
                self.assertEqual(dbk_api._search_language(), expected, prefs)
        finally:
            CONFIG.set_csv('IMP_PREFLANG', 'cs, Czech')

    def test_find_results(self):
        pages = {'https://www.databazeknih.cz/vyhledavani/knihy?q=Krev+elf%C5%AF&lang=cz': SEARCH_PAGE}
        with mock.patch.object(dbk.DBK, '_fetch', side_effect=lambda url: (pages.get(url, ''), False)) as fetch:
            queue = Queue()
            self.assertTrue(dbk.DBK().find_results('Krev elfů (Zaklínač, #3)<ll>Andrzej Sapkowski', queue))
            # series suffix and author are left out of the title search
            self.assertEqual(fetch.call_args_list[0][0][0], list(pages)[0])
        results = queue.get()
        self.assertEqual(len(results), 2)
        best = max(results, key=lambda r: r['highest_fuzz'])
        self.assertEqual(best['bookid'], '30482')
        self.assertEqual(best['source'], 'DBK')

    def test_find_results_isbn(self):
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(BOOK_PAGE, False)) as fetch:
            queue = Queue()
            self.assertTrue(dbk.DBK().find_results('80-85951-05-3', queue))
            self.assertEqual(fetch.call_args[0][0], 'https://www.databazeknih.cz/search?q=8085951053')
        results = queue.get()
        self.assertEqual(results[0]['bookid'], '30482')
        self.assertEqual(results[0]['isbn_fuzz'], 100)

    def test_find_author(self):
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(AUTHOR_SEARCH_PAGE, False)):
            self.assertEqual(dbk.DBK()._find_author('Andrzej Sapkowski'), '269')
            self.assertEqual(dbk.DBK()._find_author('Terry Pratchett'), '')

    def test_find_results_author_only(self):
        pages = {'https://www.databazeknih.cz/search?in=authors&q=Andrzej+Sapkowski': AUTHOR_SEARCH_PAGE,
                 'https://www.databazeknih.cz/vydane-knihy/autor-269': AUTHOR_BOOKS_PAGE}
        with mock.patch.object(dbk.DBK, '_fetch', side_effect=lambda url: (pages.get(url, ''), False)):
            queue = Queue()
            self.assertTrue(dbk.DBK().find_results('<ll>Andrzej Sapkowski', queue))
        results = queue.get()
        self.assertEqual([r['bookid'] for r in results], ['433', '30500'])
        self.assertEqual(results[0]['authorname'], 'Andrzej Sapkowski')

    def test_dbk_id_columns(self):
        db = DBConnection()
        try:
            self.assertTrue(has_column(db, 'books', 'dbk_id'))
            self.assertTrue(has_column(db, 'authors', 'dbk_id'))
        finally:
            db.close()
