// Readarr's series page has every book in the series: this looks the series up at its info source
// and lists its books in order, the ones the library hasn't got to add as Add New does
import { useQuery } from '@tanstack/react-query';
import { Plus, Search } from 'lucide-react';
import { useState } from 'react';
import AddModal, { Adding } from 'AddNew/AddModal';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { bookKind, OWNED } from 'Library/BookFormats';
import styles from 'Library/Library.module.css';
import { BookMediaType } from 'typings/AddNew';
import { api } from 'Utilities/api';

interface SeriesMember {
  number: string;
  title: string;
  authorName: string;
  authorId: string;
  year: string;
  id: string;
  source: string;
  inLibrary: boolean;
  libraryId: string;
  status: string;
  audioStatus: string;
}

const COLUMNS: Column[] = [
  { name: 'number', label: '#' },
  { name: 'title', label: 'Title' },
  { name: 'author', label: 'Author' },
  { name: 'year', label: 'Published' },
  { name: 'library', label: 'Library' },
];

function mediaTypes(): BookMediaType[] {
  const tabs = window.LazyLibrarian?.tabs ?? { ebook: true, audio: true };
  return [...(tabs.ebook ? ['ebook' as const] : []), ...(tabs.audio ? ['audiobook' as const] : [])];
}

// what the library has of a book: a file, wanted, or only known
function libraryLabel(book: SeriesMember) {
  const statuses = [book.status, book.audioStatus];
  const status = statuses.find((s) => OWNED.includes(s)) ?? statuses.find((s) => s === 'Wanted') ?? book.status;
  return <Label kind={bookKind(status)}>{status || 'In the library'}</Label>;
}

function SeriesSourceBooks({ seriesId, name }: { seriesId: string; name: string }) {
  const [isAsked, setIsAsked] = useState(false);
  const [adding, setAdding] = useState<Adding | null>(null);
  const { data, error, isFetching } = useQuery({
    queryKey: ['library', 'series', seriesId, 'lookup'],
    queryFn: () => api<SeriesMember[]>(`/library/series/${encodeURIComponent(seriesId)}/lookup`),
    enabled: isAsked,
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
  const missing = (data ?? []).filter((book) => !book.inLibrary).length;

  return (
    <section className={styles.sourceBooks}>
      <h2 className={styles.legend}>Books at the Info Source</h2>
      {!isAsked ? (
        <p className={styles.muted}>
          The books above are the ones of {name} the library knows. Its info source may list more.{' '}
          <Button onPress={() => setIsAsked(true)}>
            <Icon name={Search} /> Look Up the Series
          </Button>
        </p>
      ) : null}
      {isFetching && !data ? <LoadingIndicator /> : null}
      {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
      {data ? (
        <>
          <p className={styles.muted}>
            {data.length
              ? `${data.length} in the series, ${missing} not in the library.`
              : "Its info source didn't list its books."}
          </p>
          {data.length ? (
            <Table columns={COLUMNS}>
              {data.map((book) => (
                <TableRow key={`${book.number}-${book.id || book.title}`}>
                  <TableRowCell className={styles.date}>{book.number}</TableRowCell>
                  <TableRowCell>
                    {book.inLibrary ? (
                      <Link to={`/book/${encodeURIComponent(book.libraryId)}`} className={styles.bookTitle}>
                        {book.title}
                      </Link>
                    ) : (
                      book.title
                    )}
                  </TableRowCell>
                  <TableRowCell>{book.authorName}</TableRowCell>
                  <TableRowCell className={styles.date}>{book.year}</TableRowCell>
                  <TableRowCell>
                    {book.inLibrary ? (
                      libraryLabel(book)
                    ) : book.id ? (
                      <Button
                        aria-label={`Add ${book.title}`}
                        onPress={() =>
                          setAdding({ kind: 'book', id: book.id, name: book.title, source: book.source, authorId: book.authorId })
                        }
                      >
                        <Icon name={Plus} /> Add
                      </Button>
                    ) : (
                      <span className={styles.muted} title="Its info source gave no id to add it by, Add New finds it by title">
                        No id
                      </span>
                    )}
                  </TableRowCell>
                </TableRow>
              ))}
            </Table>
          ) : null}
        </>
      ) : null}
      <AddModal
        key={adding ? `${adding.kind}-${adding.id}` : 'none'}
        adding={adding}
        mediaTypes={mediaTypes()}
        onModalClose={() => setAdding(null)}
      />
    </section>
  );
}

export default SeriesSourceBooks;
