// Sonarr's series details for an author: who they are, how much of them the library has, their
// books with what's wanted of each as an eBook and an audiobook, and searching for them
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, RefreshCw, Search, SquarePen, Trash2, User } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { runCommand } from 'App/commands';
import { CheckInput, SelectInput } from 'Components/Form/Form';
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
import { BookSearchButtons, Format, FormatCell, FormatInfo, OWNED, shownFormats } from 'Library/BookFormats';
import styles from 'Library/Library.module.css';
import { AuthorBook, AuthorDetail } from 'typings/Author';
import { api } from 'Utilities/api';
import { formatDateTime } from 'Utilities/format';
import { imageUrl } from 'Utilities/images';
import { AUTHOR_STATUSES, setAuthorStatus, setBookStatus } from '../authors';
import DeleteAuthorModal from '../DeleteAuthorModal';

const BOOK_FILTERS = [
  { key: 'shown', value: 'All but ignored' },
  { key: 'all', value: 'All' },
  { key: 'wanted', value: 'Wanted' },
  { key: 'have', value: 'In the library' },
  { key: 'missing', value: 'Not in the library' },
];

// about this many characters show before More
const ABOUT_SHOWN = 400;

function bookMatches(book: AuthorBook, filter: string, formats: Format[]) {
  const statuses = formats.map((format) => (format === 'ebook' ? book.status : book.audioStatus));

  switch (filter) {
    case 'all':
      return true;
    case 'wanted':
      return statuses.some((status) => status === 'Wanted' || status === 'Snatched');
    case 'have':
      return statuses.some((status) => OWNED.includes(status));
    case 'missing':
      return !statuses.some((status) => OWNED.includes(status)) && !statuses.every((status) => status === 'Ignored');
    default:
      return !statuses.every((status) => status === 'Ignored');
  }
}

function BookRow({
  book,
  formats,
  isSelected,
  onSelectedChange,
}: {
  book: AuthorBook;
  formats: FormatInfo[];
  isSelected: boolean;
  onSelectedChange: (isSelected: boolean) => void;
}) {
  return (
    <TableRow className={book.status === 'Ignored' && book.audioStatus === 'Ignored' ? styles.ignored : undefined}>
      <TableRowCell className={styles.select}>
        <CheckInput checked={isSelected} label={`Select ${book.title}`} onChange={onSelectedChange} />
      </TableRowCell>
      <TableRowCell>
        <Link to={`/book/${encodeURIComponent(book.id)}`} className={styles.bookTitle}>
          {book.title}
        </Link>
        {book.subtitle ? <span className={styles.muted}>: {book.subtitle}</span> : null}
        {!book.isPrimary ? <span className={styles.muted}> (with others)</span> : null}
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
      <TableRowCell className={styles.date}>{book.releaseDate}</TableRowCell>
      {formats.map((format) => (
        <FormatCell key={format.format} book={book} format={format} />
      ))}
      <TableRowCell className={styles.actions}>
        <BookSearchButtons book={book} formats={formats} />
      </TableRowCell>
    </TableRow>
  );
}

function AuthorHeader({ author }: { author: AuthorDetail }) {
  const [failed, setFailed] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const src = imageUrl(author.image);
  const lived = [author.born, author.died].filter(Boolean).join(' – ');
  // the sources give About as HTML, shown as its text
  const about = useMemo(
    () => (author.about ? new DOMParser().parseFromString(author.about, 'text/html').body.textContent?.trim() : ''),
    [author.about]
  );

  return (
    <div className={styles.header}>
      <div className={styles.headerImage}>
        {src && !failed ? (
          <img src={src} alt="" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
        ) : (
          <Icon name={User} size={64} />
        )}
      </div>
      <div className={styles.headerInfo}>
        <h1 className={styles.headerName}>{author.name}</h1>
        <div className={styles.headerLabels}>
          <SelectInput
            className={styles.statusSelect}
            value={author.status}
            values={AUTHOR_STATUSES}
            onChange={(status) => setAuthorStatus([author.id], status)}
          />
          {lived ? (
            <Label>
              {lived}
              {author.age ? ` (${author.age})` : ''}
            </Label>
          ) : null}
          {author.aka ? <Label title="Also known as">{author.aka}</Label> : null}
          {author.locked ? <Label kind="warning" title="Its details aren't changed by a refresh">Locked</Label> : null}
          <span title={formatDateTime(author.added)}>
            <Label>Added {author.added}</Label>
          </span>
        </div>
        <div className={styles.headerProgress}>
          <ProgressBar progress={author.percent} kind={author.have >= author.total ? 'success' : 'primary'} />
          <span>
            {author.have} of {author.total} books in the library
          </span>
        </div>
        {author.links.length ? (
          <div className={styles.links}>
            {author.links.map((link) => (
              <Link key={link.source} to={link.url}>
                <Icon name={ExternalLink} size={13} /> {link.source}
              </Link>
            ))}
          </div>
        ) : null}
        {about ? (
          <div className={isAboutOpen ? styles.about : styles.aboutClosed}>
            <p>{about}</p>
            {about.length > ABOUT_SHOWN ? (
              <button type="button" className={styles.more} onClick={() => setIsAboutOpen(!isAboutOpen)}>
                {isAboutOpen ? 'Less' : 'More'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AuthorDetails() {
  const { authorId = '' } = useParams();
  const navigate = useNavigate();
  const formats = shownFormats();
  const [filter, setFilter] = useState('shown');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);

  const author = useQuery({
    queryKey: ['author', 'detail', authorId],
    queryFn: () => api<AuthorDetail>(`/author/${encodeURIComponent(authorId)}`),
    retry: false,
  });
  const books = useQuery({
    queryKey: ['author', 'books', authorId],
    queryFn: () => api<AuthorBook[]>(`/author/${encodeURIComponent(authorId)}/books`),
    enabled: author.isSuccess,
  });

  const shown = useMemo(
    () => (books.data ?? []).filter((book) => bookMatches(book, filter, formats.map((f) => f.format))),
    [books.data, filter, formats]
  );
  const selectedIds = shown.filter((book) => selected.has(book.id)).map((book) => book.id);
  const allSelected = shown.length > 0 && selectedIds.length === shown.length;

  const columns: Column[] = [
    { name: 'title', label: 'Title' },
    { name: 'released', label: 'Released' },
    ...formats.map((f) => ({ name: f.format, label: f.label })),
    { name: 'actions', label: 'Actions', isVisuallyHidden: true },
  ];

  function markSelected(status: string, which: Format[]) {
    setBookStatus(selectedIds, which, status);
    setSelected(new Set());
  }

  const data = author.data;

  return (
    <PageContent title={data?.name ?? 'Author'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Refresh"
            iconName={RefreshCw}
            isSpinning={isRefreshing}
            isDisabled={!data}
            onPress={() => {
              setIsRefreshing(true);
              runCommand('RefreshAuthor', { authorId }, `Refresh ${data?.name}`).finally(() => setIsRefreshing(false));
            }}
          />
          <PageToolbarButton
            label="Search Wanted"
            iconName={Search}
            isSpinning={isSearching}
            isDisabled={!data}
            onPress={() => {
              setIsSearching(true);
              runCommand('AuthorSearch', { authorId }, `Search for ${data?.name}'s wanted books`).finally(() =>
                setIsSearching(false)
              );
            }}
          />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Edit"
            iconName={SquarePen}
            isDisabled={!data}
            to={`/edit_author?authorid=${encodeURIComponent(authorId)}`}
          />
          <PageToolbarButton
            label="Old Page"
            iconName={ExternalLink}
            isDisabled={!data}
            to={`/author_page?authorid=${encodeURIComponent(authorId)}`}
          />
          <PageToolbarButton label="Delete" iconName={Trash2} isDisabled={!data} onPress={() => setIsDeleteOpen(true)} />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <SelectInput
            className={styles.filter}
            value=""
            isDisabled={!selectedIds.length}
            values={[
              { key: '', value: 'Mark selected…' },
              ...formats.map((f) => ({ key: `Wanted:${f.format}`, value: `Want ${f.label}` })),
              ...(formats.length > 1 ? [{ key: 'Wanted:both', value: 'Want both' }] : []),
              { key: 'Skipped:both', value: 'Skip' },
              { key: 'Ignored:both', value: 'Ignore' },
            ]}
            onChange={(value) => {
              if (value) {
                const [status, which] = value.split(':');
                markSelected(status, which === 'both' ? formats.map((f) => f.format) : [which as Format]);
              }
            }}
          />
          <SelectInput className={styles.filter} value={filter} values={BOOK_FILTERS} onChange={setFilter} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {author.isLoading ? <LoadingIndicator /> : null}
        {author.error ? <Alert kind="danger">{(author.error as Error).message}</Alert> : null}
        {data ? <AuthorHeader author={data} /> : null}
        {data && data.status === 'Loading' ? (
          <Alert kind="info">The author is still being added, their books are on their way</Alert>
        ) : null}

        {books.isLoading ? <LoadingIndicator /> : null}
        {books.data && !shown.length ? <Alert kind="info">No book matches the filter</Alert> : null}
        {shown.length ? (
          <Table
            columns={columns}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedIds.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(shown.map((book) => book.id)) : new Set())}
              />
            }
          >
            {shown.map((book) => (
              <BookRow
                key={book.id}
                book={book}
                formats={formats}
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
        ) : null}
        {books.data ? (
          <div className={styles.footer}>
            {shown.length} of {books.data.length} {books.data.length === 1 ? 'book' : 'books'}
          </div>
        ) : null}
      </PageContentBody>

      {data ? (
        <DeleteAuthorModal
          isOpen={isDeleteOpen}
          authors={[data]}
          onModalClose={() => setIsDeleteOpen(false)}
          onDeleted={() => navigate('/authors')}
        />
      ) : null}
    </PageContent>
  );
}

export default AuthorDetails;
