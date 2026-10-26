// Sonarr's Wanted, Missing: what's wanted and not downloaded, to search for automatically or
// interactively. Searches run as commands, so how each ended shows in the sidebar
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { FolderInput, Search, User } from 'lucide-react';
import { useEffect, useState } from 'react';
import { runCommand } from 'App/commands';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
import IconButton from 'Components/Link/IconButton';
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
import InteractiveImportModal from 'InteractiveImport/InteractiveImportModal';
import { InteractiveSearchModal } from 'InteractiveSearch/InteractiveSearch';
import { MEDIA_TYPE_NAMES } from 'typings/Queue';
import { MissingBook, PagedResult } from 'typings/Wanted';
import { api } from 'Utilities/api';
import { formatDateTime, relativeDate } from 'Utilities/format';
import styles from './Missing.module.css';

const PAGE_SIZE = 20;

const COLUMNS: Column[] = [
  { name: 'title', label: 'Title' },
  { name: 'mediaType', label: 'Type' },
  { name: 'published', label: 'Published' },
  { name: 'added', label: 'Added' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

function searchFor(books: MissingBook[]) {
  const label = books.length === 1 ? `Search for ${books[0].title}` : `Search for ${books.length} books`;

  return runCommand(
    'BookSearch',
    { books: books.map((book) => ({ bookId: book.bookId, mediaType: book.mediaType })) },
    label
  );
}

function MissingRow({
  book,
  isSelected,
  onSelectedChange,
}: {
  book: MissingBook;
  isSelected: boolean;
  onSelectedChange: (isSelected: boolean) => void;
}) {
  const [isSearching, setIsSearching] = useState(false);
  const [isInteractiveOpen, setIsInteractiveOpen] = useState(false);

  return (
    <TableRow>
      <TableRowCell className={styles.select}>
        <CheckInput checked={isSelected} label={`Select ${book.title}`} onChange={onSelectedChange} />
      </TableRowCell>
      <TableRowCell className={styles.title}>
        <Link className={styles.titleLink} to={`/book_detail?bookid=${encodeURIComponent(book.bookId)}`}>
          {book.title}
        </Link>
        <div className={styles.author}>
          {book.authorId ? (
            <Link to={`/author_page?authorid=${encodeURIComponent(book.authorId)}`}>{book.author}</Link>
          ) : (
            book.author
          )}
        </div>
      </TableRowCell>
      <TableRowCell>{MEDIA_TYPE_NAMES[book.mediaType]}</TableRowCell>
      <TableRowCell className={styles.date}>{book.published}</TableRowCell>
      <TableRowCell className={styles.date} title={formatDateTime(book.added)}>
        {relativeDate(book.added)}
      </TableRowCell>
      <TableRowCell className={styles.actions}>
        <IconButton
          name={Search}
          title="Automatic Search"
          isSpinning={isSearching}
          onPress={() => {
            setIsSearching(true);
            searchFor([book]).finally(() => setIsSearching(false));
          }}
        />
        <IconButton name={User} title="Interactive Search" onPress={() => setIsInteractiveOpen(true)} />
      </TableRowCell>
      <InteractiveSearchModal
        isOpen={isInteractiveOpen}
        bookId={book.bookId}
        mediaType={book.mediaType}
        title={book.title}
        onModalClose={() => setIsInteractiveOpen(false)}
      />
    </TableRow>
  );
}

function Missing() {
  const [page, setPage] = useState(1);
  const [mediaType, setMediaType] = useState('');
  const [search, setSearch] = useState('');
  const [term, setTerm] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isSearchingSelected, setIsSearchingSelected] = useState(false);
  const [isSearchingAll, setIsSearchingAll] = useState(false);
  const [isImportOpen, setIsImportOpen] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(term.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [term]);

  const { data, error, isLoading } = useQuery({
    queryKey: ['wanted', 'missing', page, mediaType, search],
    queryFn: () =>
      api<PagedResult<MissingBook>>('/wanted/missing', {
        query: { page, pageSize: PAGE_SIZE, sortKey: 'added', sortDirection: 'descending', mediaType, search },
      }),
    placeholderData: keepPreviousData,
  });

  const records = data?.records ?? [];
  const selectedBooks = records.filter((book) => selected.has(book.id));
  const allSelected = records.length > 0 && selectedBooks.length === records.length;
  const totalPages = data ? Math.max(1, Math.ceil(data.totalRecords / PAGE_SIZE)) : 0;

  return (
    <PageContent title="Missing">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label={selectedBooks.length ? 'Search Selected' : 'Search All'}
            iconName={Search}
            isSpinning={isSearchingSelected || isSearchingAll}
            isDisabled={!records.length}
            onPress={() => {
              if (selectedBooks.length) {
                setIsSearchingSelected(true);
                searchFor(selectedBooks).finally(() => setIsSearchingSelected(false));
                setSelected(new Set());
              } else {
                setIsSearchingAll(true);
                runCommand('MissingBookSearch', {}, 'Search for every wanted book').finally(() =>
                  setIsSearchingAll(false)
                );
              }
            }}
          />
          <PageToolbarSeparator />
          <PageToolbarButton label="Manual Import" iconName={FolderInput} onPress={() => setIsImportOpen(true)} />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <SelectInput
            className={styles.filter}
            value={mediaType}
            values={[
              { key: '', value: 'All' },
              { key: 'ebook', value: 'eBooks' },
              { key: 'audiobook', value: 'Audiobooks' },
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
        {error ? <Alert kind="danger">Failed to load the wanted books: {error.message}</Alert> : null}
        {data && !records.length ? <Alert kind="success">No missing books</Alert> : null}

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
                <MissingRow
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

      <InteractiveImportModal isOpen={isImportOpen} onModalClose={() => setIsImportOpen(false)} />
    </PageContent>
  );
}

export default Missing;
