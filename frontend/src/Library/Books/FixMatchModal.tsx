// Fix Match, as Plex's Fix Match, Jellyfin's Identify and Audiobookshelf's Match: search an info
// source for the book, its author and title filled in, choose the right one, and what to take from
// it. The book is linked to it there, and takes its details and cover
import { useMutation, useQuery } from '@tanstack/react-query';
import { BookOpen, Search } from 'lucide-react';
import { useState } from 'react';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { api } from 'Utilities/api';
import styles from './FixMatch.module.css';

interface Match {
  source: string;
  id: string;
  title: string;
  subtitle: string;
  author: string;
  date: string;
  publisher: string;
  isbn: string;
  language: string;
  pages: number;
  genres: string;
  description: string;
  cover: string;
  link: string;
}

interface Editing {
  title: string;
  author: string;
  ownSource: string;
  sourceIds: Record<string, string>;
  matchSources: string[];
}

function Cover({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);

  return src && !failed ? (
    <img className={styles.cover} src={src} alt="" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
  ) : (
    <div className={styles.cover}>
      <Icon name={BookOpen} size={24} />
    </div>
  );
}

function FixMatchModal({ bookId, onModalClose }: { bookId: string; onModalClose: () => void }) {
  const book = useQuery({
    queryKey: ['edit', 'book', bookId],
    queryFn: () => api<Editing>(`/library/book/${encodeURIComponent(bookId)}/edit`),
    gcTime: 0,
  });
  const [source, setSource] = useState('');
  const [term, setTerm] = useState<string | null>(null);
  const [asked, setAsked] = useState<{ source: string; term: string } | null>(null);
  const [chosen, setChosen] = useState<Match | null>(null);
  const [takeDetails, setTakeDetails] = useState(true);
  const [takeCover, setTakeCover] = useState(true);

  const sources = book.data?.matchSources ?? [];
  const shownSource = source || sources[0] || '';
  const shownTerm = term ?? (book.data ? `${book.data.author} ${book.data.title}` : '');

  const found = useQuery({
    queryKey: ['edit', 'book', bookId, 'match', asked],
    queryFn: () =>
      api<Match[]>(`/library/book/${encodeURIComponent(bookId)}/match`, {
        query: { source: asked?.source, term: asked?.term },
      }),
    enabled: !!asked,
    gcTime: 0,
    retry: false,
  });

  const apply = useMutation({
    mutationFn: (match: Match) =>
      api<{ message: string }>(`/library/book/${encodeURIComponent(bookId)}/match`, {
        method: 'POST',
        body: { source: match.source, id: match.id, details: takeDetails, cover: takeCover },
      }),
    onSuccess: (result) => {
      showMessage({ id: `match-${bookId}`, text: result.message, kind: 'success', isWorking: false });
      queryClient.invalidateQueries({ queryKey: ['library'] });
      queryClient.invalidateQueries({ queryKey: ['author'] });
      onModalClose();
    },
  });

  function search() {
    setChosen(null);
    setAsked({ source: shownSource, term: shownTerm.trim() });
  }

  const isOwn = !!chosen && chosen.source === book.data?.ownSource;

  return (
    <Modal isOpen={true} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Fix Match{book.data ? ` - ${book.data.title}` : ''}</ModalHeader>
        <ModalBody>
          {book.isLoading ? <LoadingIndicator /> : null}
          {book.data && !sources.length ? (
            <Alert kind="warning">No info source is switched on, see Settings, Metadata.</Alert>
          ) : null}
          {book.data && sources.length ? (
            <form
              className={styles.search}
              onSubmit={(event) => {
                event.preventDefault();
                search();
              }}
            >
              <SelectInput
                className={styles.source}
                value={shownSource}
                values={sources.map((name) => ({
                  key: name,
                  value: book.data.sourceIds[name] ? `${name} (${book.data.sourceIds[name]})` : name,
                }))}
                onChange={setSource}
              />
              <TextInput
                aria-label="Search for"
                value={shownTerm}
                placeholder="Author and title, or an ISBN"
                onChange={setTerm}
              />
              <Button kind="primary" isSpinning={found.isFetching} onPress={search}>
                <Icon name={Search} /> Search
              </Button>
            </form>
          ) : null}

          {found.error ? <Alert kind="danger">{(found.error as Error).message}</Alert> : null}
          {found.data && !found.data.length ? (
            <Alert kind="info">Nothing was found. Try fewer words, the ISBN, or another source.</Alert>
          ) : null}

          {chosen ? (
            <div className={styles.chosen}>
              <div className={styles.match}>
                <Cover src={chosen.cover} />
                <div>
                  <div className={styles.title}>
                    {chosen.title}
                    {chosen.subtitle ? `: ${chosen.subtitle}` : ''}
                  </div>
                  <div className={styles.meta}>
                    {[chosen.author, chosen.date, chosen.publisher, chosen.isbn && `ISBN ${chosen.isbn}`]
                      .filter(Boolean)
                      .join(' · ')}
                  </div>
                  <div className={styles.meta}>
                    <Label>{chosen.source}</Label> {chosen.id}
                  </div>
                </div>
              </div>
              <label className={styles.take}>
                <CheckInput checked={takeDetails} onChange={setTakeDetails} />
                Take its details: title, subtitle, description, date, publisher, ISBN, language, pages, genres
              </label>
              <label className={styles.take}>
                <CheckInput checked={takeCover && !!chosen.cover} onChange={setTakeCover} />
                Take its cover{chosen.cover ? ', kept when the book is refreshed' : ', it has none'}
              </label>
              {isOwn ? (
                <Alert kind="info">
                  The book comes from {chosen.source}, so it stays the book it is there, linked to this one, and is
                  locked: a refresh would put the old match back. Unlock it in Edit to have refreshes again.
                </Alert>
              ) : null}
              {apply.error ? <Alert kind="danger">{(apply.error as Error).message}</Alert> : null}
            </div>
          ) : (
            <ul className={styles.results}>
              {(found.data ?? []).map((match) => (
                <li key={`${match.source}-${match.id}`}>
                  <button type="button" className={styles.result} onClick={() => setChosen(match)}>
                    <Cover src={match.cover} />
                    <span>
                      <span className={styles.title}>
                        {match.title}
                        {match.date ? <span className={styles.year}> ({match.date.slice(0, 4)})</span> : null}
                      </span>
                      <span className={styles.meta}>
                        {[match.author, match.publisher, match.isbn && `ISBN ${match.isbn}`, match.id]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                      {match.id === book.data?.sourceIds[match.source] ? <Label kind="success">Linked now</Label> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </ModalBody>
        <ModalFooter>
          {chosen ? <Button onPress={() => setChosen(null)}>Back to the Results</Button> : null}
          <Button onPress={onModalClose}>Cancel</Button>
          {chosen ? (
            <Button kind="success" isSpinning={apply.isPending} onPress={() => apply.mutate(chosen)}>
              Match
            </Button>
          ) : null}
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default FixMatchModal;
