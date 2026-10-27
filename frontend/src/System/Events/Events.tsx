// Sonarr's System, Events: the log LazyLibrarian keeps in memory, the most recent first, at a level
// and above, to clear
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query';
import { Bug, CircleX, Info, RefreshCw, Trash2, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import queryClient from 'App/queryClient';
import { SelectInput, TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
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
import { LogEvent } from 'typings/System';
import { api } from 'Utilities/api';
import { formatDateTime, relativeDate } from 'Utilities/format';
import styles from '../System.module.css';

const PAGE_SIZE = 50;
// the log isn't in the live updates, it changes all the time
const REFRESH = 10000;

const COLUMNS: Column[] = [
  { name: 'level', label: 'Level', isVisuallyHidden: true },
  { name: 'time', label: 'Time' },
  { name: 'component', label: 'Component' },
  { name: 'message', label: 'Message' },
];

const LEVELS: Record<string, { iconName: typeof Info; kind: 'default' | 'primary' | 'warning' | 'danger' }> = {
  DEBUG: { iconName: Bug, kind: 'default' },
  INFO: { iconName: Info, kind: 'primary' },
  WARNING: { iconName: TriangleAlert, kind: 'warning' },
  ERROR: { iconName: CircleX, kind: 'danger' },
  CRITICAL: { iconName: CircleX, kind: 'danger' },
};

interface EventPage {
  page: number;
  pageSize: number;
  totalRecords: number;
  records: LogEvent[];
}

function Events() {
  const [page, setPage] = useState(1);
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [term, setTerm] = useState('');
  const [isClearOpen, setIsClearOpen] = useState(false);
  const clear = useMutation({
    mutationFn: () => api('/log', { method: 'DELETE' }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['log'] }),
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(term.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [term]);

  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['log', page, level, search],
    queryFn: () => api<EventPage>('/log', { query: { page, pageSize: PAGE_SIZE, level, search } }),
    placeholderData: keepPreviousData,
    refetchInterval: REFRESH,
  });
  const records = data?.records ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.totalRecords / PAGE_SIZE)) : 0;

  return (
    <PageContent title="Events">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Refresh" iconName={RefreshCw} isSpinning={isFetching} onPress={() => refetch()} />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Clear"
            iconName={Trash2}
            isSpinning={clear.isPending}
            onPress={() => setIsClearOpen(true)}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <SelectInput
            className={styles.filter}
            value={level}
            values={[
              { key: '', value: 'All' },
              { key: 'info', value: 'Info' },
              { key: 'warn', value: 'Warn' },
              { key: 'error', value: 'Error' },
            ]}
            onChange={(value) => {
              setLevel(value);
              setPage(1);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the events: {(error as Error).message}</Alert> : null}
        {data && !records.length ? <Alert kind="info">No events found</Alert> : null}
        {records.length ? (
          <>
            <Table columns={COLUMNS}>
              {records.map((event, index) => {
                const shown = LEVELS[event.level] ?? LEVELS.INFO;

                return (
                  <TableRow key={`${event.time}-${index}`}>
                    <TableRowCell className={styles.icon}>
                      <Icon name={shown.iconName} kind={shown.kind} title={event.level} />
                    </TableRowCell>
                    <TableRowCell className={styles.nowrap} title={formatDateTime(event.time)}>
                      {relativeDate(event.time)}
                    </TableRowCell>
                    <TableRowCell className={styles.nowrap}>
                      {event.file.replace(/\.py$/, '')}
                      <div className={styles.muted}>{event.thread}</div>
                    </TableRowCell>
                    <TableRowCell className={styles.message}>{event.message}</TableRowCell>
                  </TableRow>
                );
              })}
            </Table>
            <TablePager page={page} totalPages={totalPages} totalRecords={data?.totalRecords ?? 0} onPageSelect={setPage} />
          </>
        ) : null}
      </PageContentBody>

      <ConfirmModal
        isOpen={isClearOpen}
        title="Clear Events"
        message="Clear the events LazyLibrarian keeps in memory? The log files keep them."
        confirmLabel="Clear"
        onConfirm={() => {
          setIsClearOpen(false);
          clear.mutate();
        }}
        onCancel={() => setIsClearOpen(false)}
      />
    </PageContent>
  );
}

export default Events;
