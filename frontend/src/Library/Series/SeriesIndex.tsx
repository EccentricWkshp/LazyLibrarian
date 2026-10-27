// The series: by author, how much of each the library has, and whether it's watched for new books
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator, ProgressBar } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import TablePager from 'Components/Table/TablePager';
import { change, remember, remembered } from 'Library/library';
import styles from 'Library/Library.module.css';
import { Series } from 'typings/Library';
import { api } from 'Utilities/api';

const PAGE_SIZE = 50;

export const SERIES_STATUSES = [
  { key: 'Wanted', value: 'Wanted', hint: 'Its books are wanted, and new ones looked for' },
  { key: 'Active', value: 'Active', hint: 'New books in it are looked for' },
  { key: 'Paused', value: 'Paused', hint: "It isn't watched for new books" },
  { key: 'Skipped', value: 'Skipped', hint: "It isn't watched for new books" },
  { key: 'Ignored', value: 'Ignored', hint: "It isn't watched for new books" },
];

const FILTERS = [
  { key: 'All', value: 'All' },
  ...SERIES_STATUSES.map((status) => ({ key: status.key, value: status.value })),
  { key: 'Empty', value: 'None in the library' },
  { key: 'Partial', value: 'Some in the library' },
  { key: 'Complete', value: 'All in the library' },
];

const COLUMNS: Column[] = [
  { name: 'status', label: 'Status' },
  { name: 'name', label: 'Series' },
  { name: 'author', label: 'Author' },
  { name: 'books', label: 'Books' },
  { name: 'source', label: 'Source' },
];

export function seriesKind(status: string) {
  return status === 'Wanted' || status === 'Active' ? 'success' : status === 'Paused' ? 'warning' : 'default';
}

export function setSeriesStatus(ids: string[], status: string) {
  return change(
    '/library/series',
    'PUT',
    { ids, status },
    (changed) => `${changed} series set ${status}`,
    'Setting the status failed'
  );
}

function SeriesIndex() {
  const [filter, setFilter] = useState(() => remembered('series.filter', 'All'));
  const [term, setTerm] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'series', filter],
    queryFn: () => api<Series[]>('/library/series', { query: { status: filter } }),
  });

  const shown = useMemo(() => {
    const wanted = term.trim().toLowerCase();
    return (data ?? []).filter(
      (series) =>
        !wanted || series.name.toLowerCase().includes(wanted) || series.authorName.toLowerCase().includes(wanted)
    );
  }, [data, term]);
  const totalPages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const records = shown.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const selectedIds = records.filter((series) => selected.has(series.id)).map((series) => series.id);
  const allSelected = records.length > 0 && selectedIds.length === records.length;

  return (
    <PageContent title="Series">
      <PageToolbar>
        <PageToolbarSection>
          <SelectInput
            className={styles.filter}
            value=""
            isDisabled={!selectedIds.length}
            values={[{ key: '', value: 'Set status…' }, ...SERIES_STATUSES]}
            onChange={(status) => {
              if (status) {
                setSeriesStatus(selectedIds, status);
                setSelected(new Set());
              }
            }}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <SelectInput
            className={styles.filter}
            value={filter}
            values={FILTERS}
            onChange={(value) => {
              setFilter(value);
              setPage(1);
              remember('series.filter', value);
            }}
          />
          <TextInput
            className={styles.filter}
            value={term}
            placeholder="Filter"
            onChange={(value) => {
              setTerm(value);
              setPage(1);
            }}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the series: {(error as Error).message}</Alert> : null}
        {data && !shown.length ? <Alert kind="info">No series {term || filter !== 'All' ? 'match' : 'yet'}</Alert> : null}

        {records.length ? (
          <Table
            columns={COLUMNS}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedIds.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(records.map((s) => s.id)) : new Set())}
              />
            }
          >
            {records.map((series) => (
              <TableRow key={series.id}>
                <TableRowCell className={styles.select}>
                  <CheckInput
                    checked={selected.has(series.id)}
                    label={`Select ${series.name}`}
                    onChange={(isSelected) =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (isSelected) {
                          next.add(series.id);
                        } else {
                          next.delete(series.id);
                        }
                        return next;
                      })
                    }
                  />
                </TableRowCell>
                <TableRowCell>
                  <Label kind={seriesKind(series.status)}>{series.status}</Label>
                </TableRowCell>
                <TableRowCell>
                  <Link to={`/series/${encodeURIComponent(series.id)}`}>{series.name}</Link>
                </TableRowCell>
                <TableRowCell>
                  <Link to={`/author/${encodeURIComponent(series.authorId)}`}>{series.authorName}</Link>
                </TableRowCell>
                <TableRowCell className={styles.booksCell}>
                  <div className={styles.progress} title={`${series.have} of ${series.total} in the library`}>
                    <ProgressBar progress={series.percent} kind={series.have >= series.total ? 'success' : 'primary'} />
                    <span className={styles.progressText}>
                      {series.have} / {series.total}
                    </span>
                  </div>
                </TableRowCell>
                <TableRowCell>{series.source}</TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}
        {shown.length > PAGE_SIZE ? (
          <TablePager page={page} totalPages={totalPages} totalRecords={shown.length} onPageSelect={setPage} />
        ) : null}
        {shown.length ? <div className={styles.footer}>{shown.length} series</div> : null}
      </PageContentBody>
    </PageContent>
  );
}

export default SeriesIndex;
