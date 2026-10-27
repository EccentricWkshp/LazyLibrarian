// Like Sonarr's Release Profiles: the words that turn a search result down or make it preferred, and
// the sizes each library's downloads have to be
import { Group } from './fields';
import SettingsSection from './SettingsSection';

const USES = ['AUDIO_TAB', 'MAG_TAB', 'COMIC_TAB'];
const WORDS = 'Separated by commas. A result with any of them in its title or file names';

function sizes(legend: string, min: string, max: string, showIf?: Group['showIf']): Group {
  return {
    legend,
    showIf,
    fields: [
      { key: min, label: 'Smallest', unit: 'MB', help: '0 for any' },
      { key: max, label: 'Largest', unit: 'MB', help: '0 for any' },
    ],
  };
}

const GROUPS: Group[] = [
  {
    legend: 'Words',
    fields: [
      { key: 'REJECT_WORDS', label: 'eBooks must not have', help: `${WORDS} is turned down` },
      { key: 'REJECT_AUDIO', label: 'Audiobooks must not have', help: `${WORDS} is turned down`, showIf: (v) => !!v.AUDIO_TAB },
      { key: 'PREFER_WORDS', label: 'Preferred', help: `${WORDS} is preferred` },
      {
        key: 'REJECT_MAGS',
        label: 'Magazines must not have',
        help: `${WORDS} is turned down. Each magazine's own are on the old Settings page`,
        showIf: (v) => !!v.MAG_TAB,
      },
      { key: 'REJECT_COMIC', label: 'Comics must not have', help: 'Separated by commas', showIf: (v) => !!v.COMIC_TAB },
      { key: 'BANNED_EXT', label: 'File types turned down', help: 'Extensions separated by commas, for any library' },
      {
        key: 'REJECT_PUBLISHER',
        label: 'Publishers left out',
        help: "Separated by commas. A library scan doesn't import their books",
        advanced: true,
      },
    ],
  },
  sizes('eBook Size', 'REJECT_MINSIZE', 'REJECT_MAXSIZE'),
  sizes('Audiobook Size', 'REJECT_MINAUDIO', 'REJECT_MAXAUDIO', (v) => !!v.AUDIO_TAB),
  {
    ...sizes('Magazine Size', 'REJECT_MAGMIN', 'REJECT_MAGSIZE', (v) => !!v.MAG_TAB),
    fields: [
      ...sizes('', 'REJECT_MAGMIN', 'REJECT_MAGSIZE').fields,
      { key: 'MAG_AGE', label: 'Oldest issue', unit: 'days', help: 'Older issues are turned down, 0 for any' },
    ],
  },
  sizes('Comic Size', 'REJECT_MINCOMIC', 'REJECT_MAXCOMIC', (v) => !!v.COMIC_TAB),
];

function Filters() {
  return <SettingsSection title="Filters" groups={GROUPS} uses={USES} />;
}

export default Filters;
