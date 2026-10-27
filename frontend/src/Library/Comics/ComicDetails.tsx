// Sonarr's series details for a comic: its cover, publisher and status, and its issues, each to
// open or delete, with the comic searched for or its folder scanned
import { useQuery } from '@tanstack/react-query';
import { Download, ExternalLink, FolderSearch, Layers, Search, SquarePen, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { runCommand } from 'App/commands';
import { CheckInput, SelectInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { change, Cover, DeleteModal, plural } from 'Library/library';
import styles from 'Library/Library.module.css';
import { ComicDetail } from 'typings/Library';
import { api, urlBase } from 'Utilities/api';
import { deleteComics, setComicStatus } from './ComicIndex';
import EditComicModal from './EditComicModal';

function ComicDetails() {
  const { comicId = '' } = useParams();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<'comic' | 'issues' | null>(null);
  const [running, setRunning] = useState('');
  const [isEditOpen, setIsEditOpen] = useState(false);

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'comic', comicId],
    queryFn: () => api<ComicDetail>(`/library/comic/${encodeURIComponent(comicId)}`),
    retry: false,
  });

  const issues = data?.issueList ?? [];
  const selectedIds = issues.filter((issue) => selected.has(issue.id)).map((issue) => issue.id);

  function run(key: string, name: string, body: Record<string, unknown>, label: string) {
    setRunning(key);
    runCommand(name, body, label).finally(() => setRunning(''));
  }

  function openUrl(issueId: string) {
    return `${urlBase()}/open_comic?comicid=${encodeURIComponent(comicId)}&issueid=${encodeURIComponent(issueId)}`;
  }

  return (
    <PageContent title={data?.title ?? 'Comic'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Search"
            iconName={Search}
            isDisabled={!data}
            isSpinning={running === 'search'}
            onPress={() =>
              run('search', 'BookSearch', { books: [{ bookId: comicId, mediaType: 'comic' }] }, `Search for ${data?.title}`)
            }
          />
          <PageToolbarButton
            label="Scan"
            iconName={FolderSearch}
            isDisabled={!data}
            isSpinning={running === 'scan'}
            onPress={() => run('scan', 'LibraryScan', { mediaType: 'comic', comicId }, `Scan ${data?.title}`)}
          />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Edit"
            iconName={SquarePen}
            isDisabled={!data}
            onPress={() => setIsEditOpen(true)}
          />
          <PageToolbarButton
            label="Old Page"
            iconName={ExternalLink}
            isDisabled={!data}
            to={`/comicissue_page?comicid=${encodeURIComponent(comicId)}`}
          />
          <PageToolbarButton label="Delete" iconName={Trash2} isDisabled={!data} onPress={() => setDeleting('comic')} />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <PageToolbarButton
            label="Delete Selected Issues"
            iconName={Trash2}
            isDisabled={!selectedIds.length}
            onPress={() => setDeleting('issues')}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        {data ? (
          <div className={styles.header}>
            <div className={styles.headerImage}>
              <Cover src={data.cover} icon={Layers} size={64} />
            </div>
            <div className={styles.headerInfo}>
              <h1 className={styles.headerName}>
                {data.title}
                {data.start ? <span className={styles.muted}> ({data.start})</span> : null}
              </h1>
              <div className={styles.headerLabels}>
                <SelectInput
                  className={styles.statusSelect}
                  value={data.status}
                  values={[
                    { key: 'Active', value: 'Active', hint: 'New issues are looked for' },
                    { key: 'Paused', value: 'Paused', hint: "New issues aren't looked for" },
                  ]}
                  onChange={(status) => setComicStatus([data.id], status)}
                />
                <Label>{plural(data.issues, 'issue')}</Label>
                {data.publisher ? <Label>{data.publisher}</Label> : null}
                {data.first || data.last ? (
                  <Label>
                    Issues {data.first} – {data.last}
                  </Label>
                ) : null}
                {data.added ? <Label>Added {data.added}</Label> : null}
              </div>
              {data.link ? (
                <div className={styles.links}>
                  <Link to={data.link}>
                    <Icon name={ExternalLink} size={13} /> {data.id.startsWith('CV') ? 'ComicVine' : 'Comixology'}
                  </Link>
                </div>
              ) : null}
              {data.overview ? (
                <div className={styles.aboutClosed}>
                  <p>{new DOMParser().parseFromString(data.overview, 'text/html').body.textContent}</p>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {data && !issues.length ? <Alert kind="info">No issues yet. Search for it, or scan its folder.</Alert> : null}
        {issues.length ? (
          <div className={styles.issues}>
            {issues.map((issue) => (
              <div key={issue.id} className={styles.issue}>
                <a className={styles.issueCover} href={openUrl(issue.id)}>
                  <Cover src={issue.cover} icon={Layers} />
                </a>
                <div className={styles.issueInfo}>
                  <label className={styles.check}>
                    <CheckInput
                      checked={selected.has(issue.id)}
                      label={`Select issue ${issue.id}`}
                      onChange={(isSelected) =>
                        setSelected((current) => {
                          const next = new Set(current);
                          if (isSelected) {
                            next.add(issue.id);
                          } else {
                            next.delete(issue.id);
                          }
                          return next;
                        })
                      }
                    />
                    <span className={styles.issueDate}>#{issue.id}</span>
                  </label>
                  <div className={styles.issueMeta}>
                    {issue.format ? <Label kind="success">{issue.format}</Label> : <Label>No file</Label>}
                    <a href={openUrl(issue.id)} title="Open">
                      <Icon name={Download} size={14} />
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        {issues.length ? <div className={styles.footer}>{plural(issues.length, 'issue')}</div> : null}
      </PageContentBody>

      <DeleteModal
        isOpen={deleting === 'comic'}
        title={data?.title ?? ''}
        filesLabel="Delete its issue files"
        filesHelp="The files of its issues are deleted"
        keepHelp="Its issue files stay where they are, a library scan would find them again"
        onDelete={(deleteFiles) =>
          deleteComics([comicId], deleteFiles).then((result) => (result ? navigate('/comics') : null))
        }
        onModalClose={() => setDeleting(null)}
      />
      <DeleteModal
        isOpen={deleting === 'issues'}
        title={plural(selectedIds.length, 'issue')}
        filesLabel="Delete their files"
        filesHelp="The issues' files are deleted"
        keepHelp="Their files stay where they are, a library scan would find them again"
        onDelete={(deleteFiles) =>
          change(
            `/library/comic/${encodeURIComponent(comicId)}/issues`,
            'DELETE',
            { ids: selectedIds, deleteFiles },
            (changed) => `${plural(changed, 'issue')} deleted`,
            'Deleting failed'
          ).then(() => setSelected(new Set()))
        }
        onModalClose={() => setDeleting(null)}
      />
      {isEditOpen ? (
        <EditComicModal
          comicId={comicId}
          onSaved={(saved) => (saved !== comicId ? navigate(`/comic/${encodeURIComponent(saved)}`) : null)}
          onModalClose={() => setIsEditOpen(false)}
        />
      ) : null}
    </PageContent>
  );
}

export default ComicDetails;
