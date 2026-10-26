// Sonarr's Activity, History: every download, grabbed, imported or failed, with why one failed
// or where it went, and Mark as Failed for one that was grabbed
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query';
import { CloudDownload, Download, Info, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import ItemTitleCell from 'Activity/ItemTitleCell';
import { ProtocolLabel } from 'Activity/Queue/QueueRow';
import queryClient from 'App/queryClient';
import { SelectInput, TextInput } from 'Components/Form/Form';
import Icon, { IconKind } from 'Components/Icon';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import TablePager from 'Components/Table/TablePager';
import { HistoryEventType, HistoryItem } from 'typings/History';
import { MEDIA_TYPE_NAMES } from 'typings/Queue';
import { PagedResult } from 'typings/Wanted';
import { api } from 'Utilities/api';
import { formatBytes, formatDateTime, relativeDate } from 'Utilities/format';
import styles from './History.module.css';

const PAGE_SIZE = 20;

const COLUMNS: Column[] = [
  { name: 'eventType', label: 'Event', isVisuallyHidden: true },
  { name: 'title', label: 'Title' },
  { name: 'mediaType', label: 'Type' },
  { name: 'sourceTitle', label: 'Release Title' },
  { name: 'protocol', label: 'Protocol' },
  { name: 'indexer', label: 'Indexer' },
  { name: 'downloadClient', label: 'Download Client' },
  { name: 'date', label: 'Date' },
  { name: 'details', label: 'Details', isVisuallyHidden: true },
];

const EVENTS: Record<HistoryEventType, { iconName: typeof Download; kind: IconKind; title: string }> = {
  grabbed: { iconName: CloudDownload, kind: 'default', title: 'Grabbed' },
  downloadFolderImported: { iconName: Download, kind: 'success', title: 'Imported' },
  downloadFailed: { iconName: CloudDownload, kind: 'danger', title: 'Download Failed' },
};

// what Sonarr's HistoryEventTypeCell says each event was
function eventTitle(item: HistoryItem) {
  if (item.eventType === 'grabbed') {
    return `Grabbed from ${item.indexer || 'an indexer'} and sent to ${item.downloadClient || 'the download client'}`;
  }

  if (item.eventType === 'downloadFolderImported') {
    return 'Downloaded and imported';
  }

  return item.eventType === 'downloadFailed' ? 'Download failed' : item.status;
}

async function markAsFailed(id: number) {
  try {
    return await api<{ message: string }>(`/history/failed/${id}`, { method: 'POST' });
  } finally {
    // the modal may be gone by now, so this isn't left to its callbacks
    ['history', 'blocklist', 'queue', 'wanted'].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));
  }
}

function HistoryDetailsModal({ item, isOpen, onModalClose }: { item: HistoryItem; isOpen: boolean; onModalClose: () => void }) {
  const markFailed = useMutation({ mutationFn: () => markAsFailed(item.id) });
  const messageLabel = item.eventType === 'downloadFolderImported' ? 'Imported To' : 'Message';
  const rows: [string, string][] = [
    ['Name', item.sourceTitle],
    ['Indexer', item.indexer],
    ['Download Client', item.downloadClient],
    ['Download ID', item.downloadId],
    ['Size', formatBytes(item.size)],
    ['Date', formatDateTime(item.date)],
    [messageLabel, item.message],
  ];

  return (
    <Modal isOpen={isOpen} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>{EVENTS[item.eventType]?.title ?? item.status}</ModalHeader>
        <ModalBody>
          <dl className={styles.details}>
            {rows
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <div key={label} className={styles.detail}>
                  <dt>{label}</dt>
                  <dd className={label === 'Name' ? styles.releaseTitle : undefined}>{value}</dd>
                </div>
              ))}
          </dl>
          {markFailed.isError ? <Alert kind="danger">{markFailed.error.message}</Alert> : null}
          {markFailed.data ? <Alert kind="success">{markFailed.data.message}</Alert> : null}
        </ModalBody>
        <ModalFooter>
          {item.eventType === 'grabbed' && !markFailed.data ? (
            <Button kind="danger" isSpinning={markFailed.isPending} onPress={() => markFailed.mutate()}>
              Mark as Failed
            </Button>
          ) : null}
          <Button onPress={onModalClose}>Close</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

function HistoryRow({ item }: { item: HistoryItem }) {
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const event = EVENTS[item.eventType];

  return (
    <TableRow>
      <TableRowCell className={styles.event}>
        <Icon name={event?.iconName ?? Info} kind={event?.kind ?? 'default'} title={eventTitle(item)} />
      </TableRowCell>
      <ItemTitleCell item={item} />
      <TableRowCell>{MEDIA_TYPE_NAMES[item.mediaType]}</TableRowCell>
      <TableRowCell className={styles.release}>
        <span className={styles.releaseTitle}>{item.sourceTitle}</span>
        {item.eventType === 'downloadFailed' && item.message ? (
          <div className={styles.failure}>{item.message}</div>
        ) : null}
      </TableRowCell>
      <TableRowCell>{item.protocol ? <ProtocolLabel protocol={item.protocol} /> : null}</TableRowCell>
      <TableRowCell>{item.indexer}</TableRowCell>
      <TableRowCell>{item.downloadClient}</TableRowCell>
      <TableRowCell className={styles.date} title={formatDateTime(item.date)}>
        {relativeDate(item.date)}
      </TableRowCell>
      <TableRowCell className={styles.actions}>
        <IconButton name={Info} title="Details" onPress={() => setIsDetailsOpen(true)} />
      </TableRowCell>
      <HistoryDetailsModal item={item} isOpen={isDetailsOpen} onModalClose={() => setIsDetailsOpen(false)} />
    </TableRow>
  );
}

function History() {
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState('');
  const [search, setSearch] = useState('');
  const [term, setTerm] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(term.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [term]);

  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['history', page, eventType, search],
    queryFn: () =>
      api<PagedResult<HistoryItem>>('/history', {
        query: { page, pageSize: PAGE_SIZE, sortKey: 'date', sortDirection: 'descending', eventType, search },
      }),
    placeholderData: keepPreviousData,
  });

  const records = data?.records ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.totalRecords / PAGE_SIZE)) : 0;

  return (
    <PageContent title="History">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Refresh" iconName={RefreshCw} isSpinning={isFetching} onPress={() => refetch()} />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <SelectInput
            className={styles.filter}
            value={eventType}
            values={[
              { key: '', value: 'All' },
              { key: 'grabbed', value: 'Grabbed' },
              { key: 'downloadFolderImported', value: 'Imported' },
              { key: 'downloadFailed', value: 'Failed' },
            ]}
            onChange={(value) => {
              setEventType(value);
              setPage(1);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the history: {error.message}</Alert> : null}
        {data && !records.length ? <Alert kind="info">No history found</Alert> : null}

        {records.length ? (
          <>
            <Table columns={COLUMNS}>
              {records.map((item) => (
                <HistoryRow key={item.id} item={item} />
              ))}
            </Table>
            <TablePager
              page={page}
              totalPages={totalPages}
              totalRecords={data?.totalRecords ?? 0}
              onPageSelect={setPage}
            />
          </>
        ) : null}
      </PageContentBody>
    </PageContent>
  );
}

export default History;
