// Sonarr's Settings, Media Management: the library folders, how imported files are named, what's
// imported and how, the statuses new books get, file permissions, and how often each task runs
import { Group } from './fields';
import SettingsSection from './SettingsSection';

const BOOK_NAME_HELP =
  '$Author, $SortAuthor, $Title, $SortTitle, $Language, $Series, $SerName, $SerNum, $FmtName, $FmtNum, $PadNum, $PubYear, $SerYear, $Abridged, $$ and any text';
// the libraries switched on, which decide what's shown
const USES = ['EBOOK_TAB', 'AUDIO_TAB', 'MAG_TAB', 'COMIC_TAB'];
const STATUS_OPTIONS = ['Skipped', 'Wanted', 'Have', 'Ignored'].map((status) => ({ key: status, value: status }));

const GROUPS: Group[] = [
  {
    legend: 'Root Folders',
    fields: [
      { key: 'EBOOK_DIR', label: 'eBook library', showIf: (v) => !!v.EBOOK_TAB },
      { key: 'AUDIO_DIR', label: 'Audiobook library', showIf: (v) => !!v.AUDIO_TAB },
      {
        key: 'MAG_DIR',
        label: 'Magazine library',
        help: 'Empty keeps magazines with the eBooks',
        showIf: (v) => !!v.MAG_TAB,
      },
      { key: 'COMIC_DIR', label: 'Comic library', help: 'Empty keeps comics with the eBooks', showIf: (v) => !!v.COMIC_TAB },
      {
        key: 'DOWNLOAD_DIR',
        label: 'Download folders',
        help: 'Where the download clients put finished downloads, separated by commas. Remote path mappings are in Download Clients',
      },
      {
        key: 'ALTERNATE_DIR',
        label: 'Import and export folder',
        help: 'For wishlists, and importing books by hand',
        advanced: true,
      },
    ],
  },
  {
    legend: 'Book Naming',
    fields: [
      { key: 'EBOOK_DEST_FOLDER', label: 'eBook folder', help: BOOK_NAME_HELP },
      { key: 'EBOOK_DEST_FILE', label: 'eBook file', help: BOOK_NAME_HELP },
      { key: 'AUDIOBOOK_DEST_FOLDER', label: 'Audiobook folder', help: BOOK_NAME_HELP },
      { key: 'AUDIOBOOK_DEST_FILE', label: 'Audiobook part file', help: `${BOOK_NAME_HELP}, $Part, $Total. Needs $Title or $SortTitle, and $Part` },
      { key: 'AUDIOBOOK_SINGLE_FILE', label: 'Audiobook single file', help: 'As the part file, without $Part and $Total' },
      {
        key: 'FMT_SERIES',
        label: '$Series is',
        help: '$SerName, $FmtName, $Language, $SerNum, $FmtNum, $PadNum, $PubYear, $SerYear, $$ and any text',
        advanced: true,
      },
      { key: 'FMT_SERNAME', label: '$FmtName is', help: '$SerName, $Language, $PubYear, $SerYear, $$ and any text', advanced: true },
      { key: 'FMT_SERNUM', label: '$FmtNum is', help: '$SerNum, $PadNum, $PubYear, $SerYear, $$ and any text', advanced: true },
    ],
  },
  {
    legend: 'Magazine and Comic Naming',
    showIf: (v) => !!v.MAG_TAB || !!v.COMIC_TAB,
    fields: [
      {
        key: 'MAG_DEST_FOLDER',
        label: 'Magazine folder',
        help: 'Below the magazine library. $Title, $IssueDate, $IssueYear, $IssueVol, $IssueNum, $IssueMonth, $IssueMNum, $IssueDay and any text',
        showIf: (v) => !!v.MAG_TAB,
      },
      {
        key: 'MAG_RELATIVE',
        label: 'Magazines below the eBook library',
        help: 'Off, the magazine folder is a full path',
        showIf: (v) => !!v.MAG_TAB && !v.MAG_DIR,
        advanced: true,
      },
      {
        key: 'MAG_DEST_FILE',
        label: 'Magazine file',
        help: 'Has to have $IssueDate, or $IssueYear and one of $IssueNum, $IssueMonth, $IssueMNum',
        showIf: (v) => !!v.MAG_TAB,
      },
      { key: 'MAG_DELFOLDER', label: "Delete a magazine's folder with its last issue", showIf: (v) => !!v.MAG_TAB, advanced: true },
      {
        key: 'COMIC_DEST_FOLDER',
        label: 'Comic folder',
        help: 'Below the comic library. $Title, $Issue, $Publisher and any text',
        showIf: (v) => !!v.COMIC_TAB,
      },
      {
        key: 'COMIC_RELATIVE',
        label: 'Comics below the eBook library',
        help: 'Off, the comic folder is a full path',
        showIf: (v) => !!v.COMIC_TAB && !v.COMIC_DIR,
        advanced: true,
      },
      { key: 'COMIC_DELFOLDER', label: "Delete a comic's folder with its last issue", showIf: (v) => !!v.COMIC_TAB, advanced: true },
    ],
  },
  {
    legend: 'Importing',
    fields: [
      { key: 'DESTINATION_COPY', label: 'Copy, keeping the downloaded files', help: 'Off moves them into the library' },
      {
        key: 'RECYCLE_BIN',
        label: 'Recycling Bin',
        help: "An audiobook or issue imported where one already is replaces it. The old files go here instead of being deleted",
      },
      { key: 'ONE_FORMAT', label: 'Import one format of an eBook', help: 'When a download has more than one' },
      { key: 'EBOOK_TYPE', label: 'eBook formats', help: 'The extensions imported, best first, separated by commas' },
      { key: 'AUDIOBOOK_TYPE', label: 'Audiobook formats', help: 'Separated by commas' },
      { key: 'MAG_TYPE', label: 'Magazine formats', help: 'Separated by commas', showIf: (v) => !!v.MAG_TAB },
      { key: 'COMIC_TYPE', label: 'Comic formats', help: 'Separated by commas', showIf: (v) => !!v.COMIC_TAB },
      { key: 'IMP_AUTOSEARCH', label: 'Search for what is added' },
      { key: 'IMP_SINGLEBOOK', label: 'One book a folder', help: 'For several formats of a book in one folder', advanced: true },
      { key: 'IMP_RENAME', label: 'Rename books found by a library scan', advanced: true },
      { key: 'MAG_RENAME', label: 'Rename magazines found by a library scan', advanced: true },
      { key: 'FULL_SCAN', label: 'Full library scan', help: 'Forgets books whose files are gone', advanced: true },
      { key: 'ADD_AUTHOR', label: 'Add authors a library scan finds', advanced: true },
      { key: 'ADD_SERIES', label: 'Add series', advanced: true },
    ],
  },
  {
    legend: 'New Books',
    help: 'What new books are, until they are wanted, downloaded or ignored',
    fields: [
      { key: 'NEWBOOK_STATUS', label: 'eBooks of an author you have', input: 'select', options: STATUS_OPTIONS },
      { key: 'NEWAUDIO_STATUS', label: 'Audiobooks of an author you have', input: 'select', options: STATUS_OPTIONS },
      { key: 'NEWAUTHOR_STATUS', label: 'eBooks of a new author', input: 'select', options: STATUS_OPTIONS },
      { key: 'NEWAUTHOR_AUDIO', label: 'Audiobooks of a new author', input: 'select', options: STATUS_OPTIONS },
      {
        key: 'NOTFOUND_STATUS',
        label: 'A book whose file has gone',
        input: 'select',
        options: STATUS_OPTIONS,
      },
      {
        key: 'FOUND_STATUS',
        label: 'A downloaded or found book',
        input: 'select',
        options: [
          { key: 'Open', value: 'Open' },
          { key: 'Have', value: 'Have' },
        ],
        advanced: true,
      },
      {
        key: 'NEWSERIES_STATUS',
        label: 'A new series',
        input: 'select',
        options: ['Active', 'Paused', 'Wanted', 'Ignored'].map((status) => ({ key: status, value: status })),
      },
      {
        key: 'NEWAUTHOR_BOOKS',
        label: "Add a new author's other books",
        help: 'When an author comes in with a wishlist, a scan or an import',
        advanced: true,
      },
      { key: 'CONTRIBUTING_AUTHORS', label: 'Add contributing authors too', advanced: true },
      { key: 'DEL_SECONDARY', label: 'Delete authors who are only contributors', advanced: true },
    ],
  },
  {
    legend: 'Permissions',
    advanced: true,
    fields: [
      { key: 'FILE_PERM', label: 'File permissions', help: '3 or 4 octal digits, like 644' },
      { key: 'DIR_PERM', label: 'Folder permissions', help: 'Like 755' },
    ],
  },
  {
    legend: 'Tasks',
    help: 'How often each runs. 0 stops it, see System, Tasks',
    fields: [
      { key: 'SEARCH_BOOKINTERVAL', label: 'Book search' },
      { key: 'SEARCH_MAGINTERVAL', label: 'Magazine search', showIf: (v) => !!v.MAG_TAB },
      { key: 'SEARCH_COMICINTERVAL', label: 'Comic search', showIf: (v) => !!v.COMIC_TAB },
      { key: 'SEARCHRSS_INTERVAL', label: 'RSS search' },
      { key: 'WISHLIST_INTERVAL', label: 'Wishlist search' },
      { key: 'SCAN_INTERVAL', label: 'Looking for finished downloads' },
      { key: 'PP_DELAY', label: 'Wait after a download finishes', unit: 'seconds', advanced: true },
    ],
  },
];

function MediaManagement() {
  return <SettingsSection title="Media Management" groups={GROUPS} uses={USES} />;
}

export default MediaManagement;
