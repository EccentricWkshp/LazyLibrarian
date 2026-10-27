// Sonarr's EditSeriesModal for an author: their name, dates and description, their picture, and the
// info sources they're linked to, found by name or by an id
import { Search } from 'lucide-react';
import { useState } from 'react';
import queryClient from 'App/queryClient';
import { CheckInput, TextArea, TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import { Alert, Label } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import { EditColumns, EditField, EditModal, PictureChoices, useEdit } from 'Library/Edit/edit';
import styles from 'Library/Edit/Edit.module.css';
import { api } from 'Utilities/api';

interface AuthorSource {
  source: string;
  id: string;
  enabled: boolean;
  primary: boolean;
}

interface AuthorEdit {
  id: string;
  name: string;
  born: string;
  died: string;
  aka: string;
  amazonUrl: string;
  about: string;
  locked: boolean;
  reason: string;
  image: string;
  sources: AuthorSource[];
  // a picture found, by its path
  found: string;
}

interface SourceMatch {
  found: boolean;
  id: string;
  name: string;
  link: string;
}

function SourceRow({
  authorId,
  source,
  onChange,
}: {
  authorId: string;
  source: AuthorSource;
  onChange: (sources: AuthorSource[]) => void;
}) {
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState('');
  const [problem, setProblem] = useState('');
  const [match, setMatch] = useState<SourceMatch | null>(null);
  const [linking, setLinking] = useState('');
  const base = `/author/${encodeURIComponent(authorId)}/source/${encodeURIComponent(source.source)}`;

  async function run(what: string, action: () => Promise<void>) {
    setBusy(what);
    setProblem('');
    try {
      await action();
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setBusy('');
    }
  }

  function changed(sources: AuthorSource[]) {
    onChange(sources);
    queryClient.invalidateQueries({ queryKey: ['author'] });
  }

  return (
    <tr>
      <td>{source.source}</td>
      <td>{source.id || <span className={styles.readonly}>Not linked</span>}</td>
      <td>
        {source.id ? (
          <input
            type="radio"
            name="primarySource"
            aria-label={`Use ${source.source} for the author's link`}
            checked={source.primary}
            onChange={() => run('primary', async () => changed(await api(`${base}/primary`, { method: 'POST' })))}
          />
        ) : null}
      </td>
      <td>
        <div className={styles.sourceActions}>
          {source.id ? (
            <Button
              kind="danger"
              isSpinning={busy === 'unlink'}
              onPress={() => run('unlink', async () => changed(await api(base, { method: 'DELETE' })))}
            >
              Unlink
            </Button>
          ) : source.enabled ? (
            <>
              <Button
                isSpinning={busy === 'search'}
                onPress={() =>
                  run('search', async () => {
                    const found = await api<SourceMatch>(`${base}/search`, { method: 'POST' });
                    setMatch(found);
                  })
                }
              >
                <Icon name={Search} /> Search
              </Button>
              <TextInput
                aria-label={`${source.source} id`}
                placeholder="or its id"
                value={typed}
                onChange={setTyped}
              />
              <Button isDisabled={!typed.trim()} onPress={() => setLinking(typed.trim())}>
                Link
              </Button>
            </>
          ) : (
            <span className={styles.readonly}>Off in Settings, Metadata</span>
          )}
        </div>
        {match && !match.found ? <div className={styles.readonly}>Not found by name on {source.source}</div> : null}
        {match?.found ? (
          <div className={styles.sourceActions}>
            <span>
              Found {match.name} ({match.id})
            </span>
            <Button kind="primary" onPress={() => setLinking(match.id)}>
              Link
            </Button>
          </div>
        ) : null}
        {problem ? <div className={styles.readonly}>{problem}</div> : null}
        <ConfirmModal
          isOpen={!!linking}
          title={`Link to ${source.source}`}
          message={`Link this author to ${source.source} id ${linking}? Check the id is theirs, it isn't checked against their name.`}
          confirmLabel="Link"
          kind="primary"
          onConfirm={() => {
            const sourceId = linking;
            setLinking('');
            setMatch(null);
            run('link', async () => changed(await api(base, { method: 'PUT', body: { sourceId } })));
          }}
          onCancel={() => setLinking('')}
        />
      </td>
    </tr>
  );
}

function EditAuthorModal({ authorId, onModalClose }: { authorId: string; onModalClose: () => void }) {
  const edit = useEdit<AuthorEdit>(`/author/${encodeURIComponent(authorId)}/edit`, true);
  const [sources, setSources] = useState<AuthorSource[] | null>(null);
  const author = edit.values;

  return (
    <EditModal
      isOpen={true}
      title={author ? `Edit - ${author.name}` : 'Edit Author'}
      isLoading={edit.loaded.isLoading}
      loadError={edit.loaded.error}
      error={edit.error}
      isSaving={edit.isSaving}
      isChanged={Object.keys(edit.edited).length > 0}
      onSave={() => edit.save({}, onModalClose)}
      onModalClose={onModalClose}
    >
      {author ? (
        <>
          <EditField id="authorName" label="Name">
            <TextInput id="authorName" value={author.name} onChange={(name) => edit.set('name', name)} />
          </EditField>
          <EditColumns>
            <EditField id="authorBorn" label="Born" help="Year-month-day, empty for not known">
              <TextInput id="authorBorn" value={author.born} onChange={(born) => edit.set('born', born)} />
            </EditField>
            <EditField id="authorDied" label="Died">
              <TextInput id="authorDied" value={author.died} onChange={(died) => edit.set('died', died)} />
            </EditField>
          </EditColumns>
          <EditField id="authorAka" label="Also Known As" help="Other names they write as, separated by commas">
            <TextInput id="authorAka" value={author.aka} onChange={(aka) => edit.set('aka', aka)} />
          </EditField>
          <EditField id="authorAmazon" label="Amazon Author Page" help="It can't be looked up, paste it if you find it">
            <TextInput
              id="authorAmazon"
              placeholder="https://www.amazon.com/stores/.../author/..."
              value={author.amazonUrl}
              onChange={(amazonUrl) => edit.set('amazonUrl', amazonUrl)}
            />
          </EditField>
          <EditField id="authorAbout" label="About">
            <TextArea id="authorAbout" rows={6} value={author.about} onChange={(about) => edit.set('about', about)} />
          </EditField>

          <EditField label="Picture" help="Choose one found, or give a link or a file below">
            <PictureChoices<{ name: string; path: string }>
              url={`/author/${encodeURIComponent(authorId)}/images`}
              label="picture"
              current={author.image}
              selected={author.found ? author.found.split('/').pop() ?? '' : ''}
              name={(choice) => choice.name}
              onSelect={(choice) => edit.set('found', choice ? choice.path : '')}
            />
          </EditField>
          <EditField
            id="authorImage"
            label="Picture From"
            help="A link or a file ending .jpg, .jpeg, .png or .webp, or none for no picture"
          >
            <TextInput
              id="authorImage"
              placeholder="https://..."
              value={(edit.edited as { image?: string }).image ?? ''}
              onChange={(image) => edit.set('image', image)}
            />
          </EditField>

          <EditField label="Info Sources" help="The checked one is the author's link and badge">
            <table className={styles.sources}>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>ID</th>
                  <th>Used</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {(sources ?? author.sources).map((source) => (
                  <SourceRow key={source.source} authorId={authorId} source={source} onChange={setSources} />
                ))}
              </tbody>
            </table>
          </EditField>

          <label className={styles.check}>
            <CheckInput checked={author.locked} label="Lock" onChange={(locked) => edit.set('locked', locked)} />
            <span>Lock: a refresh doesn't change what's set here</span>
          </label>
          {author.reason ? (
            <p className={styles.readonly}>
              <Label>Added</Label> {author.reason}
            </p>
          ) : null}
          {!author.sources.some((source) => source.enabled) ? (
            <Alert kind="info">No info source that links authors is on, see Settings, Metadata</Alert>
          ) : null}
        </>
      ) : null}
    </EditModal>
  );
}

export default EditAuthorModal;
