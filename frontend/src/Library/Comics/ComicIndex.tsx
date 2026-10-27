// Sonarr's series index for comics: covers or a table, paused or deleted here, searched for and
// the library scanned
import { useQuery } from '@tanstack/react-query';
import { Cog, FolderSearch, Layers, LayoutGrid, Plus, Search, Table as TableIcon, Trash2 } from 'lucide-react';
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
import { Comic } from 'typings/Library';
import { api } from 'Utilities/api';

const COLUMNS: Column[] = [
  { name: 'status', label: 'Status' },
  { name: 'title', label: 'Comic' },
  { name: 'publisher', label: 'Publisher' },
  { name: 'latest', label: 'Latest Issue' },
  { name: 'acquired', label: 'Last Acquired' },
  { name: 'issues', label: 'Issues' },
];

const FILTERS = [
  { key: 'all', value: 'All' },
  { key: 'Active', value: 'Active' },
  { key: 'Paused', value: 'Paused' },
];

export function comicPath(id: string) {
  return `/comic/${encodeURIComponent(id)}`;
}

export function setComicStatus(ids: string[], status: string) {
  return change(
    '/library/comics',
    'PUT',
    { ids, status },
    (changed) => `${plural(changed, 'comic')} set ${status}`,
    'Setting the status failed'
  );
}

export function deleteComics(ids: string[], deleteFiles: boolean) {
  return change(
    '/library/comics',
    'DELETE',
    { ids, deleteFiles },
    (changed) => `${plural(changed, 'comic')} deleted`,
    'Deleting failed'
  );
}

function ComicIndex() {
  const [view, setView] = useState(() => remembered('comics.view', 'posters'));
  const [filter, setFilter] = useState(() => remembered('comics.filter', 'all'));
  const [term, setTerm] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [running, setRunning] = useState('');

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'comics'],
    queryFn: () => api<Comic[]>('/library/comics'),
  });

  const shown = useMemo(() => {
    const wanted = term.trim().toLowerCase();
    return (data ?? []).filter(
      (comic) => (filter === 'all' || comic.status === filter) && (!wanted || comic.title.toLowerCase().includes(wanted))
    );
  }, [data, filter, term]);
  const selectedIds = shown.filter((comic) => selected.has(comic.id)).map((comic) => comic.id);
  const allSelected = shown.length > 0 && selectedIds.length === shown.length;
  const issues = shown.reduce((count, comic) => count + comic.issues, 0);

  function run(key: string, name: string, body: Record<string, unknown>, label: string) {
    setRunning(key);
    runCommand(name, body, label).finally(() => setRunning(''));
  }

  return (
    <PageContent title="Comics">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Add New" iconName={Plus} to="/comics/add" />
          <PageToolbarButton
            label="Search All"
            iconName={Search}
            isSpinning={running === 'search'}
            onPress={() => run('search', 'RunTask', { task: 'search_comics' }, 'Search for comics')}
          />
          <PageToolbarButton
            label="Library Scan"
            iconName={FolderSearch}
            isSpinning={running === 'scan'}
            onPress={() => run('scan', 'LibraryScan', { mediaType: 'comic' }, 'Scan the comic library')}
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
                isDisabled={!selectedIds.length}
                values={[
                  { key: '', value: 'Set status…' },
                  { key: 'Active', value: 'Active' },
                  { key: 'Paused', value: 'Paused' },
                ]}
                onChange={(status) => {
                  if (status) {
                    setComicStatus(selectedIds, status);
                    setSelected(new Set());
                  }
                }}
              />
              <PageToolbarButton
                label="Delete"
                iconName={Trash2}
                isDisabled={!selectedIds.length}
                onPress={() => setIsDeleteOpen(true)}
              />
            </>
          ) : null}
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <RssButton type="Comic" label="RSS Feed" />
          <PageToolbarButton
            label={view === 'posters' ? 'Table' : 'Covers'}
            iconName={view === 'posters' ? TableIcon : LayoutGrid}
            onPress={() => {
              const next = view === 'posters' ? 'table' : 'posters';
              setView(next);
              remember('comics.view', next);
            }}
          />
          <SelectInput
            className={styles.filter}
            value={filter}
            values={FILTERS}
            onChange={(value) => {
              setFilter(value);
              remember('comics.filter', value);
            }}
          />
          <TextInput className={styles.filter} value={term} placeholder="Filter" onChange={setTerm} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the comics: {(error as Error).message}</Alert> : null}
        {data && !data.length ? (
          <Alert kind="info">
            There are no comics yet. <Link to="/comics/add">Add New</Link> finds them at ComicVine and
            Comixology.
          </Alert>
        ) : null}

        {shown.length && view === 'posters' ? (
          <div className={styles.posters}>
            {shown.map((comic) => (
              <PosterCard
                key={comic.id}
                to={comicPath(comic.id)}
                cover={comic.cover}
                icon={Layers}
                name={comic.title}
                corner={comic.status !== 'Active' ? <Label kind="warning">{comic.status}</Label> : null}
              >
                <div className={styles.posterFooter}>
                  {plural(comic.issues, 'issue')}
                  {comic.start ? ` · ${comic.start}` : ''}
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
                isIndeterminate={!allSelected && selectedIds.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(shown.map((c) => c.id)) : new Set())}
              />
            }
          >
            {shown.map((comic) => (
              <TableRow key={comic.id}>
                <TableRowCell className={styles.select}>
                  <CheckInput
                    checked={selected.has(comic.id)}
                    label={`Select ${comic.title}`}
                    onChange={(isSelected) =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (isSelected) {
                          next.add(comic.id);
                        } else {
                          next.delete(comic.id);
                        }
                        return next;
                      })
                    }
                  />
                </TableRowCell>
                <TableRowCell>
                  <Label kind={comic.status === 'Active' ? 'success' : 'warning'}>{comic.status}</Label>
                </TableRowCell>
                <TableRowCell>
                  <Link to={comicPath(comic.id)}>{comic.title}</Link>
                  {comic.start ? <span className={styles.muted}> ({comic.start})</span> : null}
                </TableRowCell>
                <TableRowCell>{comic.publisher}</TableRowCell>
                <TableRowCell className={styles.date}>{comic.latestIssue}</TableRowCell>
                <TableRowCell className={styles.date}>{comic.lastAcquired}</TableRowCell>
                <TableRowCell>{comic.issues}</TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}
        {data && data.length && !shown.length ? <Alert kind="info">No comic matches the filter</Alert> : null}
        {shown.length ? (
          <div className={styles.footer}>
            {plural(shown.length, 'comic')} · {plural(issues, 'issue')}
          </div>
        ) : null}
      </PageContentBody>

      <DeleteModal
        isOpen={isDeleteOpen}
        title={selectedIds.length === 1 ? (shown.find((c) => c.id === selectedIds[0])?.title ?? '') : plural(selectedIds.length, 'comic')}
        filesLabel="Delete their issue files"
        filesHelp="The files of their issues are deleted"
        keepHelp="Their issue files stay where they are, a library scan would find them again"
        onDelete={(deleteFiles) => deleteComics(selectedIds, deleteFiles).then(() => setSelected(new Set()))}
        onModalClose={() => setIsDeleteOpen(false)}
      />
    </PageContent>
  );
}

export default ComicIndex;
