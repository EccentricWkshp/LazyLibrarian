// Sonarr's edit modal for a magazine issue: the magazine it's an issue of, its date or number, and
// the tags of its pdf
import { TextInput } from 'Components/Form/Form';
import { EditField, EditModal, useEdit } from 'Library/Edit/edit';
import styles from 'Library/Edit/Edit.module.css';

interface IssueEdit {
  id: string;
  title: string;
  issueDate: string;
  file: string;
  tags: { name: string; value: string }[];
}

function EditIssueModal({
  issueId,
  onSaved,
  onModalClose,
}: {
  issueId: string;
  // with the magazine to show now
  onSaved: (title: string) => void;
  onModalClose: () => void;
}) {
  const edit = useEdit<IssueEdit>(`/library/magazine/issue/${encodeURIComponent(issueId)}/edit`, true);
  const issue = edit.values;

  return (
    <EditModal
      isOpen={true}
      title={issue ? `Edit - ${edit.loaded.data?.title} ${edit.loaded.data?.issueDate}` : 'Edit Issue'}
      isLoading={edit.loaded.isLoading}
      loadError={edit.loaded.error}
      error={edit.error}
      isSaving={edit.isSaving}
      isChanged={Object.keys(edit.edited).length > 0}
      onSave={() =>
        edit.save<{ title: string; message: string }>({}, (saved) => {
          onSaved(saved.title);
          onModalClose();
        })
      }
      onModalClose={onModalClose}
    >
      {issue ? (
        <>
          <EditField
            id="issueTitle"
            label="Magazine"
            help="Another title moves the issue to that magazine, which is added if it's new"
          >
            <TextInput id="issueTitle" value={issue.title} onChange={(title) => edit.set('title', title)} />
          </EditField>
          <EditField
            id="issueDate"
            label="Issue Date or Number"
            help="Its file is renamed to match. It has to fit the magazine's Issue Dates"
          >
            <TextInput id="issueDate" value={issue.issueDate} onChange={(issueDate) => edit.set('issueDate', issueDate)} />
          </EditField>
          {issue.tags.length ? (
            <EditField label="PDF Tags">
              <div className={styles.rows}>
                {issue.tags.map((tag, index) => (
                  <EditField key={tag.name} id={`tag-${index}`} label={tag.name.replace(/^\//, '')}>
                    <TextInput
                      id={`tag-${index}`}
                      value={tag.value}
                      onChange={(value) =>
                        edit.set(
                          'tags',
                          issue.tags.map((t, i) => (i === index ? { ...t, value } : t))
                        )
                      }
                    />
                  </EditField>
                ))}
              </div>
            </EditField>
          ) : null}
          {issue.file ? <p className={styles.readonly}>{issue.file}</p> : null}
        </>
      ) : null}
    </EditModal>
  );
}

export default EditIssueModal;
