import { User, X } from 'lucide-react';
import { useState } from 'react';
import ItemTitleCell from 'Activity/ItemTitleCell';
import { CheckInput } from 'Components/Form/Form';
import IconButton from 'Components/Link/IconButton';
import { Label, ProgressBar } from 'Components/Misc';
import { TableRow, TableRowCell } from 'Components/Table/Table';
import InteractiveImportModal from 'InteractiveImport/InteractiveImportModal';
import { MEDIA_TYPE_NAMES, QueueItem } from 'typings/Queue';
import { formatBytes, formatDateTime, relativeDate } from 'Utilities/format';
import QueueStatusCell from './QueueStatusCell';
import RemoveQueueItemModal from './RemoveQueueItemModal';
import { useRemoveQueueItem } from './useQueue';
import styles from './Queue.module.css';

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

      <ItemTitleCell item={item} />

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
