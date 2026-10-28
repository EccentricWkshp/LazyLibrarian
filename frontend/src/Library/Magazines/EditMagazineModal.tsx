// Sonarr's edit modal for a magazine: its title, and how its releases are searched for and its
// issues read, which were the old Settings page's per-magazine filters
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { SelectInput, TextInput } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import { Alert } from 'Components/Misc';
import { EditColumns, EditField, EditModal, useEdit } from 'Library/Edit/edit';
import styles from 'Library/Edit/Edit.module.css';
import ProfileField from 'Library/Edit/ProfileField';
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
  wikidataId: string;
  keepIssues: number;
  keepMonths: number;
  profileId: number;
  // how its issues are known when it's chosen, '' to work it out, which numberingFound says
  numbering: string;
  numberingFound: string;
}

const FOUND_NAMES: Record<string, string> = { date: 'dates', number: 'numbers', year: 'years' };

// how a magazine's issues are known: its key for each, which its releases are read into
function numberings(found: string) {
  return [
    { key: '', value: `Work it out from its issues${FOUND_NAMES[found] ? ` (now ${FOUND_NAMES[found]})` : ''}` },
    { key: 'date', value: 'Date', hint: 'Its issues are known by the month or day they came out: 2026-03-01' },
    {
      key: 'running',
      value: 'Running number',
      hint: 'A number that runs on from issue to issue, whatever the year: Make Volume 98 is 0098',
    },
    {
      key: 'yearly',
      value: 'Number within the year',
      hint: 'A number that starts again each year, kept with its year: No 5 of 2025 is 20250005',
    },
    { key: 'volume', value: 'Volume and number', hint: 'A volume and a number in it: Vol 45 No 5 is 00450005' },
    { key: 'year', value: 'Year, an annual', hint: 'One issue a year, known by the year: 2026' },
  ];
}

interface WikidataMatch {
  id: string;
  label: string;
  description: string;
  started: string;
}

// the periodical on Wikidata its description, publisher and how often it comes out are taken from,
// found by its title or other words
function WikidataField({ title, value, onChange }: { title: string; value: string; onChange: (id: string) => void }) {
  const [term, setTerm] = useState('');
  const [asked, setAsked] = useState<string | null>(null);
  const found = useQuery({
    queryKey: ['library', 'wikidata', title, asked],
    queryFn: () => api<WikidataMatch[]>('/library/magazine/wikidata', { query: { title, term: asked ?? '' } }),
    enabled: asked !== null,
    retry: false,
  });
  const matches = found.data ?? [];
  const options = [
    { key: '', value: 'Not linked' },
    ...(value && !matches.some((match) => match.id === value) ? [{ key: value, value: `${value}, as it is` }] : []),
    ...matches.map((match) => ({
      key: match.id,
      value: [match.label, match.started ? `(${match.started})` : '', match.description ? `- ${match.description}` : '']
        .filter(Boolean)
        .join(' '),
    })),
  ];

  return (
    <EditField
      id="magWikidata"
      label="Wikidata"
      help="The periodical its description, publisher and how often it comes out are taken from. Saving takes them again"
    >
      <SelectInput id="magWikidata" value={value} values={options} onChange={onChange} />
      <div className={styles.wikidataSearch}>
        <TextInput value={term} placeholder={title} onChange={setTerm} aria-label="Look up on Wikidata" />
        <Button isSpinning={found.isFetching} onPress={() => setAsked(term.trim())}>
          Find on Wikidata
        </Button>
      </div>
      {found.error ? <Alert kind="danger">{(found.error as Error).message}</Alert> : null}
      {found.data && !matches.length ? <Alert kind="info">Wikidata has no periodical called that.</Alert> : null}
    </EditField>
  );
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
          <EditField
            id="magNumbering"
            label="Issues Are Known By"
            help="How its releases' names are read into its issues. Choosing one renumbers the issues there are and renames their files to match"
          >
            <SelectInput
              id="magNumbering"
              value={magazine.numbering}
              values={numberings(magazine.numberingFound)}
              onChange={(numbering) => edit.set('numbering', numbering)}
            />
          </EditField>
          {magazine.numbering && edit.edited.numbering !== undefined && edit.edited.numbering !== edit.loaded.data?.numbering ? (
            <Alert kind="warning">
              Its issues are renumbered and their files renamed when it's saved. An issue whose new number is
              another's is left as it is.
            </Alert>
          ) : null}
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
            <EditField
              id="magCover"
              label="Cover Page"
              help="The page its covers are made from. Changing it makes its issues' covers again"
            >
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
          <ProfileField
            mediaType="magazine"
            value={magazine.profileId}
            onChange={(profileId) => edit.set('profileId', profileId)}
          />
          <EditColumns>
            <EditField
              id="magKeepIssues"
              label="Keep Issues"
              help="Its newest issues kept, older ones and their files are deleted. 0 keeps them all"
            >
              <TextInput
                id="magKeepIssues"
                type="number"
                min={0}
                value={String(magazine.keepIssues)}
                onChange={(keep) => edit.set('keepIssues', Math.max(0, Number(keep) || 0))}
              />
            </EditField>
            <EditField
              id="magKeepMonths"
              label="Keep Months"
              help="The issues of this many months kept, older ones and their files are deleted. 0 keeps them all"
            >
              <TextInput
                id="magKeepMonths"
                type="number"
                min={0}
                value={String(magazine.keepMonths)}
                onChange={(keep) => edit.set('keepMonths', Math.max(0, Number(keep) || 0))}
              />
            </EditField>
          </EditColumns>
          {magazine.keepIssues || magazine.keepMonths ? (
            <Alert kind="warning">Saving deletes the issues it doesn't keep, and their files.</Alert>
          ) : null}
          <WikidataField
            title={title}
            value={magazine.wikidataId}
            onChange={(wikidataId) => edit.set('wikidataId', wikidataId)}
          />
        </>
      ) : null}
    </EditModal>
  );
}

export default EditMagazineModal;
