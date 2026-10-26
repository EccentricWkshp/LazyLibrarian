// Sonarr's Activity, Blocklist: the releases that failed, which the searches won't take again.
// Taking one off lets a search take it again, its history stays
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query';
import { RefreshCw, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import ItemTitleCell from 'Activity/ItemTitleCell';
import { ProtocolLabel } from 'Activity/Queue/QueueRow';
import { runCommand } from 'App/commands';
import queryClient from 'App/queryClient';
import { CheckInput, TextInput } from 'Components/Form/Form';
import IconButton from 'Components/Link/IconButton';
import { Alert, LoadingIndicator } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import TablePager from 'Components/Table/TablePager';
import { BlocklistItem } from 'typings/History';
import { MEDIA_TYPE_NAMES } from 'typings/Queue';
import { PagedResult } from 'typings/Wanted';
import { api } from 'Utilities/api';
import { formatDateTime, relativeDate } from 'Utilities/format';
import styles from './Blocklist.module.css';

const PAGE_SIZE = 20;

const COLUMNS: Column[] = [
  { name: 'title', label: 'Title' },
  { name: 'mediaType', label: 'Type' },
  { name: 'sourceTitle', label: 'Release Title' },
  { name: 'protocol', label: 'Protocol' },
  { name: 'indexer', label: 'Indexer' },
  { name: 'message', label: 'Reason' },
  { name: 'date', label: 'Date' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

async function removeFromBlocklist(ids: number[]) {
  try {
    return await api<{ message: string }>('/blocklist/bulk', { method: 'DELETE', body: { ids } });
  } finally {
    queryClient.invalidateQueries({ queryKey: ['blocklist'] });
  }
}

function BlocklistRow({
  item,
  isSelected,
  onSelectedChange,
}: {
  item: BlocklistItem;
  isSelected: boolean;
  onSelectedChange: (isSelected: boolean) => void;
}) {
  const remove = useMutation({ mutationFn: () => removeFromBlocklist([item.id]) });

  return (
    <TableRow>
      <TableRowCell className={styles.select}>
        <CheckInput checked={isSelected} label={`Select ${item.sourceTitle}`} onChange={onSelectedChange} />
      </TableRowCell>
      <ItemTitleCell item={item} />
      <TableRowCell>{MEDIA_TYPE_NAMES[item.mediaType]}</TableRowCell>
      <TableRowCell className={styles.release}>
        <span className={styles.releaseTitle}>{item.sourceTitle}</span>
      </TableRowCell>
      <TableRowCell>{item.protocol ? <ProtocolLabel protocol={item.protocol} /> : null}</TableRowCell>
      <TableRowCell>{item.indexer}</TableRowCell>
      <TableRowCell className={styles.message}>{item.message}</TableRowCell>
      <TableRowCell className={styles.date} title={formatDateTime(item.date)}>
        {relativeDate(item.date)}
      </TableRowCell>
      <TableRowCell className={styles.actions}>
        <IconButton
          name={X}
          title={remove.isError ? remove.error.message : 'Remove from blocklist'}
          isSpinning={remove.isPending}
          onPress={() => remove.mutate()}
        />
      </TableRowCell>
    </TableRow>
  );
}

function Blocklist() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [term, setTerm] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [isRemoveOpen, setIsRemoveOpen] = useState(false);
  const [isClearOpen, setIsClearOpen] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const removeSelected = useMutation({ mutationFn: removeFromBlocklist });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(term.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [term]);

  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['blocklist', page, search],
    queryFn: () =>
      api<PagedResult<BlocklistItem>>('/blocklist', {
        query: { page, pageSize: PAGE_SIZE, sortKey: 'date', sortDirection: 'descending', search },
      }),
    placeholderData: keepPreviousData,
  });

  const records = data?.records ?? [];
  const selectedIds = records.filter((item) => selected.has(item.id)).map((item) => item.id);
  const allSelected = records.length > 0 && selectedIds.length === records.length;
  const totalPages = data ? Math.max(1, Math.ceil(data.totalRecords / PAGE_SIZE)) : 0;

  return (
    <PageContent title="Blocklist">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Refresh" iconName={RefreshCw} isSpinning={isFetching} onPress={() => refetch()} />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Remove Selected"
            iconName={X}
            isDisabled={!selectedIds.length}
            isSpinning={removeSelected.isPending}
            onPress={() => setIsRemoveOpen(true)}
          />
          <PageToolbarButton
            label="Clear"
            iconName={Trash2}
            isDisabled={!records.length}
            isSpinning={isClearing}
            onPress={() => setIsClearOpen(true)}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the blocklist: {error.message}</Alert> : null}
        {removeSelected.isError ? <Alert kind="danger">{removeSelected.error.message}</Alert> : null}
        {data && !records.length ? <Alert kind="info">No releases are blocklisted</Alert> : null}

        {records.length ? (
          <>
            <Table
              columns={COLUMNS}
              selectAll={
                <CheckInput
                  checked={allSelected}
                  isIndeterminate={!allSelected && selectedIds.length > 0}
                  label="Select all"
                  onChange={(checked) => setSelected(checked ? new Set(records.map((item) => item.id)) : new Set())}
                />
              }
            >
              {records.map((item) => (
                <BlocklistRow
                  key={item.id}
                  item={item}
                  isSelected={selected.has(item.id)}
                  onSelectedChange={(isSelected) =>
                    setSelected((current) => {
                      const next = new Set(current);
                      if (isSelected) {
                        next.add(item.id);
                      } else {
                        next.delete(item.id);
                      }
                      return next;
                    })
                  }
                />
              ))}
            </Table>
            <TablePager
              page={page}
              totalPages={totalPages}
              totalRecords={data?.totalRecords ?? 0}
              onPageSelect={(next) => {
                setPage(next);
                setSelected(new Set());
              }}
            />
          </>
        ) : null}
        <p className={styles.note}>
          A release goes on the blocklist when its download fails, so the searches don't take it again while
          Settings has "Blocklist failed downloads" on. Removing it here lets them, and leaves its history.
        </p>
      </PageContentBody>

      <ConfirmModal
        isOpen={isRemoveOpen}
        title="Remove Selected"
        message={`Are you sure you want to remove ${selectedIds.length} selected ${
          selectedIds.length === 1 ? 'release' : 'releases'
        } from the blocklist?`}
        confirmLabel="Remove Selected"
        onConfirm={() => {
          setIsRemoveOpen(false);
          removeSelected.mutate(selectedIds);
          setSelected(new Set());
        }}
        onCancel={() => setIsRemoveOpen(false)}
      />

      <ConfirmModal
        isOpen={isClearOpen}
        title="Clear Blocklist"
        message="Are you sure you want to clear all items from the blocklist?"
        confirmLabel="Clear"
        onConfirm={() => {
          setIsClearOpen(false);
          setIsClearing(true);
          setSelected(new Set());
          runCommand('ClearBlocklist', {}, 'Clearing the blocklist').finally(() => setIsClearing(false));
        }}
        onCancel={() => setIsClearOpen(false)}
      />
    </PageContent>
  );
}

export default Blocklist;
