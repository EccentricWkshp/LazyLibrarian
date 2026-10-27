// Sonarr's series details for a magazine: its cover and status, what Wikidata says about it, the
// issues it's missing and when the next is due, and its issues, each to read, download, send to a
// device, give another cover or edit. Selected issues can have their covers made again, a page
// swapped to the front, their PDFs tagged, or be deleted
import { useQuery } from '@tanstack/react-query';
import {
  BookOpen,
  Download,
  ExternalLink,
  FolderSearch,
  History,
  Image,
  Newspaper,
  Pencil,
  RefreshCw,
  Search,
  Send,
  SquarePen,
  Trash2,
} from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { runCommand } from 'App/commands';
import { CheckInput, SelectInput } from 'Components/Form/Form';
import FormattedDate from 'Components/FormattedDate';
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
import { change, Cover, DeleteModal, plural, RssButton } from 'Library/library';
import styles from 'Library/Library.module.css';
import CoverPickerModal from 'Library/Reader/CoverPickerModal';
import { canRead, filePath, readerPath, sendToDevice } from 'Library/Reader/reading';
import { IssueSchedule, MagazineDetail, MagazineIssue } from 'typings/Library';
import { api } from 'Utilities/api';
import { useDates } from 'Utilities/dates';
import EditIssueModal from './EditIssueModal';
import EditMagazineModal from './EditMagazineModal';
import { deleteMagazines, setMagazineStatus } from './MagazineIndex';

// how often it comes out, in words
export function frequencyName(days: number) {
  const names: [number, number, string][] = [
    [1, 1, 'Daily'],
    [7, 7, 'Weekly'],
    [13, 15, 'Every two weeks'],
    [28, 31, 'Monthly'],
    [56, 62, 'Every two months'],
    [84, 92, 'Quarterly'],
    [180, 183, 'Twice a year'],
    [360, 366, 'Yearly'],
  ];
  const found = names.find(([low, high]) => days >= low && days <= high);

  return found ? found[2] : days ? `Every ${days} days` : '';
}

const ISSUE_ACTIONS = [
  { key: '', value: 'Selected issues…' },
  { key: 'covers', value: "Make covers from the magazine's cover page" },
  { key: 'swap', value: 'Move page 2 to the front of the PDF' },
  { key: 'tag', value: "Tag the PDFs with the magazine's details" },
  { key: 'delete', value: 'Delete them…' },
];

function Schedule({ schedule, title }: { schedule: IssueSchedule; title: string }) {
  const [showAll, setShowAll] = useState(false);
  const dates = useDates();
  const missing = schedule.missing.map(dates.issue);
  const howOften = frequencyName(schedule.frequency);

  if (!schedule.next && !missing.length) {
    return null;
  }

  return (
    <div className={styles.schedule}>
      {schedule.next ? (
        <p className={schedule.overdue ? styles.overdue : styles.muted}>
          {howOften ? `${howOften}${schedule.inferred ? ', judging by its issues' : ''}. ` : ''}
          The next issue
          {/^\d+$/.test(schedule.next) ? ` is number ${schedule.next}` : ` is due around ${dates.issue(schedule.next)}`}
          {schedule.overdue ? ', and it is overdue' : ''}.
        </p>
      ) : null}
      {missing.length ? (
        <Alert kind="warning">
          {plural(missing.length, 'issue')} missing between the first and the latest:{' '}
          {(showAll ? missing : missing.slice(0, 12)).join(', ')}
          {missing.length > 12 && !showAll ? (
            <>
              {' '}
              <Link onPress={() => setShowAll(true)}>and {missing.length - 12} more</Link>
            </>
          ) : null}
          . <Link to={`/magazines/pastissues?title=${encodeURIComponent(title)}`}>Past Issues</Link> has the ones a
          search found but didn't want.
        </Alert>
      ) : null}
    </div>
  );
}

function IssueCard({
  issue,
  isSelected,
  onSelectedChange,
  onEdit,
  onCover,
}: {
  issue: MagazineIssue;
  isSelected: boolean;
  onSelectedChange: (isSelected: boolean) => void;
  onEdit: () => void;
  onCover: () => void;
}) {
  const readable = !!issue.format && canRead(issue.format);
  const date = useDates().issue(issue.date);

  return (
    <div className={styles.issue}>
      <Link
        className={styles.issueCover}
        to={readable ? readerPath('issue', issue.id) : filePath('issue', issue.id, '', true)}
        noRouter={!readable}
        title={readable ? 'Read' : 'Download'}
      >
        <Cover src={issue.cover} icon={Newspaper} />
      </Link>
      <div className={styles.issueInfo}>
        <label className={styles.check}>
          <CheckInput checked={isSelected} label={`Select ${issue.date}`} onChange={onSelectedChange} />
          <span className={styles.issueDate} title={issue.date}>
            {date}
          </span>
        </label>
        {issue.number || issue.pages ? (
          <div className={styles.muted}>
            {[issue.number, issue.pages ? plural(issue.pages, 'page') : ''].filter(Boolean).join(' · ')}
          </div>
        ) : null}
        {issue.description ? (
          <div className={styles.issueDescription} title={issue.description}>
            {issue.description}
          </div>
        ) : null}
        <div className={styles.issueMeta}>
          {issue.format ? <Label kind="success">{issue.format}</Label> : <Label>No file</Label>}
          {readable ? (
            <Link to={readerPath('issue', issue.id)} title="Read">
              <Icon name={BookOpen} size={14} />
            </Link>
          ) : null}
          {issue.format ? (
            <>
              <Link to={filePath('issue', issue.id, '', true)} noRouter={true} title="Download">
                <Icon name={Download} size={14} />
              </Link>
              <Link title="Send to Device" onPress={() => sendToDevice('issue', issue.id, date)}>
                <Icon name={Send} size={14} />
              </Link>
              <Link title="Choose the cover" onPress={onCover}>
                <Icon name={Image} size={14} />
              </Link>
            </>
          ) : null}
          <Link title="Edit the issue" onPress={onEdit}>
            <Icon name={Pencil} size={14} />
          </Link>
        </div>
      </div>
    </div>
  );
}

function MagazineDetails() {
  const [params] = useSearchParams();
  const title = params.get('title') ?? '';
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<'magazine' | 'issues' | null>(null);
  const [running, setRunning] = useState('');
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editingIssue, setEditingIssue] = useState('');
  const [coverIssue, setCoverIssue] = useState<MagazineIssue | null>(null);

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'magazine', title],
    queryFn: () => api<MagazineDetail>('/library/magazine', { query: { title } }),
    retry: false,
  });

  const issues = data?.issueList ?? [];
  const selectedIds = issues.filter((issue) => selected.has(issue.id)).map((issue) => issue.id);
  const allSelected = issues.length > 0 && selectedIds.length === issues.length;
  const details = data
    ? [
        data.publisher,
        data.country,
        data.started ? `Since ${data.started}` : '',
        frequencyName(data.frequency),
        data.issn ? `ISSN ${data.issn}` : '',
      ].filter(Boolean)
    : [];

  function run(key: string, name: string, body: Record<string, unknown>, label: string) {
    setRunning(key);
    runCommand(name, body, label).finally(() => setRunning(''));
  }

  function issueAction(action: string) {
    const ids = selectedIds;
    if (action === 'covers') {
      run('issues', 'IssueCovers', { ids }, `Make the covers of ${plural(ids.length, 'issue')}`);
    } else if (action === 'swap') {
      run('issues', 'SwapCover', { ids, page: 2 }, `Move page 2 to the front of ${plural(ids.length, 'issue')}`);
    } else if (action === 'tag') {
      run('issues', 'TagIssues', { ids }, `Tag ${plural(ids.length, 'issue')}`);
    } else if (action === 'delete') {
      // they stay selected for the delete to take
      setDeleting('issues');
      return;
    }
    setSelected(new Set());
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
          <PageToolbarButton
            label="Refresh"
            iconName={RefreshCw}
            isDisabled={!data}
            isSpinning={running === 'refresh'}
            onPress={() => run('refresh', 'RefreshMagazine', { title: data?.title }, `Refresh ${title} from Wikidata`)}
          />
          <PageToolbarSeparator />
          <PageToolbarButton label="Edit" iconName={SquarePen} isDisabled={!data} onPress={() => setIsEditOpen(true)} />
          <PageToolbarButton
            label="Past Issues"
            iconName={History}
            isDisabled={!data}
            to={`/magazines/pastissues?title=${encodeURIComponent(title)}`}
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
          <RssButton type="Magazine" only={title} label="RSS Feed" />
          <SelectInput
            className={styles.filter}
            value=""
            isDisabled={!selectedIds.length || running === 'issues'}
            values={ISSUE_ACTIONS}
            onChange={issueAction}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        {data ? (
          <div className={styles.header}>
            <div className={styles.headerImage}>
              <Cover src={data.cover || data.logo} icon={Newspaper} size={64} />
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
                {data.latestIssue ? (
                  <Label>
                    Latest <FormattedDate value={data.latestIssue} kind="issue" />
                  </Label>
                ) : null}
                {data.language ? <Label>{data.language}</Label> : null}
                {data.added ? (
                  <Label>
                    Added <FormattedDate value={data.added} />
                  </Label>
                ) : null}
              </div>
              {details.length ? <p className={styles.muted}>{details.join(' · ')}</p> : null}
              {data.description ? <p className={styles.overview}>{data.description}</p> : null}
              <p className={styles.links}>
                {data.website ? <Link to={data.website}>Website</Link> : null}
                {data.wikidataId ? (
                  <Link to={`https://www.wikidata.org/wiki/${encodeURIComponent(data.wikidataId)}`}>Wikidata</Link>
                ) : (
                  <span className={styles.muted}>
                    Not linked to Wikidata. <Link onPress={() => setIsEditOpen(true)}>Choose it in Edit</Link>
                  </span>
                )}
              </p>
              {data.rejectWords ? (
                <p className={styles.muted}>Releases with {data.rejectWords} in their name are ruled out</p>
              ) : null}
              {data.genre ? <p className={styles.muted}>{data.genre}</p> : null}
            </div>
          </div>
        ) : null}

        {data ? <Schedule schedule={data.schedule} title={data.title} /> : null}

        {data && !issues.length ? <Alert kind="info">No issues yet. Search for it, or scan its folder.</Alert> : null}
        {issues.length ? (
          <>
            <label className={styles.check}>
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedIds.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(issues.map((issue) => issue.id)) : new Set())}
              />
              <span className={styles.muted}>Select all</span>
            </label>
            <div className={styles.issues}>
              {issues.map((issue) => (
                <IssueCard
                  key={issue.id}
                  issue={issue}
                  isSelected={selected.has(issue.id)}
                  onSelectedChange={(isSelected) =>
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
                  onEdit={() => setEditingIssue(issue.id)}
                  onCover={() => setCoverIssue(issue)}
                />
              ))}
            </div>
          </>
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
      {coverIssue ? (
        <CoverPickerModal
          kind="issue"
          id={coverIssue.id}
          name={`${title} ${coverIssue.date}`}
          current={data?.coverPage}
          onModalClose={() => setCoverIssue(null)}
        />
      ) : null}
    </PageContent>
  );
}

export default MagazineDetails;
