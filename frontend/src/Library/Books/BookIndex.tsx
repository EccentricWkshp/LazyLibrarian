// The eBooks or the audiobooks in the library: wanted, snatched or had, or those with a status,
// with what's wanted changed and searched for here, and the library scanned
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Cog, FolderSearch, Plus, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { runCommand } from 'App/commands';
import { setBookStatus } from 'Author/authors';
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
import TablePager from 'Components/Table/TablePager';
import { BookSearchButtons, FORMATS, Format, FormatStatus } from 'Library/BookFormats';
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

const SORTS = [
  { key: 'title:ascending', value: 'Title' },
  { key: 'author:ascending', value: 'Author' },
  { key: 'released:descending', value: 'Released' },
  { key: 'added:descending', value: 'Added' },
  { key: 'rating:descending', value: 'Rating' },
];

const COLUMNS: Column[] = [
  { name: 'cover', label: 'Cover', isVisuallyHidden: true },
  { name: 'title', label: 'Title' },
  { name: 'author', label: 'Author' },
  { name: 'released', label: 'Released' },
  { name: 'added', label: 'Added' },
  { name: 'status', label: 'Status' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

function BookIndex({ mediaType }: { mediaType: Format }) {
  const format = FORMATS.find((f) => f.format === mediaType)!;
  const title = mediaType === 'ebook' ? 'eBooks' : 'Audiobooks';
  const [status, setStatus] = useState(() => remembered(`books.${mediaType}.status`, ''));
  const [sort, setSort] = useState(() => remembered(`books.${mediaType}.sort`, 'title:ascending'));
  const [term, setTerm] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState('');
  const [sortKey, sortDirection] = sort.split(':');

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

  function run(key: string, name: string, body: Record<string, unknown>, label: string) {
    setRunning(key);
    runCommand(name, body, label).finally(() => setRunning(''));
  }

  return (
    <PageContent title={title}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Add New" iconName={Plus} to="/add/new" />
          <PageToolbarButton
            label="Search All"
            iconName={Search}
            isSpinning={running === 'search'}
            onPress={() => run('search', 'RunTask', { task: 'search_book' }, 'Search for wanted books')}
          />
          <PageToolbarButton
            label="Library Scan"
            iconName={FolderSearch}
            isSpinning={running === 'scan'}
            onPress={() => run('scan', 'LibraryScan', { mediaType }, `Scan the ${title.toLowerCase()} library`)}
          />
          <PageToolbarButton
            label="Post-Process"
            iconName={Cog}
            onPress={() => runCommand('RunTask', { task: 'PostProcessor' }, 'Look for finished downloads')}
          />
          <PageToolbarSeparator />
          <SelectInput
            className={styles.filter}
            value=""
            isDisabled={!selectedIds.length}
            values={[
              { key: '', value: 'Mark selected…' },
              { key: 'Wanted', value: 'Want' },
              { key: 'Skipped', value: 'Skip' },
              { key: 'Ignored', value: 'Ignore' },
              { key: 'Have', value: 'Had' },
            ]}
            onChange={(value) => {
              if (value) {
                setBookStatus(selectedIds, [mediaType], value);
                setSelected(new Set());
              }
            }}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <SelectInput
            className={styles.filter}
            value={sort}
            values={SORTS}
            onChange={(value) => {
              setSort(value);
              remember(`books.${mediaType}.sort`, value);
            }}
          />
          <SelectInput
            className={styles.filter}
            value={status}
            values={STATUSES}
            onChange={(value) => {
              setStatus(value);
              remember(`books.${mediaType}.status`, value);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the {title.toLowerCase()}: {(error as Error).message}</Alert> : null}
        {data && !records.length ? (
          <Alert kind="info">
            No {title.toLowerCase()} {search || status ? 'match' : 'yet'}. <Link to="/add/new">Add New</Link> finds
            authors and books to add.
          </Alert>
        ) : null}

        {records.length ? (
          <>
            <Table
              columns={COLUMNS}
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
                      <Link to={`/book_detail?bookid=${encodeURIComponent(book.id)}`} className={styles.bookTitle}>
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
    </PageContent>
  );
}

export default BookIndex;
