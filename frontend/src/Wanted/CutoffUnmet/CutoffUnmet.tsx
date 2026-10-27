// Sonarr's Wanted, Cutoff Unmet: books and audiobooks whose file is below their quality profile's
// cutoff, to search for upgrades of. A search only takes a release better than the file there is
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import ItemTitleCell from 'Activity/ItemTitleCell';
import { runCommand } from 'App/commands';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
import IconButton from 'Components/Link/IconButton';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import TablePager from 'Components/Table/TablePager';
import { MEDIA_TYPE_NAMES } from 'typings/Queue';
import { CutoffBook, PagedResult } from 'typings/Wanted';
import { api } from 'Utilities/api';
import { formatDateTime, relativeDate } from 'Utilities/format';
import styles from '../Missing/Missing.module.css';

const PAGE_SIZE = 20;

const COLUMNS: Column[] = [
  { name: 'title', label: 'Title' },
  { name: 'mediaType', label: 'Type' },
  { name: 'quality', label: 'Quality' },
  { name: 'cutoff', label: 'Upgrade Until' },
  { name: 'added', label: 'Imported' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

function searchFor(books: CutoffBook[]) {
  const label = books.length === 1 ? `Search for an upgrade of ${books[0].title}` : `Search for ${books.length} upgrades`;

  return runCommand(
    'CutoffUnmetSearch',
    { books: books.map((book) => ({ bookId: book.bookId, mediaType: book.mediaType })) },
    label
  );
}

function CutoffRow({
  book,
  isSelected,
  onSelectedChange,
}: {
  book: CutoffBook;
  isSelected: boolean;
  onSelectedChange: (isSelected: boolean) => void;
}) {
  const [isSearching, setIsSearching] = useState(false);

  return (
    <TableRow>
      <TableRowCell className={styles.select}>
        <CheckInput checked={isSelected} label={`Select ${book.title}`} onChange={onSelectedChange} />
      </TableRowCell>
      <ItemTitleCell item={{ ...book, issue: '' }} />
      <TableRowCell>{MEDIA_TYPE_NAMES[book.mediaType]}</TableRowCell>
      <TableRowCell>
        <Label kind="warning">{book.quality}</Label>
      </TableRowCell>
      <TableRowCell title={`The ${book.profile} profile`}>
        <Label kind="info">{book.cutoff}</Label>
      </TableRowCell>
      <TableRowCell className={styles.date} title={formatDateTime(book.added)}>
        {relativeDate(book.added)}
      </TableRowCell>
      <TableRowCell className={styles.actions}>
        <IconButton
          name={Search}
          title="Search for an upgrade"
          isSpinning={isSearching}
          onPress={() => {
            setIsSearching(true);
            searchFor([book]).finally(() => setIsSearching(false));
          }}
        />
      </TableRowCell>
    </TableRow>
  );
}

function CutoffUnmet() {
  const [page, setPage] = useState(1);
  const [mediaType, setMediaType] = useState('');
  const [search, setSearch] = useState('');
  const [term, setTerm] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isSearching, setIsSearching] = useState(false);
  const tabs = window.LazyLibrarian?.tabs ?? { ebook: true, audio: true, series: true, mag: true, comic: false };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(term.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [term]);

  const { data, error, isLoading } = useQuery({
    queryKey: ['wanted', 'cutoff', page, mediaType, search],
    queryFn: () =>
      api<PagedResult<CutoffBook>>('/wanted/cutoff', {
        query: { page, pageSize: PAGE_SIZE, sortKey: 'title', sortDirection: 'ascending', mediaType, search },
      }),
    placeholderData: keepPreviousData,
  });

  const records = data?.records ?? [];
  const selectedBooks = records.filter((book) => selected.has(book.id));
  const allSelected = records.length > 0 && selectedBooks.length === records.length;
  const totalPages = data ? Math.max(1, Math.ceil(data.totalRecords / PAGE_SIZE)) : 0;

  return (
    <PageContent title="Cutoff Unmet">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label={selectedBooks.length ? 'Search Selected' : 'Search All'}
            iconName={Search}
            isSpinning={isSearching}
            isDisabled={!records.length}
            onPress={() => {
              setIsSearching(true);
              (selectedBooks.length
                ? searchFor(selectedBooks)
                : runCommand('CutoffUnmetSearch', {}, 'Search for every upgrade')
              ).finally(() => setIsSearching(false));
              setSelected(new Set());
            }}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <SelectInput
            className={styles.filter}
            value={mediaType}
            values={[
              { key: '', value: 'All' },
              ...(tabs.ebook ? [{ key: 'ebook', value: 'eBooks' }] : []),
              ...(tabs.audio ? [{ key: 'audiobook', value: 'Audiobooks' }] : []),
            ]}
            onChange={(value) => {
              setMediaType(value);
              setPage(1);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the upgrades: {error.message}</Alert> : null}
        {data && !records.length ? (
          <Alert kind="success">
            No books are below their cutoff. Upgrades are for profiles that allow them, see{' '}
            <Link to="/settings/profiles">Settings, Profiles</Link>
          </Alert>
        ) : null}

        {records.length ? (
          <>
            <Table
              columns={COLUMNS}
              selectAll={
                <CheckInput
                  checked={allSelected}
                  isIndeterminate={!allSelected && selectedBooks.length > 0}
                  label="Select all"
                  onChange={(checked) => setSelected(checked ? new Set(records.map((book) => book.id)) : new Set())}
                />
              }
            >
              {records.map((book) => (
                <CutoffRow
                  key={book.id}
                  book={book}
                  isSelected={selected.has(book.id)}
                  onSelectedChange={(isSelected) =>
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
      </PageContentBody>
    </PageContent>
  );
}

export default CutoffUnmet;
