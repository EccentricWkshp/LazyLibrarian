// Sonarr's series index for authors: posters or a table, sorted and filtered here, and authors
// selected to set their status or delete them
import { useQuery } from '@tanstack/react-query';
import { LayoutGrid, Plus, Table as TableIcon, Trash2, User } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator, ProgressBar } from 'Components/Misc';
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
import { Author } from 'typings/Author';
import { api } from 'Utilities/api';
import { formatDateTime, relativeDate } from 'Utilities/format';
import { imageUrl } from 'Utilities/images';
import { AUTHOR_STATUSES, setAuthorStatus, statusKind } from '../authors';
import DeleteAuthorModal from '../DeleteAuthorModal';
import styles from '../Author.module.css';

type View = 'posters' | 'table';

const PAGE_SIZES: Record<View, number> = { posters: 60, table: 50 };

const FILTERS = [
  { key: 'shown', value: 'All but ignored' },
  { key: 'all', value: 'All' },
  { key: 'Active', value: 'Active' },
  { key: 'Wanted', value: 'Wanted' },
  { key: 'Paused', value: 'Paused' },
  { key: 'Ignored', value: 'Ignored' },
  { key: 'missing', value: 'Missing books' },
];

const SORTS = [
  { key: 'name', value: 'Name' },
  { key: 'added', value: 'Added' },
  { key: 'lastBook', value: 'Latest book' },
  { key: 'progress', value: 'Books' },
];

const COLUMNS: Column[] = [
  { name: 'status', label: 'Status' },
  { name: 'name', label: 'Author' },
  { name: 'lastBook', label: 'Latest Book' },
  { name: 'added', label: 'Added' },
  { name: 'books', label: 'Books' },
  { name: 'source', label: 'Source' },
];

// the view, sort and filter are kept for next time, in this browser
function remembered<T extends string>(key: string, fallback: T): T {
  try {
    return (window.localStorage.getItem(`authorIndex.${key}`) as T) || fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(`authorIndex.${key}`, value);
  } catch {
    // private windows can't keep it
  }
}

function sortValue(author: Author, sort: string): string | number {
  switch (sort) {
    case 'added':
      return author.added;
    case 'lastBook':
      return author.lastBook?.date ?? '';
    case 'progress':
      return author.percent * 100000 + author.total;
    default:
      return author.sortName.toLowerCase();
  }
}

function matches(author: Author, filter: string, term: string) {
  if (term && !author.name.toLowerCase().includes(term)) {
    return false;
  }

  switch (filter) {
    case 'all':
      return true;
    case 'shown':
      return author.status !== 'Ignored';
    case 'missing':
      return author.status !== 'Ignored' && author.have < author.total;
    default:
      return author.status === filter;
  }
}

function Progress({ author }: { author: Author }) {
  const kind = author.total && author.have >= author.total ? 'success' : author.status === 'Paused' ? 'warning' : 'primary';

  return (
    <div className={styles.progress} title={`${author.have} of ${author.total} books in the library`}>
      <ProgressBar progress={author.percent} kind={kind} />
      <span className={styles.progressText}>
        {author.have} / {author.total}
      </span>
    </div>
  );
}

function Poster({ author }: { author: Author }) {
  const [failed, setFailed] = useState(false);
  const src = imageUrl(author.image);

  return (
    <Link className={styles.poster} to={`/author/${encodeURIComponent(author.id)}`}>
      <div className={styles.posterImage}>
        {src && !failed ? (
          <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
        ) : (
          <Icon name={User} size={48} />
        )}
        {author.status !== 'Active' ? (
          <span className={styles.posterStatus}>
            <Label kind={statusKind(author.status)}>{author.status}</Label>
          </span>
        ) : null}
      </div>
      <Progress author={author} />
      <div className={styles.posterName}>{author.name}</div>
    </Link>
  );
}

function AuthorIndex() {
  const [view, setView] = useState<View>(() => remembered('view', 'posters'));
  const [sort, setSort] = useState<string>(() => remembered('sort', 'name'));
  const [filter, setFilter] = useState<string>(() => remembered('filter', 'shown'));
  const [term, setTerm] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);

  const { data, error, isLoading } = useQuery({
    queryKey: ['author', 'list'],
    queryFn: () => api<Author[]>('/author'),
  });

  const shown = useMemo(() => {
    const wanted = term.trim().toLowerCase();
    const found = (data ?? []).filter((author) => matches(author, filter, wanted));
    const descending = sort !== 'name';

    return found.sort((a, b) => {
      const x = sortValue(a, sort);
      const y = sortValue(b, sort);
      const order = x < y ? -1 : x > y ? 1 : 0;
      return descending ? -order : order;
    });
  }, [data, filter, sort, term]);

  useEffect(() => {
    setPage(1);
  }, [filter, sort, term, view]);

  const pageSize = PAGE_SIZES[view];
  const totalPages = Math.max(1, Math.ceil(shown.length / pageSize));
  const records = shown.slice((page - 1) * pageSize, page * pageSize);
  const selectedAuthors = (data ?? []).filter((author) => selected.has(author.id));
  const allSelected = records.length > 0 && records.every((author) => selected.has(author.id));
  const books = shown.reduce((count, author) => count + author.have, 0);

  function select(id: string, isSelected: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (isSelected) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  }

  return (
    <PageContent title="Authors">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Add New" iconName={Plus} to="/add/new" />
          {view === 'table' ? (
            <>
              <PageToolbarSeparator />
              <SelectInput
                className={styles.filter}
                value=""
                isDisabled={!selectedAuthors.length}
                values={[{ key: '', value: 'Set status…' }, ...AUTHOR_STATUSES]}
                onChange={(status) => {
                  if (status) {
                    setAuthorStatus([...selected], status);
                    setSelected(new Set());
                  }
                }}
              />
              <PageToolbarButton
                label="Delete"
                iconName={Trash2}
                isDisabled={!selectedAuthors.length}
                onPress={() => setIsDeleteOpen(true)}
              />
            </>
          ) : null}
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <PageToolbarButton
            label={view === 'posters' ? 'Table' : 'Posters'}
            iconName={view === 'posters' ? TableIcon : LayoutGrid}
            onPress={() => {
              const next = view === 'posters' ? 'table' : 'posters';
              setView(next);
              remember('view', next);
            }}
          />
          <SelectInput
            className={styles.filter}
            value={sort}
            values={SORTS}
            onChange={(value) => {
              setSort(value);
              remember('sort', value);
            }}
          />
          <SelectInput
            className={styles.filter}
            value={filter}
            values={FILTERS}
            onChange={(value) => {
              setFilter(value);
              remember('filter', value);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the authors: {(error as Error).message}</Alert> : null}
        {data && !data.length ? (
          <Alert kind="info">
            There are no authors yet. <Link to="/add/new">Add New</Link> finds them at the info sources.
          </Alert>
        ) : null}
        {data && data.length && !shown.length ? <Alert kind="info">No author matches the filter</Alert> : null}

        {records.length && view === 'posters' ? (
          <div className={styles.posters}>
            {records.map((author) => (
              <Poster key={author.id} author={author} />
            ))}
          </div>
        ) : null}

        {records.length && view === 'table' ? (
          <Table
            columns={COLUMNS}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && records.some((author) => selected.has(author.id))}
                label="Select all"
                onChange={(checked) =>
                  setSelected(checked ? new Set(records.map((author) => author.id)) : new Set())
                }
              />
            }
          >
            {records.map((author) => (
              <TableRow key={author.id}>
                <TableRowCell className={styles.select}>
                  <CheckInput
                    checked={selected.has(author.id)}
                    label={`Select ${author.name}`}
                    onChange={(isSelected) => select(author.id, isSelected)}
                  />
                </TableRowCell>
                <TableRowCell>
                  <Label kind={statusKind(author.status)}>{author.status}</Label>
                </TableRowCell>
                <TableRowCell>
                  <Link to={`/author/${encodeURIComponent(author.id)}`}>{author.name}</Link>
                </TableRowCell>
                <TableRowCell>
                  {author.lastBook ? (
                    <>
                      {author.lastBook.title}
                      {author.lastBook.date ? <span className={styles.muted}> ({author.lastBook.date})</span> : null}
                    </>
                  ) : null}
                </TableRowCell>
                <TableRowCell className={styles.date} title={formatDateTime(author.added)}>
                  {relativeDate(author.added)}
                </TableRowCell>
                <TableRowCell className={styles.booksCell}>
                  <Progress author={author} />
                </TableRowCell>
                <TableRowCell>{author.source}</TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}

        {shown.length > pageSize ? (
          <TablePager page={page} totalPages={totalPages} totalRecords={shown.length} onPageSelect={setPage} />
        ) : null}
        {shown.length ? (
          <div className={styles.footer}>
            {shown.length} {shown.length === 1 ? 'author' : 'authors'} · {books} {books === 1 ? 'book' : 'books'} in the
            library
          </div>
        ) : null}
      </PageContentBody>

      <DeleteAuthorModal
        isOpen={isDeleteOpen}
        authors={selectedAuthors}
        onModalClose={() => setIsDeleteOpen(false)}
        onDeleted={() => setSelected(new Set())}
      />
    </PageContent>
  );
}

export default AuthorIndex;
