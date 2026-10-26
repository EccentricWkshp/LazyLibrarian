// The number of downloads in the queue, beside Queue in the sidebar, like Sonarr's
import { Label } from 'Components/Misc';
import { useQueue } from '../useQueue';

function QueueStatus() {
  const { data } = useQueue();

  if (!data?.length) {
    return null;
  }

  const hasWarning = data.some((item) => item.trackedDownloadStatus === 'warning' || item.status === 'warning');
  const hasError = data.some((item) => item.trackedDownloadStatus === 'error');

  return <Label kind={hasError ? 'danger' : hasWarning ? 'warning' : 'info'}>{data.length}</Label>;
}

export default QueueStatus;
