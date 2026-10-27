// Readarr's author page lists every book of theirs: this looks the author up at the info sources
// and lists their books, the ones the library hasn't got first, each to add as Add New does
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useState } from 'react';
import AddModal, { Adding } from 'AddNew/AddModal';
import BookResults from 'AddNew/BookResults';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import { Alert, LoadingIndicator } from 'Components/Misc';
import styles from 'Library/Library.module.css';
import { BookLookup, BookMediaType } from 'typings/AddNew';
import { api } from 'Utilities/api';

function mediaTypes(): BookMediaType[] {
  const tabs = window.LazyLibrarian?.tabs ?? { ebook: true, audio: true };
  return [...(tabs.ebook ? ['ebook' as const] : []), ...(tabs.audio ? ['audiobook' as const] : [])];
}

function SourceBooks({ authorId, name }: { authorId: string; name: string }) {
  const [isAsked, setIsAsked] = useState(false);
  const [adding, setAdding] = useState<Adding | null>(null);
  const { data, error, isFetching } = useQuery({
    queryKey: ['author', 'lookup', authorId],
    queryFn: () => api<BookLookup[]>(`/author/${encodeURIComponent(authorId)}/lookup`),
    enabled: isAsked,
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
  const missing = (data ?? []).filter((book) => !book.inLibrary).length;

  return (
    <section className={styles.sourceBooks}>
      <h2 className={styles.legend}>Books at the Info Sources</h2>
      {!isAsked ? (
        <p className={styles.muted}>
          The books above are the ones the library knows. {name} may have written others, or ones the import
          settings left out.{' '}
          <Button onPress={() => setIsAsked(true)}>
            <Icon name={Search} /> Look Up Their Books
          </Button>
        </p>
      ) : null}
      {isFetching && !data ? <LoadingIndicator /> : null}
      {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
      {data ? (
        <>
          <p className={styles.muted}>
            {data.length
              ? `${data.length} found, ${missing} not in the library. A search by name finds the best known ones; Add New finds others by title.`
              : 'The info sources found none of their books.'}
          </p>
          <BookResults lookup={{ authors: [], books: data, mediaTypes: mediaTypes() }} onAdd={setAdding} />
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

export default SourceBooks;
