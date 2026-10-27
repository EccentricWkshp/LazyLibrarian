// Sonarr's Settings, UI: the libraries shown, how lists sort and show, the dates, the language,
// and the old pages' look
import { Group } from './fields';
import SettingsSection from './SettingsSection';

const GROUPS: Group[] = [
  {
    legend: 'Libraries',
    help: 'The libraries in the menu, each with its pages, searches and settings',
    fields: [
      { key: 'EBOOK_TAB', label: 'eBooks' },
      { key: 'AUDIO_TAB', label: 'Audiobooks' },
      { key: 'SERIES_TAB', label: 'Series' },
      { key: 'MAG_TAB', label: 'Magazines' },
      { key: 'COMIC_TAB', label: 'Comics' },
    ],
  },
  {
    legend: 'Lists',
    fields: [
      { key: 'SORT_SURNAME', label: 'Sort authors by surname' },
      { key: 'SORT_DEFINITE', label: 'Sort titles without The or A' },
      { key: 'IGNORE_PAUSED', label: 'Hide paused authors with the ignored ones', advanced: true },
      { key: 'SHOW_GENRES', label: 'Show genres', advanced: true },
      { key: 'SHOW_REASON', label: 'Show why an author was added', advanced: true },
      { key: 'RATESTARS', label: 'Show ratings as stars', advanced: true },
      { key: 'TOGGLES', label: 'Show column toggles on the old pages', advanced: true },
    ],
  },
  {
    legend: 'Dates',
    fields: [
      {
        key: 'AUTHOR_DATE_FORMAT',
        label: 'Author and book dates',
        input: 'select',
        choices: 'authorDateFormats',
        help: "Born and died, and a book's release",
      },
      {
        key: 'DATE_FORMAT',
        label: 'Added dates',
        input: 'select',
        choices: 'dateFormats',
        help: 'The Added columns, and the history',
      },
      { key: 'ISS_FORMAT', label: 'Issue dates', input: 'select', choices: 'issueDateFormats' },
    ],
  },
  {
    legend: 'Language',
    fields: [{ key: 'UI_LANGUAGE', label: 'Interface language', input: 'select', choices: 'uiLanguages' }],
  },
  {
    legend: 'Old Pages',
    help: 'The pages that are still the old ones',
    fields: [
      {
        key: 'HOMEPAGE',
        label: 'Home page',
        input: 'select',
        options: [
          { key: 'Authors', value: 'Authors' },
          { key: 'eBooks', value: 'eBooks' },
          { key: 'AudioBooks', value: 'Audiobooks' },
          { key: 'Series', value: 'Series' },
          { key: 'Magazines', value: 'Magazines' },
          { key: 'Comics', value: 'Comics' },
        ],
      },
      { key: 'BOOKSTRAP_THEME', label: 'Theme', input: 'select', choices: 'themes', help: 'A dark one makes these pages dark too' },
      { key: 'DISPLAYLENGTH', label: 'Rows a page', advanced: true },
      { key: 'MAX_WALL', label: 'Covers on a cover wall', help: '0 for all', advanced: true },
      { key: 'MAG_SINGLE', label: "Open a magazine's only issue", help: "Instead of its issues' page", advanced: true },
      { key: 'COMIC_SINGLE', label: "Open a comic's only issue", advanced: true },
    ],
  },
];

function UI() {
  return <SettingsSection title="UI" groups={GROUPS} />;
}

export default UI;
