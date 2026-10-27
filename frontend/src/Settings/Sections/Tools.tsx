// The programs LazyLibrarian runs, Calibre, and what's converted as it's imported
import { Group } from './fields';
import SettingsSection from './SettingsSection';

const USES = ['MAG_TAB', 'COMIC_TAB'];

const GROUPS: Group[] = [
  {
    legend: 'Programs',
    help: 'Their paths, a name alone when they are on the path',
    tests: [
      { label: 'Test ffmpeg', test: 'FFMPEG' },
      { label: 'Test ebook-convert', test: 'EBOOK_CONVERT' },
      { label: 'Test the preprocessor', test: 'PREPROCESSOR' },
    ],
    fields: [
      { key: 'EBOOK_CONVERT', label: 'ebook-convert', help: "Calibre's, converts eBooks from one format to another" },
      { key: 'FFMPEG', label: 'ffmpeg', help: 'Joins audiobook parts and writes their tags' },
      { key: 'FFMPEG_OUT', label: 'ffmpeg output', help: 'An extension, to make every audiobook one type', advanced: true },
      { key: 'EXT_PREPROCESS', label: 'Preprocessor', help: 'A program of yours run on a download before it is imported' },
      { key: 'CREATE_LINK', label: 'Link program', help: 'Makes a link to a large file instead of copying it', advanced: true },
    ],
  },
  {
    legend: 'Calibre',
    help: 'Import into a Calibre library, with calibredb or through the Calibre content server',
    tests: [{ label: 'Test Calibre', test: 'CALIBREDB' }],
    fields: [
      { key: 'IMP_CALIBREDB', label: 'calibredb', help: 'Its path, empty to not use Calibre' },
      { key: 'CALIBRE_USE_SERVER', label: 'Use the content server' },
      {
        key: 'CALIBRE_SERVER',
        label: 'Server',
        placeholder: 'http://calibre:8080',
        showIf: (v) => !!v.CALIBRE_USE_SERVER,
      },
      { key: 'CALIBRE_USER', label: 'Username', showIf: (v) => !!v.CALIBRE_USE_SERVER },
      { key: 'CALIBRE_PASS', label: 'Password', input: 'password', showIf: (v) => !!v.CALIBRE_USE_SERVER },
      { key: 'IMP_CALIBRE_EBOOK', label: 'Import eBooks into Calibre' },
      { key: 'IMP_CALIBRE_MAGAZINE', label: 'Import magazines into Calibre', showIf: (v) => !!v.MAG_TAB },
      {
        key: 'IMP_CALIBRE_MAGTITLE',
        label: "A magazine's title is its author",
        showIf: (v) => !!v.MAG_TAB && !!v.IMP_CALIBRE_MAGAZINE,
      },
      {
        key: 'IMP_CALIBRE_MAGISSUE',
        label: "An issue's date is its title",
        showIf: (v) => !!v.MAG_TAB && !!v.IMP_CALIBRE_MAGAZINE,
      },
      { key: 'IMP_CALIBRE_COMIC', label: 'Import comics into Calibre', showIf: (v) => !!v.COMIC_TAB },
      { key: 'IMP_CALIBREOVERWRITE', label: "Replace a format Calibre has", advanced: true },
      { key: 'OPF_TAGS', label: 'Tag books in Calibre', help: 'With their genres and wishlists, as chosen below' },
      { key: 'GENRE_TAGS', label: 'Genres as tags', showIf: (v) => !!v.OPF_TAGS },
      { key: 'WISHLIST_TAGS', label: 'Wishlists as tags', showIf: (v) => !!v.OPF_TAGS },
      {
        key: 'IMP_AUTOADD',
        label: 'Auto-add folder',
        help: "A copy of each book is put in Calibre's auto-add folder",
        advanced: true,
      },
      { key: 'IMP_AUTOADD_COPY', label: 'Keep a copy in the library too', advanced: true },
      { key: 'IMP_AUTOADD_BOOKONLY', label: 'Only the book, no opf or cover', advanced: true },
      { key: 'IMP_AUTOADDMAG', label: 'Magazine auto-add folder', showIf: (v) => !!v.MAG_TAB, advanced: true },
      { key: 'IMP_AUTOADDMAG_COPY', label: 'Keep a copy of the issue in the library too', showIf: (v) => !!v.MAG_TAB, advanced: true },
      { key: 'IMP_AUTOADD_MAGONLY', label: 'Only the issue, no opf or cover', showIf: (v) => !!v.MAG_TAB, advanced: true },
    ],
  },
  {
    legend: 'eBook Conversions',
    fields: [
      {
        key: 'EBOOK_WANTED_FORMATS',
        label: 'Formats wanted',
        help: 'Separated by commas. A download in another format is converted with ebook-convert',
      },
      { key: 'DELETE_OTHER_FORMATS', label: "Delete the formats that aren't wanted" },
    ],
  },
  {
    legend: 'Audiobook Conversions',
    fields: [
      { key: 'CREATE_SINGLEAUDIO', label: 'Join the parts into one file' },
      { key: 'KEEP_SEPARATEAUDIO', label: 'Keep the parts too', showIf: (v) => !!v.CREATE_SINGLEAUDIO },
      { key: 'ZIP_AUDIOPARTS', label: 'Zip the parts' },
      { key: 'WRITE_AUDIOTAGS', label: 'Write the tags' },
      { key: 'AUDIO_OPTIONS', label: 'ffmpeg options', advanced: true },
    ],
  },
  {
    legend: 'Magazine Conversions',
    showIf: (v) => !!v.MAG_TAB,
    fields: [
      { key: 'SWAP_COVERPAGE', label: 'Swap the cover page', help: "For issues whose first page isn't the cover" },
      { key: 'SHRINK_MAG', label: 'Shrink to', unit: 'dpi', help: '0 leaves it as it is' },
      { key: 'TAG_PDF', label: 'Tag the pdf' },
    ],
  },
];

function Tools() {
  return <SettingsSection title="Tools" groups={GROUPS} uses={USES} />;
}

export default Tools;
