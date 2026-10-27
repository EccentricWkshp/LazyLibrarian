// The languages books are wanted in, the language dates are read and shown in, and the words names
// and magazine titles are read with
import { Field, Group } from './fields';
import SettingsSection from './SettingsSection';

const USES = ['MAG_TAB'];
const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

const MONTH_NAMES: Field[] = [
  {
    key: 'MONTH_0',
    label: 'Languages',
    help: "The languages the names below are in, separated by commas. Each month needs a name in each, in the same order",
  },
  ...MONTHS.map((month, index) => ({ key: `MONTH_${index + 1}`, label: month })),
];

const SEASONS: Field[] = MONTHS.map((month, index) => ({
  key: `SEASON_${index + 1}`,
  label: month,
  help: index ? undefined : "Season names an issue can have that mean this month, separated by commas: winter, christmas",
}));

const GROUPS: Group[] = [
  {
    legend: 'Book Languages',
    commands: [
      {
        label: 'Refresh Book Languages',
        command: 'RefreshLanguages',
        help: "Looks again at books whose language is unknown or might be wrong, and stops ignoring the ones in a preferred language. Save a change to the preferred languages first. It's in System, Tasks too",
      },
    ],
    fields: [
      {
        key: 'IMP_PREFLANG',
        label: 'Preferred languages',
        input: 'languages',
        help: "Books in these are wanted, hover a language for its codes. Add Unknown when a source leaves the language out, or All to want any",
      },
      {
        key: 'GB_COUNTRY',
        label: 'GoogleBooks country',
        input: 'select',
        choices: 'countries',
        help: "For books only sold in some countries. It doesn't limit the languages",
        advanced: true,
      },
      { key: 'GOOGLE_TRANS_ID', label: "Tell a book's language from its title with Google Translate", advanced: true },
      {
        key: 'MS_TRANS_ID',
        label: 'Microsoft Azure key',
        input: 'password',
        help: "To tell a book's language from its title with Azure",
        advanced: true,
      },
    ],
  },
  {
    legend: 'Magazine Language',
    showIf: (v) => !!v.MAG_TAB,
    fields: [
      {
        key: 'PREF_MAGLANG',
        label: 'A new magazine is in',
        input: 'select',
        choices: 'magazineLanguages',
        help: "Written into each issue's opf file and pdf, for readers and Calibre. It doesn't filter searches",
      },
    ],
  },
  {
    legend: 'Dates',
    fields: [
      {
        key: 'DATE_LANG',
        label: 'Month names in',
        input: 'select',
        choices: 'dateLanguages',
        help: 'For reading magazine dates, and showing dates with a month name. The date formats are in UI',
      },
    ],
  },
  { legend: 'Month Names', advanced: true, fields: MONTH_NAMES },
  { legend: 'Seasons', advanced: true, showIf: (v) => !!v.MAG_TAB, fields: SEASONS },
  {
    legend: 'Names',
    fields: [
      {
        key: 'NAME_POSTFIX',
        label: 'Name suffixes',
        help: 'Left at the end when an author is sorted by surname, separated by commas: jr, phd',
      },
      { key: 'NAME_DEFINITE', label: 'Articles', help: 'Left out when a title is sorted, separated by commas: the, a' },
      {
        key: 'IMP_NOSPLIT',
        label: "Titles that aren't split",
        help: 'Prefixes, and words in brackets, that a title is not split into a title and subtitle at',
        advanced: true,
      },
      { key: 'MULTI_AUTHOR_SPLIT', label: "Words between authors' names", help: 'and, with', advanced: true },
    ],
  },
  {
    legend: 'Magazine Titles',
    showIf: (v) => !!v.MAG_TAB,
    advanced: true,
    fields: [
      { key: 'ISSUE_NOUNS', label: 'Words for an issue number', help: 'issue, no, #' },
      { key: 'VOLUME_NOUNS', label: 'Words for a volume', help: 'vol, volume' },
      { key: 'MAG_NOUNS', label: 'Words a title can have', help: 'Not taken for a date: winter, special, edition' },
    ],
  },
];

function Languages() {
  return <SettingsSection title="Languages" groups={GROUPS} uses={USES} />;
}

export default Languages;
