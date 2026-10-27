// Sonarr's and Readarr's Add New: look an author or book up at the info sources, a magazine by its
// title or a comic at ComicVine and Comixology, and add the one chosen, with what to want of it
import { useQuery } from '@tanstack/react-query';
import classNames from 'classnames';
import { Search } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router';
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

type Kind = 'book' | 'magazine' | 'comic';

const KINDS: { kind: Kind; title: string; tab: 'ebook' | 'mag' | 'comic'; placeholder: string; help: string }[] = [
  {
    kind: 'book',
    title: 'Authors & Books',
    tab: 'ebook',
    placeholder: 'An author, a title or an ISBN',
    help: 'Looked up at the info sources in Settings. Add an author to have all their books, or just a book.',
  },
  {
    kind: 'magazine',
    title: 'Magazines',
    tab: 'mag',
    placeholder: 'A magazine title, then ~ and words that rule a release out',
    help: 'A magazine is found by its title. Words after a ~, separated by commas, rule out releases that have them.',
  },
  {
    kind: 'comic',
    title: 'Comics',
    tab: 'comic',
    placeholder: 'A comic title, or a ComicVine id starting CV',
    help: 'Looked up at ComicVine, which needs an API key in Settings, and Comixology.',
  },
];

function shownKinds() {
  const tabs = window.LazyLibrarian?.tabs ?? { ebook: true, audio: true, series: true, mag: true, comic: false };

  // books are for eBooks and audiobooks
  return KINDS.filter((kind) => (kind.tab === 'ebook' ? tabs.ebook || tabs.audio : tabs[kind.tab]));
}

function lookupPath(kind: Kind) {
  return kind === 'book' ? '/lookup' : `/${kind}/lookup`;
}

function AddNew() {
  const kinds = shownKinds();
  const [params, setParams] = useSearchParams();
  const kind = (kinds.find((k) => k.kind === params.get('kind'))?.kind ?? kinds[0]?.kind ?? 'book') as Kind;
  const term = params.get('term') ?? '';
  const [typed, setTyped] = useState(term);
  const [adding, setAdding] = useState<Adding | null>(null);
  const current = KINDS.find((k) => k.kind === kind)!;

  const { data, error, isFetching } = useQuery({
    queryKey: ['lookup', kind, term],
    queryFn: () => api<Lookup | MagazineLookup[] | ComicLookup[]>(lookupPath(kind), { query: { term } }),
    enabled: !!term,
    staleTime: 10 * 60 * 1000,
    retry: false,
  });

  function lookUp(nextKind: Kind, nextTerm: string) {
    const next = new URLSearchParams();
    next.set('kind', nextKind);
    if (nextTerm.trim()) {
      next.set('term', nextTerm.trim());
    }
    setParams(next);
  }

  return (
    <PageContent title="Add New">
      <PageContentBody>
        {kinds.length > 1 ? (
          <div className={styles.kinds} role="tablist">
            {kinds.map((k) => (
              <button
                key={k.kind}
                type="button"
                role="tab"
                aria-selected={k.kind === kind}
                className={classNames(styles.kind, k.kind === kind && styles.selectedKind)}
                onClick={() => {
                  setTyped('');
                  lookUp(k.kind, '');
                }}
              >
                {k.title}
              </button>
            ))}
          </div>
        ) : null}

        <form
          className={styles.searchBar}
          onSubmit={(event) => {
            event.preventDefault();
            lookUp(kind, typed);
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
          <Button kind="primary" isDisabled={!typed.trim()} isSpinning={isFetching} onPress={() => lookUp(kind, typed)}>
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
