// Searching inside magazine issues: the pages with the words, best first, each with the words around
// them, opening the issue at that page. The issues' words are read into an index as they're imported
// and scanned, Index Issues reads the ones that aren't yet
import { useQuery } from '@tanstack/react-query';
import { FileSearch, Newspaper, Search } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { runCommand } from 'App/commands';
import FormattedDate from 'Components/FormattedDate';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Cover, plural } from 'Library/library';
import { readerPath } from 'Library/Reader/reading';
import { api } from 'Utilities/api';
import styles from './SearchIssues.module.css';

interface IssuePage {
  issueId: string;
  title: string;
  date: string;
  cover: string;
  page: number;
  snippet: string;
}

// the words searched for are between [ and ] in a snippet
function Snippet({ text }: { text: string }) {
  return (
    <p className={styles.snippet}>
      {text.split(/(\[[^\]]*\])/).map((part, index) =>
        part.startsWith('[') && part.endsWith(']') ? <mark key={index}>{part.slice(1, -1)}</mark> : part
      )}
    </p>
  );
}

function SearchIssues() {
  const [params, setParams] = useSearchParams();
  const asked = params.get('q') ?? '';
  const [typed, setTyped] = useState(asked);
  const [isIndexing, setIsIndexing] = useState(false);

  const { data, error, isFetching } = useQuery({
    queryKey: ['library', 'issuesearch', asked],
    queryFn: () => api<IssuePage[]>('/library/magazine/search', { query: { q: asked } }),
    enabled: !!asked,
    retry: false,
  });

  function look(words: string) {
    setParams(words.trim() ? { q: words.trim() } : {});
  }

  return (
    <PageContent title="Search Issues">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Index Issues"
            iconName={FileSearch}
            isSpinning={isIndexing}
            onPress={() => {
              setIsIndexing(true);
              runCommand('IndexIssues', {}, 'Read the words of the issues').finally(() => setIsIndexing(false));
            }}
          />
        </PageToolbarSection>
      </PageToolbar>
      <PageContentBody>
        <form
          className={styles.searchBar}
          onSubmit={(event) => {
            event.preventDefault();
            look(typed);
          }}
        >
          <Icon name={Search} size={20} />
          <input
            className={styles.searchInput}
            aria-label="Words to look for"
            placeholder='Words in an article, "a phrase", or the start of a word'
            value={typed}
            autoFocus={true}
            onChange={(event) => setTyped(event.target.value)}
          />
          <Button kind="primary" isDisabled={!typed.trim()} isSpinning={isFetching} onPress={() => look(typed)}>
            Search
          </Button>
        </form>

        {!asked ? (
          <p className={styles.help}>
            Finds the pages of PDF and EPUB issues with the words, as they were read into the index when they were
            imported or scanned. Index Issues reads the ones that aren't yet; it can take a while for a big library.
          </p>
        ) : null}
        {isFetching && !data ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        {data && !data.length ? (
          <Alert kind="info">No page has those words. Issues that haven't been indexed can't be searched yet.</Alert>
        ) : null}
        {data?.length ? (
          <>
            <p className={styles.help}>{plural(data.length, 'page')} found, best first</p>
            <ul className={styles.results}>
              {data.map((found) => (
                <li key={`${found.issueId}-${found.page}`}>
                  <Link className={styles.result} to={`${readerPath('issue', found.issueId)}?page=${found.page}`}>
                    <span className={styles.cover}>
                      <Cover src={found.cover} icon={Newspaper} size={24} />
                    </span>
                    <span>
                      <span className={styles.title}>
                        {found.title} <FormattedDate value={found.date} kind="issue" />
                      </span>
                      <span className={styles.page}> · page {found.page}</span>
                      <Snippet text={found.snippet} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </PageContentBody>
    </PageContent>
  );
}

export default SearchIssues;
