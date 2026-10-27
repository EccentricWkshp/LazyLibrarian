// The old Past Issues page: search results for magazines' issues that weren't wanted when they were
// found, older issues mostly. Wanting one downloads it, or they can be skipped, ignored or forgotten
import { useQuery } from '@tanstack/react-query';
import { RefreshCw, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import FormattedDate from 'Components/FormattedDate';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { change, plural } from 'Library/library';
import styles from 'Library/Library.module.css';
import { PastIssue } from 'typings/Library';
import { api } from 'Utilities/api';

const STATUSES = ['Skipped', 'Wanted', 'Snatched', 'Have', 'Ignored'].map((status) => ({ key: status, value: status }));
const ACTIONS = [
  { key: '', value: 'Change selected to…' },
  { key: 'Wanted', value: 'Wanted, download it' },
  { key: 'Skipped', value: 'Skipped' },
  { key: 'Ignored', value: 'Ignored' },
  { key: 'Remove', value: 'Forget them' },
];

const COLUMNS: Column[] = [
  { name: 'title', label: 'Magazine' },
  { name: 'issue', label: 'Issue' },
  { name: 'releaseTitle', label: 'Release Title' },
  { name: 'indexer', label: 'Indexer' },
  { name: 'date', label: 'Found' },
];

function PastIssues() {
  const [params, setParams] = useSearchParams();
  const status = params.get('status') ?? 'Skipped';
  const title = params.get('title') ?? '';
  const [term, setTerm] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['library', 'pastissues', status, title],
    queryFn: () => api<PastIssue[]>('/library/magazine/pastissues', { query: { status, title } }),
  });

  const shown = useMemo(() => {
    const words = term.trim().toLowerCase();
    return (data ?? []).filter(
      (issue) => !words || `${issue.title} ${issue.releaseTitle} ${issue.issue}`.toLowerCase().includes(words)
    );
  }, [data, term]);
  const selectedUrls = shown.filter((issue) => selected.has(issue.url)).map((issue) => issue.url);
  const allSelected = shown.length > 0 && selectedUrls.length === shown.length;

  function show(next: Record<string, string>) {
    const query = new URLSearchParams({ status, ...(title ? { title } : {}), ...next });
    if (!query.get('title')) {
      query.delete('title');
    }
    setParams(query);
    setSelected(new Set());
  }

  return (
    <PageContent title={title ? `Past Issues - ${title}` : 'Past Issues'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Refresh" iconName={RefreshCw} isSpinning={isFetching} onPress={() => refetch()} />
          <PageToolbarSeparator />
          <SelectInput
            className={styles.filter}
            value=""
            isDisabled={!selectedUrls.length}
            values={ACTIONS}
            onChange={(action) => {
              if (action) {
                change(
                  '/library/magazine/pastissues',
                  'PUT',
                  { urls: selectedUrls, action },
                  (changed) => `${plural(changed, 'past issue')} ${action === 'Remove' ? 'forgotten' : `set ${action}`}`,
                  'Changing the past issues failed'
                ).then(() => setSelected(new Set()));
              }
            }}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          {title ? (
            <PageToolbarButton label="All Magazines" iconName={X} onPress={() => show({ title: '' })} />
          ) : null}
          <SelectInput className={styles.filter} value={status} values={STATUSES} onChange={(next) => show({ status: next })} />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        {data && !shown.length ? (
          <Alert kind="info">
            No past issues are {status}. A magazine search keeps the issues it found but didn't want here.
          </Alert>
        ) : null}
        {shown.length ? (
          <Table
            columns={COLUMNS}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedUrls.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(shown.map((issue) => issue.url)) : new Set())}
              />
            }
          >
            {shown.map((issue) => (
              <TableRow key={issue.url}>
                <TableRowCell className={styles.select}>
                  <CheckInput
                    checked={selected.has(issue.url)}
                    label={`Select ${issue.releaseTitle}`}
                    onChange={(isSelected) =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (isSelected) {
                          next.add(issue.url);
                        } else {
                          next.delete(issue.url);
                        }
                        return next;
                      })
                    }
                  />
                </TableRowCell>
                <TableRowCell>
                  <Link to={`/magazine?title=${encodeURIComponent(issue.title)}`}>{issue.title}</Link>
                </TableRowCell>
                <TableRowCell className={styles.date}>
                  <FormattedDate value={issue.issue} kind="issue" />
                </TableRowCell>
                <TableRowCell>{issue.releaseTitle}</TableRowCell>
                <TableRowCell>{issue.indexer}</TableRowCell>
                <TableRowCell className={styles.date}>
                  <FormattedDate value={issue.date} />
                </TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}
        {shown.length ? <div className={styles.footer}>{plural(shown.length, 'past issue')}</div> : null}
      </PageContentBody>
    </PageContent>
  );
}

export default PastIssues;
