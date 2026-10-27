// Sonarr's edit modal for a magazine: its title, and how its releases are searched for and its
// issues read, which were the old Settings page's per-magazine filters
import { useQuery } from '@tanstack/react-query';
import { SelectInput, TextInput } from 'Components/Form/Form';
import { Alert } from 'Components/Misc';
import { EditColumns, EditField, EditModal, useEdit } from 'Library/Edit/edit';
import { ConfigChoices } from 'Settings/Sections/fields';
import { api } from 'Utilities/api';

interface MagazineEdit {
  title: string;
  reject: string;
  regex: string;
  genre: string;
  dateType: string;
  coverPage: number;
  language: string;
}

function EditMagazineModal({
  title,
  onSaved,
  onModalClose,
}: {
  title: string;
  // with its title now
  onSaved: (title: string) => void;
  onModalClose: () => void;
}) {
  const edit = useEdit<MagazineEdit>(`/library/magazine/edit?title=${encodeURIComponent(title)}`, true);
  const choices = useQuery({
    queryKey: ['config', 'choices'],
    queryFn: () => api<ConfigChoices>('/config/choices'),
  });
  const magazine = edit.values;
  const isRenamed = !!magazine && magazine.title.trim() !== title;
  const languages = (choices.data?.magazineLanguages ?? []).map((language) => ({
    key: language.value,
    value: language.label,
  }));

  return (
    <EditModal
      isOpen={true}
      title={`Edit - ${title}`}
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
      {magazine ? (
        <>
          <EditField id="magTitle" label="Title">
            <TextInput id="magTitle" value={magazine.title} onChange={(value) => edit.set('title', value)} />
          </EditField>
          {isRenamed ? (
            <Alert kind="warning">Renaming it moves its issue files to match the new title. It can take a while.</Alert>
          ) : null}
          <EditField
            id="magRegex"
            label="Search For"
            help="What's searched for instead of its title, when releases name it differently"
          >
            <TextInput id="magRegex" value={magazine.regex} onChange={(regex) => edit.set('regex', regex)} />
          </EditField>
          <EditField
            id="magReject"
            label="Must Not Contain"
            help="Words that rule a release out, separated by commas. See Settings, Filters for all magazines"
          >
            <TextInput id="magReject" value={magazine.reject} onChange={(reject) => edit.set('reject', reject)} />
          </EditField>
          <EditField id="magGenre" label="Genres" help="Separated by commas, written into each issue's opf file">
            <TextInput id="magGenre" value={magazine.genre} onChange={(genre) => edit.set('genre', genre)} />
          </EditField>
          <EditColumns>
            <EditField
              id="magDateType"
              label="Issue Dates"
              help="Empty to tell. Or what its issues are named by: Y year, M month, D day, V volume, I issue, MM two months, like YM or VI"
            >
              <TextInput
                id="magDateType"
                placeholder="Automatic"
                value={magazine.dateType}
                onChange={(dateType) => edit.set('dateType', dateType.toUpperCase())}
              />
            </EditField>
            <EditField id="magCover" label="Cover Page" help="The page its covers are made from">
              <TextInput
                id="magCover"
                type="number"
                min={1}
                value={String(magazine.coverPage)}
                onChange={(page) => edit.set('coverPage', Math.max(1, Number(page) || 1))}
              />
            </EditField>
          </EditColumns>
          <EditField id="magLanguage" label="Language" help="Written into each issue's opf file and pdf">
            <SelectInput
              id="magLanguage"
              value={magazine.language}
              values={
                languages.some((language) => language.key === magazine.language)
                  ? languages
                  : [{ key: magazine.language, value: magazine.language }, ...languages]
              }
              onChange={(language) => edit.set('language', language)}
            />
          </EditField>
        </>
      ) : null}
    </EditModal>
  );
}

export default EditMagazineModal;
