// Sonarr's edit modal for a comic: its title, ComicVine id, other ids, genres and description
import { TextArea, TextInput } from 'Components/Form/Form';
import { Alert } from 'Components/Misc';
import { EditField, EditModal, useEdit } from 'Library/Edit/edit';

interface ComicEdit {
  id: string;
  title: string;
  aka: string;
  description: string;
  genre: string;
}

function EditComicModal({
  comicId,
  onSaved,
  onModalClose,
}: {
  comicId: string;
  // with its id now
  onSaved: (id: string) => void;
  onModalClose: () => void;
}) {
  const edit = useEdit<ComicEdit>(`/library/comic/${encodeURIComponent(comicId)}/edit`, true);
  const comic = edit.values;

  return (
    <EditModal
      isOpen={true}
      title={comic ? `Edit - ${edit.loaded.data?.title}` : 'Edit Comic'}
      isLoading={edit.loaded.isLoading}
      loadError={edit.loaded.error}
      error={edit.error}
      isSaving={edit.isSaving}
      isChanged={Object.keys(edit.edited).length > 0}
      onSave={() =>
        edit.save<{ id: string; message: string }>({}, (saved) => {
          onSaved(saved.id);
          onModalClose();
        })
      }
      onModalClose={onModalClose}
    >
      {comic ? (
        <>
          <EditField id="comicTitle" label="Title">
            <TextInput id="comicTitle" value={comic.title} onChange={(title) => edit.set('title', title)} />
          </EditField>
          <EditField id="comicId" label="ID" help="Its ComicVine id, which its issues are looked up by">
            <TextInput id="comicId" value={comic.id} onChange={(id) => edit.set('id', id)} />
          </EditField>
          {comic.id.trim() !== comicId ? (
            <Alert kind="warning">Its issues move to the new id. It has to be a comic ComicVine knows.</Alert>
          ) : null}
          <EditField id="comicAka" label="Also Known As" help="Other ids of it, separated by commas">
            <TextInput id="comicAka" value={comic.aka} onChange={(aka) => edit.set('aka', aka)} />
          </EditField>
          <EditField id="comicGenre" label="Genres" help="Separated by commas">
            <TextInput id="comicGenre" value={comic.genre} onChange={(genre) => edit.set('genre', genre)} />
          </EditField>
          <EditField id="comicDescription" label="Description">
            <TextArea
              id="comicDescription"
              rows={6}
              value={comic.description}
              onChange={(description) => edit.set('description', description)}
            />
          </EditField>
        </>
      ) : null}
    </EditModal>
  );
}

export default EditComicModal;
