// Sonarr's Settings, Indexers: the usenet and torrent indexers, wishlists, IRC and the sites books
// are downloaded from directly, and how their results are chosen
import { INDEXERS } from 'Settings/Providers/kinds';
import ProviderPage from 'Settings/Providers/ProviderPage';
import { Group } from './fields';

const GROUPS: Group[] = [
  {
    legend: 'Options',
    fields: [
      { key: 'MIN_SEEDERS', label: 'Minimum seeders', help: 'For a torrent result, unless its indexer has its own' },
      { key: 'USENET_RETENTION', label: 'Retention', unit: 'days', help: 'Older usenet results are left out, 0 for any' },
      { key: 'MATCH_RATIO', label: 'Search match', unit: '%', help: 'How well a result has to match to be shown' },
      { key: 'DLOAD_RATIO', label: 'Download match', unit: '%', help: 'How well it has to match to be grabbed' },
      {
        key: 'PRIORITY_WEIGHT',
        label: 'Priority weighting',
        help: "0 picks the best match. Higher makes an indexer's priority count for more",
        advanced: true,
      },
      { key: 'MAX_PAGES', label: 'Result pages', help: 'Searched at each indexer, 0 for all of them', advanced: true },
      { key: 'BLACKLIST_FAILED', label: 'Block failed releases', help: 'See Activity, Blocklist' },
      { key: 'BLACKLIST_PROCESSED', label: 'Skip releases downloaded before' },
      { key: 'DELAYSEARCH', label: 'Search less often for books not found', advanced: true },
    ],
  },
];

function Indexers() {
  return (
    <ProviderPage
      title="Indexers"
      heading="Indexers"
      kinds={INDEXERS}
      groups={GROUPS}
      note="A test that works saves the indexer's settings, as the old settings page did. Newznab and torznab indexers are asked what they can search when they're added or tested, see Show Advanced in their settings."
    />
  );
}

export default Indexers;
