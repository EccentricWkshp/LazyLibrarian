// A series: its books in order, with what's wanted of each as an eBook and an audiobook, and
// whether the series is watched for new books
import { useQuery } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { useParams } from 'react-router';
import { setBookStatus } from 'Author/authors';
import { CheckInput, SelectInput } from 'Components/Form/Form';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator, ProgressBar } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { BookSearchButtons, FormatCell, shownFormats } from 'Library/BookFormats';
import { Cover } from 'Library/library';
import styles from 'Library/Library.module.css';
import { SeriesDetail } from 'typings/Library';
import { api } from 'Utilities/api';
import { SERIES_STATUSES, setSeriesStatus } from './SeriesIndex';

function SeriesDetails() {
  const { seriesId = '' } = useParams();
  const formats = shownFormats();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'series', 'detail', seriesId],
    queryFn: () => api<SeriesDetail>(`/library/series/${encodeURIComponent(seriesId)}`),
    retry: false,
  });

  const books = data?.books ?? [];
  const selectedIds = books.filter((book) => selected.has(book.id)).map((book) => book.id);
  const allSelected = books.length > 0 && selectedIds.length === books.length;
  const columns: Column[] = [
    { name: 'number', label: '#' },
    { name: 'cover', label: 'Cover', isVisuallyHidden: true },
    { name: 'title', label: 'Title' },
    { name: 'author', label: 'Author' },
    { name: 'released', label: 'Released' },
    ...formats.map((f) => ({ name: f.format, label: f.label })),
    { name: 'actions', label: 'Actions', isVisuallyHidden: true },
  ];

  return (
    <PageContent title={data?.name ?? 'Series'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Old Page"
            iconName={ExternalLink}
            isDisabled={!data}
            to={`/series_members?seriesid=${encodeURIComponent(seriesId)}`}
          />
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
                setBookStatus(
                  selectedIds,
                  which === 'both' ? formats.map((f) => f.format) : [which],
                  status
                );
                setSelected(new Set());
              }
            }}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        {data ? (
          <div className={styles.header}>
            <div className={styles.headerInfo}>
              <h1 className={styles.headerName}>{data.name}</h1>
              <div className={styles.headerLabels}>
                <SelectInput
                  className={styles.statusSelect}
                  value={data.status}
                  values={SERIES_STATUSES}
                  onChange={(status) => setSeriesStatus([data.id], status)}
                />
                <span>
                  by <Link to={`/author/${encodeURIComponent(data.authorId)}`}>{data.authorName}</Link>
                </span>
              </div>
              <div className={styles.headerProgress}>
                <ProgressBar progress={data.percent} kind={data.have >= data.total ? 'success' : 'primary'} />
                <span>
                  {data.have} of {data.total} in the library
                </span>
              </div>
            </div>
          </div>
        ) : null}

        {books.length ? (
          <Table
            columns={columns}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedIds.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(books.map((b) => b.id)) : new Set())}
              />
            }
          >
            {books.map((book) => (
              <TableRow
                key={book.id}
                className={book.status === 'Ignored' && book.audioStatus === 'Ignored' ? styles.ignored : undefined}
              >
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
                <TableRowCell className={styles.date}>{book.number}</TableRowCell>
                <TableRowCell className={styles.coverCell}>
                  <Cover src={book.image} size={20} />
                </TableRowCell>
                <TableRowCell>
                  <Link to={`/book_detail?bookid=${encodeURIComponent(book.id)}`} className={styles.bookTitle}>
                    {book.title}
                  </Link>
                  {book.subtitle ? <span className={styles.muted}>: {book.subtitle}</span> : null}
                </TableRowCell>
                <TableRowCell>
                  <Link to={`/author/${encodeURIComponent(book.authorId)}`}>{book.authorName}</Link>
                </TableRowCell>
                <TableRowCell className={styles.date}>{book.releaseDate}</TableRowCell>
                {formats.map((format) => (
                  <FormatCell key={format.format} book={book} format={format} />
                ))}
                <TableRowCell className={styles.actions}>
                  <BookSearchButtons book={book} formats={formats} />
                </TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}
        {data && !books.length ? <Alert kind="info">The library has none of its books yet</Alert> : null}
      </PageContentBody>
    </PageContent>
  );
}

export default SeriesDetails;
