// Sonarr's series index for magazines: covers or a table, paused or deleted here, searched for
// and the library scanned
import { useQuery } from '@tanstack/react-query';
import { Cog, FolderSearch, LayoutGrid, Newspaper, Plus, Search, Table as TableIcon, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { runCommand } from 'App/commands';
import { CheckInput, SelectInput, TextInput } from 'Components/Form/Form';
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
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { change, DeleteModal, plural, PosterCard, remember, remembered, RssButton } from 'Library/library';
import styles from 'Library/Library.module.css';
import { Magazine } from 'typings/Library';
import { api } from 'Utilities/api';

const COLUMNS: Column[] = [
  { name: 'status', label: 'Status' },
  { name: 'title', label: 'Magazine' },
  { name: 'latest', label: 'Latest Issue' },
  { name: 'acquired', label: 'Last Acquired' },
  { name: 'issues', label: 'Issues' },
];

const FILTERS = [
  { key: 'all', value: 'All' },
  { key: 'Active', value: 'Active' },
  { key: 'Paused', value: 'Paused' },
];

export function magazinePath(title: string) {
  return `/magazine?title=${encodeURIComponent(title)}`;
}

export function setMagazineStatus(titles: string[], status: string) {
  return change(
    '/library/magazines',
    'PUT',
    { ids: titles, status },
    (changed) => `${plural(changed, 'magazine')} set ${status}`,
    'Setting the status failed'
  );
}

export function deleteMagazines(titles: string[], deleteFiles: boolean) {
  return change(
    '/library/magazines',
    'DELETE',
    { ids: titles, deleteFiles },
    (changed) => `${plural(changed, 'magazine')} deleted`,
    'Deleting failed'
  );
}

function MagazineIndex() {
  const [view, setView] = useState(() => remembered('magazines.view', 'posters'));
  const [filter, setFilter] = useState(() => remembered('magazines.filter', 'all'));
  const [term, setTerm] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [running, setRunning] = useState('');

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'magazines'],
    queryFn: () => api<Magazine[]>('/library/magazines'),
  });

  const shown = useMemo(() => {
    const wanted = term.trim().toLowerCase();
    return (data ?? []).filter(
      (magazine) =>
        (filter === 'all' || magazine.status === filter) && (!wanted || magazine.title.toLowerCase().includes(wanted))
    );
  }, [data, filter, term]);
  const selectedTitles = shown.filter((magazine) => selected.has(magazine.title)).map((magazine) => magazine.title);
  const allSelected = shown.length > 0 && selectedTitles.length === shown.length;
  const issues = shown.reduce((count, magazine) => count + magazine.issues, 0);

  function run(key: string, name: string, body: Record<string, unknown>, label: string) {
    setRunning(key);
    runCommand(name, body, label).finally(() => setRunning(''));
  }

  return (
    <PageContent title="Magazines">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Add New" iconName={Plus} to="/magazines/add" />
          <PageToolbarButton
            label="Search All"
            iconName={Search}
            isSpinning={running === 'search'}
            onPress={() => run('search', 'RunTask', { task: 'search_magazines' }, 'Search for magazines')}
          />
          <PageToolbarButton
            label="Library Scan"
            iconName={FolderSearch}
            isSpinning={running === 'scan'}
            onPress={() => run('scan', 'LibraryScan', { mediaType: 'magazine' }, 'Scan the magazine library')}
          />
          <PageToolbarButton
            label="Post-Process"
            iconName={Cog}
            onPress={() => runCommand('RunTask', { task: 'PostProcessor' }, 'Look for finished downloads')}
          />
          {view === 'table' ? (
            <>
              <PageToolbarSeparator />
              <SelectInput
                className={styles.filter}
                value=""
                isDisabled={!selectedTitles.length}
                values={[
                  { key: '', value: 'Set status…' },
                  { key: 'Active', value: 'Active' },
                  { key: 'Paused', value: 'Paused' },
                ]}
                onChange={(status) => {
                  if (status) {
                    setMagazineStatus(selectedTitles, status);
                    setSelected(new Set());
                  }
                }}
              />
              <PageToolbarButton
                label="Delete"
                iconName={Trash2}
                isDisabled={!selectedTitles.length}
                onPress={() => setIsDeleteOpen(true)}
              />
            </>
          ) : null}
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <RssButton type="Magazine" label="RSS Feed" />
          <PageToolbarButton
            label={view === 'posters' ? 'Table' : 'Covers'}
            iconName={view === 'posters' ? TableIcon : LayoutGrid}
            onPress={() => {
              const next = view === 'posters' ? 'table' : 'posters';
              setView(next);
              remember('magazines.view', next);
            }}
          />
          <SelectInput
            className={styles.filter}
            value={filter}
            values={FILTERS}
            onChange={(value) => {
              setFilter(value);
              remember('magazines.filter', value);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the magazines: {(error as Error).message}</Alert> : null}
        {data && !data.length ? (
          <Alert kind="info">
            There are no magazines yet. <Link to="/magazines/add">Add New</Link> adds one by its title.
          </Alert>
        ) : null}

        {shown.length && view === 'posters' ? (
          <div className={styles.posters}>
            {shown.map((magazine) => (
              <PosterCard
                key={magazine.title}
                to={magazinePath(magazine.title)}
                cover={magazine.cover}
                icon={Newspaper}
                name={magazine.title}
                corner={magazine.status !== 'Active' ? <Label kind="warning">{magazine.status}</Label> : null}
              >
                <div className={styles.posterFooter}>
                  {plural(magazine.issues, 'issue')}
                  {magazine.latestIssue ? ` · ${magazine.latestIssue}` : ''}
                </div>
              </PosterCard>
            ))}
          </div>
        ) : null}

        {shown.length && view === 'table' ? (
          <Table
            columns={COLUMNS}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedTitles.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(shown.map((m) => m.title)) : new Set())}
              />
            }
          >
            {shown.map((magazine) => (
              <TableRow key={magazine.title}>
                <TableRowCell className={styles.select}>
                  <CheckInput
                    checked={selected.has(magazine.title)}
                    label={`Select ${magazine.title}`}
                    onChange={(isSelected) =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (isSelected) {
                          next.add(magazine.title);
                        } else {
                          next.delete(magazine.title);
                        }
                        return next;
                      })
                    }
                  />
                </TableRowCell>
                <TableRowCell>
                  <Label kind={magazine.status === 'Active' ? 'success' : 'warning'}>{magazine.status}</Label>
                </TableRowCell>
                <TableRowCell>
                  <Link to={magazinePath(magazine.title)}>{magazine.title}</Link>
                </TableRowCell>
                <TableRowCell className={styles.date}>{magazine.latestIssue}</TableRowCell>
                <TableRowCell className={styles.date}>{magazine.lastAcquired}</TableRowCell>
                <TableRowCell>{magazine.issues}</TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}
        {data && data.length && !shown.length ? <Alert kind="info">No magazine matches the filter</Alert> : null}
        {shown.length ? (
          <div className={styles.footer}>
            {plural(shown.length, 'magazine')} · {plural(issues, 'issue')}
          </div>
        ) : null}
      </PageContentBody>

      <DeleteModal
        isOpen={isDeleteOpen}
        title={selectedTitles.length === 1 ? selectedTitles[0] : plural(selectedTitles.length, 'magazine')}
        filesLabel="Delete their issue files"
        filesHelp="The files of their issues are deleted"
        keepHelp="Their issue files stay where they are, a library scan would find them again"
        onDelete={(deleteFiles) => deleteMagazines(selectedTitles, deleteFiles).then(() => setSelected(new Set()))}
        onModalClose={() => setIsDeleteOpen(false)}
      />
    </PageContent>
  );
}

export default MagazineIndex;
