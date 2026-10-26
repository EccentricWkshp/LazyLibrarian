import { User, X } from 'lucide-react';
import { useState } from 'react';
import { CheckInput } from 'Components/Form/Form';
import IconButton from 'Components/Link/IconButton';
import Link from 'Components/Link/Link';
import { Label, ProgressBar } from 'Components/Misc';
import { TableRow, TableRowCell } from 'Components/Table/Table';
import InteractiveImportModal from 'InteractiveImport/InteractiveImportModal';
import { MEDIA_TYPE_NAMES, QueueItem } from 'typings/Queue';
import { formatBytes, formatDateTime, relativeDate } from 'Utilities/format';
import QueueStatusCell from './QueueStatusCell';
import RemoveQueueItemModal from './RemoveQueueItemModal';
import { useRemoveQueueItem } from './useQueue';
import styles from './Queue.module.css';

// where each kind of item is in the old pages
function itemLink(item: QueueItem) {
  if (item.mediaType === 'magazine') {
    return `/issue_page?title=${encodeURIComponent(item.bookId)}`;
  }

  if (item.mediaType === 'comic') {
    return `/comicissue_page?comicid=${encodeURIComponent(item.bookId.split('_')[0])}`;
  }

  return `/book_detail?bookid=${encodeURIComponent(item.bookId)}`;
}

export function ProtocolLabel({ protocol }: { protocol: string }) {
  const name = protocol === 'usenet' ? 'nzb' : protocol;

  return <Label kind={protocol === 'torrent' ? 'success' : protocol === 'usenet' ? 'primary' : 'default'}>{name}</Label>;
}

interface QueueRowProps {
  item: QueueItem;
  isSelected: boolean;
  onSelectedChange: (id: number, isSelected: boolean, shiftKey: boolean) => void;
}

function QueueRow({ item, isSelected, onSelectedChange }: QueueRowProps) {
  const [isRemoveModalOpen, setIsRemoveModalOpen] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const removeQueueItem = useRemoveQueueItem();
  const showInteractiveImport = item.status === 'completed' || item.status === 'warning';
  const title = item.issue ? `${item.title} - ${item.issue}` : item.title;

  return (
    <TableRow>
      <TableRowCell className={styles.select}>
        <CheckInput
          checked={isSelected}
          label={`Select ${item.sourceTitle}`}
          onChange={(checked, shiftKey) => onSelectedChange(item.id, checked, shiftKey)}
        />
      </TableRowCell>

      <QueueStatusCell item={item} />

      <TableRowCell className={styles.title}>
        <Link className={styles.titleLink} to={itemLink(item)}>
          {title}
        </Link>
        {item.author ? (
          <div className={styles.author}>
            {item.authorId ? (
              <Link to={`/author_page?authorid=${encodeURIComponent(item.authorId)}`}>{item.author}</Link>
            ) : (
              item.author
            )}
          </div>
        ) : null}
      </TableRowCell>

      <TableRowCell>{MEDIA_TYPE_NAMES[item.mediaType]}</TableRowCell>

      <TableRowCell className={styles.release}>
        <span className={styles.releaseTitle}>{item.sourceTitle}</span>
      </TableRowCell>

      <TableRowCell>
        <ProtocolLabel protocol={item.protocol} />
      </TableRowCell>

      <TableRowCell>{item.indexer}</TableRowCell>

      <TableRowCell>{item.downloadClient}</TableRowCell>

      <TableRowCell className={styles.size}>{formatBytes(item.size)}</TableRowCell>

      <TableRowCell className={styles.added} title={formatDateTime(item.added)}>
        {relativeDate(item.added)}
      </TableRowCell>

      <TableRowCell className={styles.progress}>
        {item.progress ? (
          <ProgressBar
            progress={item.progress}
            kind={item.trackedDownloadStatus === 'warning' ? 'warning' : item.status === 'completed' ? 'success' : 'primary'}
            title={`${item.progress}%`}
          />
        ) : null}
      </TableRowCell>

      <TableRowCell className={styles.actions}>
        {showInteractiveImport ? (
          <IconButton name={User} aria-label="Manual Import" title="Manual Import" onPress={() => setIsImportModalOpen(true)} />
        ) : null}
        <IconButton
          name={X}
          title="Remove from queue"
          isSpinning={removeQueueItem.isPending}
          onPress={() => setIsRemoveModalOpen(true)}
        />
      </TableRowCell>

      <InteractiveImportModal
        isOpen={isImportModalOpen}
        queueItem={item}
        onModalClose={() => setIsImportModalOpen(false)}
      />

      <RemoveQueueItemModal
        isOpen={isRemoveModalOpen}
        sourceTitle={item.sourceTitle}
        onRemovePress={(options) => {
          setIsRemoveModalOpen(false);
          removeQueueItem.mutate({ ids: [item.id], options });
        }}
        onModalClose={() => setIsRemoveModalOpen(false)}
      />
    </TableRow>
  );
}

export default QueueRow;
