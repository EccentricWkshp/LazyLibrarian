// Sonarr's Activity, Queue: what has been sent to the download clients and not imported yet
import { FolderInput, RefreshCw, X } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { CheckInput } from 'Components/Form/Form';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table } from 'Components/Table/Table';
import InteractiveImportModal from 'InteractiveImport/InteractiveImportModal';
import QueueRow from './QueueRow';
import RemoveQueueItemModal from './RemoveQueueItemModal';
import { useQueue, useRemoveQueueItem } from './useQueue';
import styles from './Queue.module.css';

const COLUMNS: Column[] = [
  { name: 'status', label: 'Status', isVisuallyHidden: true },
  { name: 'title', label: 'Title' },
  { name: 'mediaType', label: 'Type' },
  { name: 'sourceTitle', label: 'Release Title' },
  { name: 'protocol', label: 'Protocol' },
  { name: 'indexer', label: 'Indexer' },
  { name: 'downloadClient', label: 'Download Client' },
  { name: 'size', label: 'Size' },
  { name: 'added', label: 'Added' },
  { name: 'progress', label: 'Progress' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

function Queue() {
  const { data, error, isLoading, isFetching, refetch } = useQueue();
  const removeQueueItems = useRemoveQueueItem();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [lastToggled, setLastToggled] = useState<number | null>(null);
  const [isRemoveModalOpen, setIsRemoveModalOpen] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);

  const items = useMemo(() => data ?? [], [data]);
  // items that have gone from the queue aren't selected any more
  const selectedIds = items.filter((item) => selected.has(item.id)).map((item) => item.id);
  const allSelected = items.length > 0 && selectedIds.length === items.length;

  const handleSelectedChange = useCallback(
    (id: number, isSelected: boolean, shiftKey: boolean) => {
      setSelected((current) => {
        const next = new Set(current);
        const ids = items.map((item) => item.id);
        const from = lastToggled === null ? -1 : ids.indexOf(lastToggled);
        const to = ids.indexOf(id);
        // shift selects everything between this and the last one, as in Sonarr
        const range = shiftKey && from >= 0 ? ids.slice(Math.min(from, to), Math.max(from, to) + 1) : [id];

        range.forEach((rangeId) => (isSelected ? next.add(rangeId) : next.delete(rangeId)));

        return next;
      });
      setLastToggled(id);
    },
    [items, lastToggled]
  );

  return (
    <PageContent title="Queue">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Refresh" iconName={RefreshCw} isSpinning={isFetching} onPress={() => refetch()} />
          <PageToolbarSeparator />
          <PageToolbarButton label="Manual Import" iconName={FolderInput} onPress={() => setIsImportModalOpen(true)} />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Remove Selected"
            iconName={X}
            isDisabled={!selectedIds.length}
            isSpinning={removeQueueItems.isPending}
            onPress={() => setIsRemoveModalOpen(true)}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}

        {error ? <Alert kind="danger">Failed to load the queue: {error.message}</Alert> : null}

        {removeQueueItems.error ? <Alert kind="danger">{removeQueueItems.error.message}</Alert> : null}

        {removeQueueItems.data
          ?.filter((result) => result.message)
          .map((result) => (
            <Alert key={result.message} kind="warning">
              {result.message}
            </Alert>
          ))}

        {!isLoading && !error && !items.length ? <Alert kind="info">Queue is empty</Alert> : null}

        {items.length ? (
          <Table
            columns={COLUMNS}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedIds.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(items.map((item) => item.id)) : new Set())}
              />
            }
          >
            {items.map((item) => (
              <QueueRow
                key={item.id}
                item={item}
                isSelected={selected.has(item.id)}
                onSelectedChange={handleSelectedChange}
              />
            ))}
          </Table>
        ) : null}
        <p className={styles.note}>
          Downloads stay here until they're imported. One that finished but couldn't be imported shows a warning:
          hover over its icon for the reason, and use Manual Import to choose what it is.
        </p>
      </PageContentBody>

      <RemoveQueueItemModal
        isOpen={isRemoveModalOpen}
        selectedCount={selectedIds.length}
        onRemovePress={(options) => {
          setIsRemoveModalOpen(false);
          removeQueueItems.mutate({ ids: selectedIds, options });
          setSelected(new Set());
        }}
        onModalClose={() => setIsRemoveModalOpen(false)}
      />

      <InteractiveImportModal isOpen={isImportModalOpen} onModalClose={() => setIsImportModalOpen(false)} />
    </PageContent>
  );
}

export default Queue;
