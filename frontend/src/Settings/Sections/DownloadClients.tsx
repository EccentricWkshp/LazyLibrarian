// Sonarr's Settings, Download Clients: the clients, what's done with a download once it's finished
// or failed, and where a client's folders are here
import { DOWNLOAD_CLIENTS } from 'Settings/Providers/kinds';
import ProviderPage from 'Settings/Providers/ProviderPage';
import RemotePathMappings from 'Settings/Providers/RemotePathMappings';
import { Group } from './fields';

const GROUPS: Group[] = [
  {
    legend: 'Completed Download Handling',
    fields: [
      { key: 'DEL_COMPLETED', label: 'Remove Completed', help: 'Take a download out of the client once it is imported' },
      { key: 'KEEP_SEEDING', label: 'Keep seeding', help: 'A torrent goes on seeding once it is imported' },
      { key: 'SEED_WAIT', label: "Don't remove a torrent still seeding", showIf: (v) => !!v.DEL_COMPLETED },
      { key: 'DEL_FAILED', label: 'Remove Failed', help: 'Take a failed download out of the client, as well as blocking it' },
      { key: 'DEL_DOWNLOADFAILED', label: "Delete a failed download's files", advanced: true },
      { key: 'STALL_AGE', label: 'Give up on a stalled download after', unit: 'hours', help: 'One that never started. 0 waits' },
      { key: 'TASK_AGE', label: 'Forget a failed download after', unit: 'hours', advanced: true },
    ],
  },
  {
    legend: 'Sending',
    fields: [
      { key: 'PREFER_MAGNET', label: 'Send magnet links', help: 'Rather than torrent files, when a result has both' },
      { key: 'TORRENT_PAUSED', label: 'Add torrents paused' },
      { key: 'NZB_PAUSED', label: 'Add nzbs paused' },
    ],
  },
];

function DownloadClients() {
  return (
    <ProviderPage title="Download Clients" heading="Download Clients" kinds={DOWNLOAD_CLIENTS} groups={GROUPS}>
      <RemotePathMappings />
    </ProviderPage>
  );
}

export default DownloadClients;
