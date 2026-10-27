// Sonarr's and Readarr's Add New: look an author or book up at the info sources, a magazine by its
// title and at Wikidata, or a comic at ComicVine and Comixology, and add the one chosen, with what
// to want of it. Each has its own, under Authors, Magazines and Comics
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useState } from 'react';
import { Navigate, useSearchParams } from 'react-router';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { Lookup, ComicLookup, MagazineLookup } from 'typings/AddNew';
import { api } from 'Utilities/api';
import AddModal, { Adding } from './AddModal';
import BookResults from './BookResults';
import { ComicResults, MagazineResults } from './IssueResults';
import styles from './AddNew.module.css';

export type Kind = 'book' | 'magazine' | 'comic';

const KINDS: Record<Kind, { title: string; placeholder: string; help: string }> = {
  book: {
    title: 'Authors & Books',
    placeholder: 'An author, a title or an ISBN',
    help: 'Looked up at the info sources in Settings. Add an author to have all their books, or just a book.',
  },
  magazine: {
    title: 'Magazines',
    placeholder: 'A magazine title, then ~ and words that rule a release out',
    help:
      'Looked up on Wikidata, which gives a magazine its description, publisher and how often it comes out. ' +
      'Words after a ~, separated by commas, rule out releases that have them.',
  },
  comic: {
    title: 'Comics',
    placeholder: 'A comic title, or a ComicVine id starting CV',
    help: 'Looked up at ComicVine, which needs an API key in Settings, and Comixology.',
  },
};

// where each kind's Add New is
export const ADD_NEW: Record<Kind, string> = { book: '/add/new', magazine: '/magazines/add', comic: '/comics/add' };

function lookupPath(kind: Kind) {
  return kind === 'book' ? '/lookup' : `/${kind}/lookup`;
}

function AddNew({ kind = 'book' }: { kind?: Kind }) {
  const [params, setParams] = useSearchParams();
  const asked = params.get('kind') as Kind | null;
  const term = params.get('term') ?? '';
  const [typed, setTyped] = useState(term);
  const [adding, setAdding] = useState<Adding | null>(null);
  const current = KINDS[kind];
  // the old address of a magazine's or comic's Add New
  const moved = kind === 'book' && asked && asked !== 'book' && ADD_NEW[asked] ? ADD_NEW[asked] : '';

  const { data, error, isFetching } = useQuery({
    queryKey: ['lookup', kind, term],
    queryFn: () => api<Lookup | MagazineLookup[] | ComicLookup[]>(lookupPath(kind), { query: { term } }),
    enabled: !!term && !moved,
    staleTime: 10 * 60 * 1000,
    retry: false,
  });

  if (moved) {
    return <Navigate to={`${moved}${term ? `?term=${encodeURIComponent(term)}` : ''}`} replace={true} />;
  }

  function lookUp(nextTerm: string) {
    const next = new URLSearchParams();
    if (nextTerm.trim()) {
      next.set('term', nextTerm.trim());
    }
    setParams(next);
  }

  return (
    <PageContent title={kind === 'book' ? 'Add New' : `Add New - ${current.title}`}>
      <PageContentBody>
        <form
          className={styles.searchBar}
          onSubmit={(event) => {
            event.preventDefault();
            lookUp(typed);
          }}
        >
          <Icon name={Search} size={20} className={styles.searchIcon} />
          <input
            className={styles.searchInput}
            aria-label={`Look up ${current.title}`}
            placeholder={current.placeholder}
            value={typed}
            autoFocus={true}
            onChange={(event) => setTyped(event.target.value)}
          />
          <Button kind="primary" isDisabled={!typed.trim()} isSpinning={isFetching} onPress={() => lookUp(typed)}>
            Look Up
          </Button>
        </form>

        {!term ? <p className={styles.help}>{current.help}</p> : null}
        {isFetching && !data ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}

        {data && term && kind === 'book' ? <BookResults lookup={data as Lookup} onAdd={setAdding} /> : null}
        {data && term && kind === 'magazine' ? (
          <MagazineResults found={data as MagazineLookup[]} onAdd={setAdding} />
        ) : null}
        {data && term && kind === 'comic' ? <ComicResults found={data as ComicLookup[]} onAdd={setAdding} /> : null}
      </PageContentBody>

      <AddModal
        key={adding ? `${adding.kind}-${adding.id}` : 'none'}
        adding={adding}
        mediaTypes={kind === 'book' && data ? (data as Lookup).mediaTypes : []}
        onModalClose={() => setAdding(null)}
      />
    </PageContent>
  );
}

export default AddNew;
