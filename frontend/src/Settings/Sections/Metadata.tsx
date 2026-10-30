// Sonarr's Settings, Metadata Source and Metadata: where authors and books are looked up, the reading
// lists synced, which books are added, their genres, and the opf and cover files written
import { Group, Option, Values } from './fields';
import SettingsSection from './SettingsSection';

const USES = ['MAG_TAB', 'COMIC_TAB'];

// the sources that are on, by the name BOOK_API has for each
function sourcesOn(values: Values): Option[] {
  const sources: [string, string, boolean][] = [
    ['OpenLibrary', 'OpenLibrary', !!values.OL_API],
    ['HardCover', 'HardCover', !!values.HC_API],
    ['GoogleBooks', 'GoogleBooks', !!values.GB_API],
    ['GoodReads', 'Goodreads', !!values.GR_API],
    ['DNB', 'Deutsche Nationalbibliothek', !!values.DNB_API],
    ['BN', 'Biblioteka Narodowa', !!values.BN_API],
    ['DBK', 'Databáze knih', !!values.DBK_API],
    ['RanobeDB', 'RanobeDB', !!values.RAN_API],
  ];
  return sources.filter(([, , on]) => on).map(([key, value]) => ({ key, value }));
}

const GROUPS: Group[] = [
  {
    legend: 'Metadata Source',
    help: 'Where authors and books are looked up',
    fields: [
      {
        key: 'BOOK_API',
        label: 'Searched first',
        input: 'select',
        optionsFor: sourcesOn,
        help: 'Of the sources that are on',
      },
      {
        key: 'MULTI_SOURCE',
        label: "Add authors' books from all the sources that are on",
        help: "Not just the first one's: books only another source knows are added too",
      },
      {
        key: 'FILL_MISSING',
        label: 'Fill in missing details from every source',
        help: "A book's or author's description, ISBN, pages, publisher, genres, cover, series or biography, when its own source hasn't got them. Asked again after the cache's days",
      },
      { key: 'OL_API', label: 'OpenLibrary' },
      { key: 'HC_API', label: 'HardCover' },
      { key: 'GB_API', label: 'GoogleBooks API Key', input: 'password', help: 'Each user needs their own, it has a daily limit' },
      { key: 'DNB_API', label: 'Deutsche Nationalbibliothek', help: 'German books' },
      { key: 'BN_API', label: 'Biblioteka Narodowa', help: 'Polish books' },
      {
        key: 'DBK_API',
        label: 'Databáze knih',
        help: 'Czech and Slovak books. Add the languages to the preferred ones, see Languages, to keep them',
      },
      { key: 'RAN_API', label: 'RanobeDB', help: 'Light novels' },
      {
        key: 'AUDNEXUS',
        label: 'Audnexus for audiobooks',
        help: 'The narrator, genres, description and cover of an audiobook you have, by its ASIN',
      },
      {
        key: 'GR_API',
        label: 'Goodreads API Key',
        input: 'password',
        help: 'Goodreads gives no new keys, it only works with one you have',
        advanced: true,
      },
      { key: 'LT_DEVKEY', label: 'LibraryThing Key', input: 'password', advanced: true },
      { key: 'MAX_BOOKPAGES', label: "Pages of an author's books", help: 'Looked up, 0 for all', advanced: true },
      { key: 'CV_APIKEY', label: 'ComicVine API Key', input: 'password', showIf: (v) => !!v.COMIC_TAB },
      {
        key: 'CV_WEBSEARCH',
        label: 'Search the ComicVine site',
        help: "When the API finds nothing. It can get the API key blocked",
        showIf: (v) => !!v.COMIC_TAB,
        advanced: true,
      },
    ],
  },
  {
    legend: 'OpenLibrary Copy',
    help: "A copy of OpenLibrary's data, looked up here instead of asking OpenLibrary",
    advanced: true,
    showIf: (v) => !!v.OL_API,
    fields: [
      { key: 'OL_USE_DUMP', label: 'Use a local copy' },
      { key: 'OL_DUMP_DIR', label: 'Folder', showIf: (v) => !!v.OL_USE_DUMP },
      { key: 'OL_DUMP_INTERVAL', label: 'Update it every', showIf: (v) => !!v.OL_USE_DUMP },
    ],
  },
  {
    legend: 'HardCover Sync',
    help: "Your reading lists with HardCover's. The HardCover token is in your profile",
    showIf: (v) => !!v.HC_API,
    fields: [
      { key: 'HC_SYNC', label: 'Sync' },
      { key: 'HARDCOVER_INTERVAL', label: 'Every', showIf: (v) => !!v.HC_SYNC },
      { key: 'HC_SYNCREADONLY', label: "Only read HardCover's lists", showIf: (v) => !!v.HC_SYNC },
      {
        key: 'HC_SYNC_LIMIT',
        label: 'Changes a sync makes at most',
        help: 'A safety limit, 0 for none',
        showIf: (v) => !!v.HC_SYNC,
        advanced: true,
      },
    ],
  },
  {
    legend: 'Goodreads Sync',
    help: 'Your reading lists with Goodreads shelves, with a Goodreads key you have',
    advanced: true,
    tests: [{ label: 'Test Goodreads', test: 'GOODREADS' }],
    fields: [
      { key: 'GR_SYNC', label: 'Sync' },
      { key: 'GOODREADS_INTERVAL', label: 'Every' },
      { key: 'GR_SECRET', label: 'Secret', input: 'password' },
      { key: 'GR_OAUTH_TOKEN', label: 'OAuth Token', input: 'password' },
      { key: 'GR_OAUTH_SECRET', label: 'OAuth Secret', input: 'password' },
      { key: 'GR_SYNCREADONLY', label: 'Only read the shelves' },
      { key: 'GR_SYNCUSER', label: 'The shelves are your reading list' },
      { key: 'GR_USER', label: 'Goodreads user ID' },
      { key: 'GR_WANTED', label: 'Wanted eBooks shelf' },
      { key: 'GR_OWNED', label: 'Owned eBooks shelf' },
      { key: 'GR_AWANTED', label: 'Wanted audiobooks shelf' },
      { key: 'GR_AOWNED', label: 'Owned audiobooks shelf' },
      { key: 'GR_UNIQUE', label: 'Take a book off the wanted shelf once owned' },
    ],
  },
  {
    legend: 'Books Added',
    help: "An author's books that are left out when they're looked up",
    fields: [
      { key: 'NO_FUTURE', label: 'Leave out books not out yet' },
      { key: 'NO_PUBDATE', label: 'Leave out books without a release date' },
      { key: 'NO_ISBN', label: 'Leave out books without an ISBN' },
      { key: 'NO_SETS', label: 'Leave out parts and box sets' },
      { key: 'NO_LANG', label: "Leave out books in a language you don't prefer", help: 'See Languages' },
      { key: 'IMP_IGNORE', label: 'Add the books left out, as Ignored' },
      { key: 'NO_SINGLE_BOOK_SERIES', label: 'Leave out series of one book', advanced: true },
      { key: 'NO_NONINTEGER_SERIES', label: 'Leave out books numbered 1.5 in a series', advanced: true },
      { key: 'DELETE_CSV', label: 'Delete a CSV or wishlist once imported', advanced: true },
    ],
  },
  {
    legend: 'Genres',
    fields: [
      { key: 'GENRE_LIMIT', label: 'Genres a book keeps', help: 'The first ones found' },
      {
        key: 'GENRE_USERS',
        label: 'Goodreads readers a genre needs',
        help: 'The readers who shelved the book under it',
        advanced: true,
      },
      { key: 'GENRE_EXCLUDE', label: 'Genres left out', help: 'Separated by commas' },
      { key: 'GENRE_EXCLUDE_PARTS', label: 'Genres with these words left out', help: 'Separated by commas' },
      {
        key: 'GENRE_REPLACE',
        label: 'Genres renamed',
        input: 'textarea',
        placeholder: 'sci-fi = science fiction',
        help: 'One a line: a genre = what it becomes. Renamed before the ones left out are',
      },
      {
        key: 'COMIC_GENRES',
        label: 'Comic genres',
        help: 'eBooks with these genres are searched in the comic categories too',
        showIf: (v) => !!v.COMIC_TAB,
      },
    ],
  },
  {
    legend: 'Metadata Files',
    help: 'Written beside what is imported, for Calibre and readers',
    fields: [
      { key: 'IMP_EBOOKOPF', label: 'An opf file for each book' },
      { key: 'PREF_EBOOKOPF', label: "Prefer an opf file's details", help: "Over the book's own, when it's imported" },
      { key: 'KEEP_OPF', label: "Keep a download's opf file", advanced: true },
      { key: 'KEEP_JPG', label: "Keep a download's cover", advanced: true },
      { key: 'IMP_MAGOPF', label: 'An opf file for each magazine issue', showIf: (v) => !!v.MAG_TAB },
      { key: 'IMP_MAGCOVER', label: 'A cover for each magazine issue', showIf: (v) => !!v.MAG_TAB },
      {
        key: 'MAG_FULLTEXT',
        label: "Index each issue's words for searching",
        help: 'Magazines, Search Issues finds articles in them. The index is kept in fulltext.db, apart from the library',
        showIf: (v) => !!v.MAG_TAB,
      },
      { key: 'IMP_COMICOPF', label: 'An opf file for each comic issue', showIf: (v) => !!v.COMIC_TAB },
      { key: 'IMP_COMICCOVER', label: 'A cover for each comic issue', showIf: (v) => !!v.COMIC_TAB },
      {
        key: 'IMP_CONVERT',
        label: 'Cover program',
        help: 'Makes the issue covers. Empty for ghostscript, or ImageMagick through Wand or PythonMagick',
        advanced: true,
      },
    ],
  },
];

function Metadata() {
  return <SettingsSection title="Metadata" groups={GROUPS} uses={USES} />;
}

export default Metadata;
