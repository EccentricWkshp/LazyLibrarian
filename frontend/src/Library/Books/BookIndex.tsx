// The eBooks or the audiobooks in the library: wanted, snatched or had, or those with a status,
// with what's wanted changed and searched for here, and the library scanned. As Manage, every
// book of either library, by any status or reading list, with all that can be done to them
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Cog, FolderSearch, Plus, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { runCommand } from 'App/commands';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
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
import { BookSearchButtons, FORMATS, Format, FormatStatus, shownFormats } from 'Library/BookFormats';
import { Cover, remember, remembered } from 'Library/library';
import styles from 'Library/Library.module.css';
import { LibraryBook } from 'typings/Library';
import { PagedResult } from 'typings/Wanted';
import { api } from 'Utilities/api';
import { formatDateTime, relativeDate } from 'Utilities/format';

const PAGE_SIZE = 50;

const STATUSES = [
  { key: '', value: 'All listed' },
  { key: 'Wanted', value: 'Wanted' },
  { key: 'Snatched', value: 'Snatched' },
  { key: 'Open', value: 'In the library' },
  { key: 'Have', value: 'Had' },
  { key: 'Skipped', value: 'Skipped' },
  { key: 'Ignored', value: 'Ignored' },
];

const MANAGE_STATUSES = [
  { key: 'All', value: 'All' },
  ...STATUSES.slice(1),
  { key: 'ToRead', value: 'To read' },
  { key: 'Reading', value: 'Reading' },
  { key: 'Read', value: 'Read' },
  { key: 'Abandoned', value: 'Abandoned' },
];

const ACTIONS = [
  { key: 'Wanted', value: 'Want' },
  { key: 'Skipped', value: 'Skip' },
  { key: 'Ignored', value: 'Ignore' },
  { key: 'Have', value: 'Had' },
];

const MANAGE_ACTIONS = [
  ...ACTIONS,
  { key: 'NoDelay', value: 'Search again now' },
  { key: 'ToRead', value: 'To read' },
  { key: 'Reading', value: 'Reading' },
  { key: 'Read', value: 'Read' },
  { key: 'Abandoned', value: 'Abandoned' },
  { key: 'Unread', value: 'Off the reading lists' },
  { key: 'Remove', value: 'Remove (ignore)' },
  { key: 'Delete', value: 'Delete files' },
];

// what asks first
const CONFIRM: Record<string, string> = {
  Remove: 'They are ignored from now on, their files stay where they are.',
  Delete: 'Their files are deleted, and they are ignored from now on.',
};

const SORTS = [
  { key: 'title:ascending', value: 'Title' },
  { key: 'author:ascending', value: 'Author' },
  { key: 'released:descending', value: 'Released' },
  { key: 'added:descending', value: 'Added' },
  { key: 'rating:descending', value: 'Rating' },
];

function columns(manage: boolean): Column[] {
  return [
    { name: 'cover', label: 'Cover', isVisuallyHidden: true },
    { name: 'title', label: 'Title' },
    { name: 'author', label: 'Author' },
    { name: 'released', label: 'Released' },
    { name: 'added', label: 'Added' },
    { name: 'status', label: 'Status' },
    ...(manage
      ? [
          { name: 'reading', label: 'Reading List' },
          { name: 'search', label: 'Searches' },
        ]
      : []),
    { name: 'actions', label: 'Actions', isVisuallyHidden: true },
  ];
}

function markBooks(ids: string[], mediaType: Format, action: string, label: string) {
  const id = `mark-${Date.now()}`;

  return api<{ changed: number; failed: number }>('/library/books/mark', {
    method: 'PUT',
    body: { ids, mediaType, action },
  })
    .then((result) =>
      showMessage({
        id,
        text: `${label}: ${result.changed} changed${result.failed ? `, ${result.failed} not` : ''}`,
        kind: result.failed ? 'warning' : 'success',
        isWorking: false,
      })
    )
    .catch((error) => showMessage({ id, text: `${label} failed: ${error.message}`, kind: 'danger', isWorking: false }))
    .finally(() => {
      queryClient.invalidateQueries({ queryKey: ['library'] });
      queryClient.invalidateQueries({ queryKey: ['author'] });
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
    });
}

function BookIndex({ mediaType: fixedType, manage = false }: { mediaType?: Format; manage?: boolean }) {
  const formats = shownFormats();
  const [chosenType, setChosenType] = useState<Format>(
    () => (remembered('manage.mediaType', formats[0].format) as Format) ?? formats[0].format
  );
  const mediaType = fixedType ?? chosenType;
  const format = FORMATS.find((f) => f.format === mediaType)!;
  const key = manage ? 'manage' : `books.${mediaType}`;
  const title = manage ? 'Manage' : mediaType === 'ebook' ? 'eBooks' : 'Audiobooks';
  const kind = mediaType === 'ebook' ? 'eBooks' : 'audiobooks';
  const [status, setStatus] = useState(() => remembered(`${key}.status`, manage ? 'Wanted' : ''));
  const [sort, setSort] = useState(() => remembered(`${key}.sort`, 'title:ascending'));
  const [term, setTerm] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState('');
  const [confirming, setConfirming] = useState('');
  const [sortKey, sortDirection] = sort.split(':');
  const actions = manage ? MANAGE_ACTIONS : ACTIONS;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(term.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [term]);

  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [mediaType, status, sort]);

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'books', mediaType, status, sort, search, page],
    queryFn: () =>
      api<PagedResult<LibraryBook>>('/library/books', {
        query: { mediaType, status, search, sortKey, sortDirection, page, pageSize: PAGE_SIZE },
      }),
    placeholderData: keepPreviousData,
  });

  const records = data?.records ?? [];
  const selectedIds = records.filter((book) => selected.has(book.id)).map((book) => book.id);
  const allSelected = records.length > 0 && selectedIds.length === records.length;
  const totalPages = data ? Math.max(1, Math.ceil(data.totalRecords / PAGE_SIZE)) : 0;

  function run(runKey: string, name: string, body: Record<string, unknown>, label: string) {
    setRunning(runKey);
    runCommand(name, body, label).finally(() => setRunning(''));
  }

  function act(action: string) {
    const label = actions.find((a) => a.key === action)?.value ?? action;
    markBooks(selectedIds, mediaType, action, label);
    setSelected(new Set());
  }

  return (
    <PageContent title={title}>
      <PageToolbar>
        <PageToolbarSection>
          {/* Manage has more to choose from, the library's own pages have these */}
          {manage ? null : <PageToolbarButton label="Add New" iconName={Plus} to="/add/new" />}
          <PageToolbarButton
            label="Search All"
            iconName={Search}
            isSpinning={running === 'search'}
            onPress={() => run('search', 'RunTask', { task: 'search_book' }, 'Search for wanted books')}
          />
          {manage ? null : (
            <>
              <PageToolbarButton
                label="Library Scan"
                iconName={FolderSearch}
                isSpinning={running === 'scan'}
                onPress={() => run('scan', 'LibraryScan', { mediaType }, `Scan the ${kind} library`)}
              />
              <PageToolbarButton
                label="Post-Process"
                iconName={Cog}
                onPress={() => runCommand('RunTask', { task: 'PostProcessor' }, 'Look for finished downloads')}
              />
            </>
          )}
          <PageToolbarSeparator />
          <SelectInput
            className={styles.filter}
            value=""
            isDisabled={!selectedIds.length}
            values={[{ key: '', value: 'Mark selected…' }, ...actions]}
            onChange={(value) => {
              if (CONFIRM[value]) {
                setConfirming(value);
              } else if (value) {
                act(value);
              }
            }}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          {manage && formats.length > 1 ? (
            <SelectInput
              className={styles.filter}
              value={mediaType}
              values={formats.map((f) => ({ key: f.format, value: `${f.label}s` }))}
              onChange={(value) => {
                setChosenType(value as Format);
                remember('manage.mediaType', value);
              }}
            />
          ) : null}
          <SelectInput
            className={styles.filter}
            value={sort}
            values={SORTS}
            onChange={(value) => {
              setSort(value);
              remember(`${key}.sort`, value);
            }}
          />
          <SelectInput
            className={styles.filter}
            value={status}
            values={manage ? MANAGE_STATUSES : STATUSES}
            onChange={(value) => {
              setStatus(value);
              remember(`${key}.status`, value);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the {kind}: {(error as Error).message}</Alert> : null}
        {data && !records.length ? (
          <Alert kind="info">
            No {kind} {search || status ? 'match' : 'yet'}. <Link to="/add/new">Add New</Link> finds authors and books
            to add.
          </Alert>
        ) : null}

        {records.length ? (
          <>
            <Table
              columns={columns(manage)}
              selectAll={
                <CheckInput
                  checked={allSelected}
                  isIndeterminate={!allSelected && selectedIds.length > 0}
                  label="Select all"
                  onChange={(checked) => setSelected(checked ? new Set(records.map((book) => book.id)) : new Set())}
                />
              }
            >
              {records.map((book) => {
                // the lists' shape, with this library's status
                const statuses = {
                  id: book.id,
                  title: book.title,
                  status: mediaType === 'ebook' ? book.status : '',
                  audioStatus: mediaType === 'audiobook' ? book.status : '',
                  ebookFormat: mediaType === 'ebook' ? book.format : '',
                  audioFormat: mediaType === 'audiobook' ? book.format : '',
                };

                return (
                  <TableRow key={book.id}>
                    <TableRowCell className={styles.select}>
                      <CheckInput
                        checked={selected.has(book.id)}
                        label={`Select ${book.title}`}
                        onChange={(isSelected) =>
                          setSelected((current) => {
                            const next = new Set(current);
                            if (isSelected) {
                              next.add(book.id);
                            } else {
                              next.delete(book.id);
                            }
                            return next;
                          })
                        }
                      />
                    </TableRowCell>
                    <TableRowCell className={styles.coverCell}>
                      <Cover src={book.image} size={20} />
                    </TableRowCell>
                    <TableRowCell>
                      <Link to={`/book/${encodeURIComponent(book.id)}`} className={styles.bookTitle}>
                        {book.title}
                      </Link>
                      {book.subtitle ? <span className={styles.muted}>: {book.subtitle}</span> : null}
                      {book.series.length ? (
                        <div className={styles.series}>
                          {book.series.map((series) => (
                            <Link key={series.id} to={`/series/${encodeURIComponent(series.id)}`}>
                              {series.name}
                              {series.number ? ` #${series.number}` : ''}
                            </Link>
                          ))}
                        </div>
                      ) : null}
                    </TableRowCell>
                    <TableRowCell>
                      <Link to={`/author/${encodeURIComponent(book.authorId)}`}>{book.authorName}</Link>
                    </TableRowCell>
                    <TableRowCell className={styles.date}>{book.releaseDate}</TableRowCell>
                    <TableRowCell className={styles.date} title={formatDateTime(book.added)}>
                      {book.added ? relativeDate(book.added) : ''}
                    </TableRowCell>
                    <TableRowCell className={styles.formatCell}>
                      <FormatStatus book={statuses} format={format} />
                    </TableRowCell>
                    {manage ? (
                      <>
                        <TableRowCell>{book.readingList ? <Label>{book.readingList}</Label> : null}</TableRowCell>
                        <TableRowCell
                          className={styles.date}
                          title={
                            book.search
                              ? `Last looked for ${book.search.last}, next in ${book.search.interval} hours`
                              : undefined
                          }
                        >
                          {book.search ? `${book.search.count} found nothing` : ''}
                        </TableRowCell>
                      </>
                    ) : null}
                    <TableRowCell className={styles.actions}>
                      <BookSearchButtons book={statuses} formats={[format]} />
                    </TableRowCell>
                  </TableRow>
                );
              })}
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
      </PageContentBody>

      <ConfirmModal
        isOpen={!!confirming}
        title={`${actions.find((a) => a.key === confirming)?.value ?? ''}: ${selectedIds.length} ${kind}`}
        message={CONFIRM[confirming] ?? ''}
        confirmLabel={actions.find((a) => a.key === confirming)?.value ?? 'OK'}
        onConfirm={() => {
          act(confirming);
          setConfirming('');
        }}
        onCancel={() => setConfirming('')}
      />
    </PageContent>
  );
}

export default BookIndex;
