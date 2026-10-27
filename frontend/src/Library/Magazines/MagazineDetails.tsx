// Sonarr's series details for a magazine: its cover and status, and its issues, each to open or
// delete, with the magazine searched for or its folder scanned
import { useQuery } from '@tanstack/react-query';
import { Download, ExternalLink, FolderSearch, Newspaper, Pencil, Search, SquarePen, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
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
import { MagazineDetail } from 'typings/Library';
import { api, urlBase } from 'Utilities/api';
import EditIssueModal from './EditIssueModal';
import EditMagazineModal from './EditMagazineModal';
import { deleteMagazines, setMagazineStatus } from './MagazineIndex';

function MagazineDetails() {
  const [params] = useSearchParams();
  const title = params.get('title') ?? '';
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<'magazine' | 'issues' | null>(null);
  const [running, setRunning] = useState('');
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editingIssue, setEditingIssue] = useState('');

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'magazine', title],
    queryFn: () => api<MagazineDetail>('/library/magazine', { query: { title } }),
    retry: false,
  });

  const issues = data?.issueList ?? [];
  const selectedIds = issues.filter((issue) => selected.has(issue.id)).map((issue) => issue.id);

  function run(key: string, name: string, body: Record<string, unknown>, label: string) {
    setRunning(key);
    runCommand(name, body, label).finally(() => setRunning(''));
  }

  return (
    <PageContent title={data?.title ?? 'Magazine'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Search"
            iconName={Search}
            isDisabled={!data}
            isSpinning={running === 'search'}
            onPress={() =>
              run('search', 'BookSearch', { books: [{ bookId: data?.title, mediaType: 'magazine' }] }, `Search for ${title}`)
            }
          />
          <PageToolbarButton
            label="Scan"
            iconName={FolderSearch}
            isDisabled={!data}
            isSpinning={running === 'scan'}
            onPress={() => run('scan', 'LibraryScan', { mediaType: 'magazine', title: data?.title }, `Scan ${title}`)}
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
            to={`/issue_page?title=${encodeURIComponent(title)}`}
          />
          <PageToolbarButton label="Delete" iconName={Trash2} isDisabled={!data} onPress={() => setDeleting('magazine')} />
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
              <Cover src={data.cover} icon={Newspaper} size={64} />
            </div>
            <div className={styles.headerInfo}>
              <h1 className={styles.headerName}>{data.title}</h1>
              <div className={styles.headerLabels}>
                <SelectInput
                  className={styles.statusSelect}
                  value={data.status}
                  values={[
                    { key: 'Active', value: 'Active', hint: 'New issues are looked for' },
                    { key: 'Paused', value: 'Paused', hint: "New issues aren't looked for" },
                  ]}
                  onChange={(status) => setMagazineStatus([data.title], status)}
                />
                <Label>{plural(data.issues, 'issue')}</Label>
                {data.latestIssue ? <Label>Latest {data.latestIssue}</Label> : null}
                {data.language ? <Label>{data.language}</Label> : null}
                {data.added ? <Label>Added {data.added}</Label> : null}
              </div>
              {data.rejectWords ? (
                <p className={styles.muted}>Releases with {data.rejectWords} in their name are ruled out</p>
              ) : null}
              {data.genre ? <p className={styles.muted}>{data.genre}</p> : null}
            </div>
          </div>
        ) : null}

        {data && !issues.length ? <Alert kind="info">No issues yet. Search for it, or scan its folder.</Alert> : null}
        {issues.length ? (
          <div className={styles.issues}>
            {issues.map((issue) => (
              <div key={issue.id} className={styles.issue}>
                <a className={styles.issueCover} href={`${urlBase()}/open_mag?bookid=${encodeURIComponent(issue.id)}`}>
                  <Cover src={issue.cover} icon={Newspaper} />
                </a>
                <div className={styles.issueInfo}>
                  <label className={styles.check}>
                    <CheckInput
                      checked={selected.has(issue.id)}
                      label={`Select ${issue.date}`}
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
                    <span className={styles.issueDate}>{issue.date}</span>
                  </label>
                  <div className={styles.issueMeta}>
                    {issue.format ? <Label kind="success">{issue.format}</Label> : <Label>No file</Label>}
                    <a href={`${urlBase()}/open_mag?bookid=${encodeURIComponent(issue.id)}`} title="Open">
                      <Icon name={Download} size={14} />
                    </a>
                    <Link title="Edit the issue" onPress={() => setEditingIssue(issue.id)}>
                      <Icon name={Pencil} size={14} />
                    </Link>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        {issues.length ? <div className={styles.footer}>{plural(issues.length, 'issue')}</div> : null}
      </PageContentBody>

      <DeleteModal
        isOpen={deleting === 'magazine'}
        title={title}
        filesLabel="Delete its issue files"
        filesHelp="The files of its issues are deleted"
        keepHelp="Its issue files stay where they are, a library scan would find them again"
        onDelete={(deleteFiles) =>
          deleteMagazines([title], deleteFiles).then((result) => (result ? navigate('/magazines') : null))
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
            '/library/magazine/issues',
            'DELETE',
            { ids: selectedIds, deleteFiles },
            (changed) => `${plural(changed, 'issue')} deleted`,
            'Deleting failed'
          ).then(() => setSelected(new Set()))
        }
        onModalClose={() => setDeleting(null)}
      />
      {isEditOpen ? (
        <EditMagazineModal
          title={title}
          onSaved={(saved) => (saved !== title ? navigate(`/magazine?title=${encodeURIComponent(saved)}`) : null)}
          onModalClose={() => setIsEditOpen(false)}
        />
      ) : null}
      {editingIssue ? (
        <EditIssueModal
          issueId={editingIssue}
          onSaved={(saved) => (saved !== title ? navigate(`/magazine?title=${encodeURIComponent(saved)}`) : null)}
          onModalClose={() => setEditingIssue('')}
        />
      ) : null}
    </PageContent>
  );
}

export default MagazineDetails;
