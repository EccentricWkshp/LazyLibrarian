// Interactive Search for one book, as a page, so the old book pages can open it: every release
// the providers have, why the automatic search would turn each down, and grabbing one anyway
import { useQuery } from '@tanstack/react-query';
import { RefreshCw, Search } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { runCommand } from 'App/commands';
import queryClient from 'App/queryClient';
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
import InteractiveSearch from 'InteractiveSearch/InteractiveSearch';
import { LibraryBook } from 'typings/InteractiveImport';
import { MEDIA_TYPE_NAMES, MediaType } from 'typings/Queue';
import { api } from 'Utilities/api';
import styles from './BookSearch.module.css';

const BOOK_TYPES: MediaType[] = ['ebook', 'audiobook'];

function BookSearch() {
  const [params] = useSearchParams();
  const bookId = params.get('bookId') ?? '';
  const mediaType = (params.get('mediaType') ?? 'ebook') as MediaType;
  const [isSearching, setIsSearching] = useState(false);
  const isValid = !!bookId && BOOK_TYPES.includes(mediaType);
  const { data: book, error } = useQuery({
    queryKey: ['book', bookId],
    queryFn: () => api<LibraryBook>(`/book/${encodeURIComponent(bookId)}`),
    enabled: isValid,
  });
  const name = book ? `${book.title} (${MEDIA_TYPE_NAMES[mediaType]})` : '';

  return (
    <PageContent title={book ? `Interactive Search - ${book.title}` : 'Interactive Search'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Search Again"
            iconName={RefreshCw}
            isDisabled={!book}
            onPress={() => queryClient.refetchQueries({ queryKey: ['release', bookId, mediaType] })}
          />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Automatic Search"
            iconName={Search}
            isDisabled={!book}
            isSpinning={isSearching}
            onPress={() => {
              setIsSearching(true);
              runCommand('BookSearch', { books: [{ bookId, mediaType }] }, `Search for ${book?.title}`).finally(() =>
                setIsSearching(false)
              );
            }}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {!isValid ? (
          <Alert kind="danger">Choose an eBook or audiobook to search for, by its bookId and mediaType</Alert>
        ) : null}
        {error ? <Alert kind="danger">{error.message}</Alert> : null}
        {isValid && !book && !error ? <LoadingIndicator /> : null}

        {book ? (
          <>
            <div className={styles.header}>
              <h1 className={styles.title}>
                <Link to={`/book/${encodeURIComponent(book.id)}`}>{name}</Link>
              </h1>
              <div className={styles.author}>
                {book.authorId ? (
                  <Link to={`/author_page?authorid=${encodeURIComponent(book.authorId)}`}>{book.author}</Link>
                ) : (
                  book.author
                )}
              </div>
            </div>
            <InteractiveSearch bookId={bookId} mediaType={mediaType} />
          </>
        ) : null}
      </PageContentBody>
    </PageContent>
  );
}

export default BookSearch;
