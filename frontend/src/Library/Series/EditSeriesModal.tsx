// Sonarr's edit modal for a series: its name and its id at the info source, with its books in order
import { TextInput } from 'Components/Form/Form';
import { Alert } from 'Components/Misc';
import { EditField, EditModal, useEdit } from 'Library/Edit/edit';
import styles from 'Library/Edit/Edit.module.css';

interface SeriesEdit {
  id: string;
  name: string;
  reason: string;
  members: { number: string; title: string }[];
}

function EditSeriesModal({
  seriesId,
  onSaved,
  onModalClose,
}: {
  seriesId: string;
  // with its id now
  onSaved: (id: string) => void;
  onModalClose: () => void;
}) {
  const edit = useEdit<SeriesEdit>(`/library/series/${encodeURIComponent(seriesId)}/edit`, true);
  const series = edit.values;

  return (
    <EditModal
      isOpen={true}
      title={series ? `Edit - ${edit.loaded.data?.name}` : 'Edit Series'}
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
      {series ? (
        <>
          <EditField id="seriesName" label="Name">
            <TextInput id="seriesName" value={series.name} onChange={(name) => edit.set('name', name)} />
          </EditField>
          <EditField id="seriesId" label="ID" help="Its id at the info source, which its books are looked up by">
            <TextInput id="seriesId" value={series.id} onChange={(id) => edit.set('id', id)} />
          </EditField>
          {series.id.trim() !== seriesId ? (
            <Alert kind="warning">Its books and authors move to the new id.</Alert>
          ) : null}
          {series.reason ? <p className={styles.readonly}>Found from {series.reason}</p> : null}
          {series.members.length ? (
            <EditField label="Books">
              <ul className={styles.list}>
                {series.members.map((member) => (
                  <li key={`${member.number}-${member.title}`}>
                    {member.number ? `${member.number}. ` : ''}
                    {member.title}
                  </li>
                ))}
              </ul>
            </EditField>
          ) : null}
        </>
      ) : null}
    </EditModal>
  );
}

export default EditSeriesModal;
