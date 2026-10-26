// Sonarr's QueueStatus: an icon for where a download has got to, and why it's stuck when it is
import { Clock, CloudDownload, Download } from 'lucide-react';
import Icon, { IconKind } from 'Components/Icon';
import { Popover } from 'Components/Misc';
import { TableRowCell } from 'Components/Table/Table';
import { QueueItem } from 'typings/Queue';
import styles from './Queue.module.css';

function QueueStatusCell({ item }: { item: QueueItem }) {
  const { sourceTitle, status, trackedDownloadState, trackedDownloadStatus, statusMessages, errorMessage } = item;
  let iconName = CloudDownload;
  let kind: IconKind = 'default';
  let title = 'Downloading';

  if (status === 'completed') {
    iconName = Download;
    title = 'Downloaded';

    if (trackedDownloadState === 'importBlocked') {
      title += ' - Unable to Import Automatically';
      kind = 'warning';
    } else if (trackedDownloadState === 'importPending') {
      title += ' - Waiting to Import';
      kind = 'purple';
    }
  }

  if (status === 'downloadClientUnavailable') {
    iconName = Clock;
    kind = 'warning';
    title = 'Pending - Download client is unavailable';
  }

  if (status === 'warning') {
    kind = 'warning';
    title = `Download warning: ${errorMessage || 'check the download client for more details'}`;
  }

  if (trackedDownloadStatus === 'error') {
    kind = 'danger';
  }

  const hasMessages = trackedDownloadStatus !== 'ok' && statusMessages.length > 0;
  const body = hasMessages ? (
    <div>
      {statusMessages.map(({ title: messageTitle, messages }) => (
        <div key={messageTitle}>
          {messageTitle}
          <ul>
            {messages.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  ) : (
    sourceTitle
  );

  return (
    <TableRowCell className={styles.status}>
      <Popover anchor={<Icon name={iconName} kind={kind} />} title={title} body={body} />
    </TableRowCell>
  );
}

export default QueueStatusCell;
