// The old Recent Issues wall: the magazine or comic issues acquired most recently, as covers. A
// cover opens the issue in the reader, its name goes to the magazine or comic
import { useQuery } from '@tanstack/react-query';
import { Layers, Newspaper, RefreshCw } from 'lucide-react';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Cover, RssButton } from 'Library/library';
import styles from 'Library/Library.module.css';
import { canRead, filePath, readerPath } from 'Library/Reader/reading';
import { RecentIssue } from 'typings/Library';
import { api } from 'Utilities/api';

function RecentIssues({ mediaType }: { mediaType: 'magazine' | 'comic' }) {
  const isComic = mediaType === 'comic';
  const kind = isComic ? 'comic' : 'issue';
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['library', 'recent', mediaType],
    queryFn: () => api<RecentIssue[]>('/library/issues/recent', { query: { mediaType } }),
  });

  return (
    <PageContent title="Recent Issues">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Refresh" iconName={RefreshCw} isSpinning={isFetching} onPress={() => refetch()} />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <RssButton type={isComic ? 'Comic' : 'Magazine'} label="RSS Feed" />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        {data && !data.length ? <Alert kind="info">No issues yet.</Alert> : null}
        {data?.length ? (
          <div className={styles.issues}>
            {data.map((issue) => (
              <div key={issue.id} className={styles.issue}>
                <Link
                  className={styles.issueCover}
                  to={canRead(issue.format) ? readerPath(kind, issue.id) : filePath(kind, issue.id, '', true)}
                  noRouter={!canRead(issue.format)}
                  title={canRead(issue.format) ? 'Read' : 'Download'}
                >
                  <Cover src={issue.cover} icon={isComic ? Layers : Newspaper} />
                </Link>
                <div className={styles.issueInfo}>
                  <Link
                    className={styles.issueDate}
                    to={isComic ? `/comic/${encodeURIComponent(issue.parentId)}` : `/magazine?title=${encodeURIComponent(issue.parentId)}`}
                  >
                    {issue.title}
                  </Link>
                  <div className={styles.muted}>
                    {isComic ? `#${issue.issue}` : issue.issue}
                    {issue.acquired ? ` · ${issue.acquired}` : ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </PageContentBody>
    </PageContent>
  );
}

export default RecentIssues;
