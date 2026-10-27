// Sonarr's edit modal for a book: its details, author and series, its cover, the fields of its opf
// file, and importing its files from a folder
import { Plus, X } from 'lucide-react';
import { CheckInput, SelectInput, TextArea, TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import { Label } from 'Components/Misc';
import { EditColumns, EditField, EditModal, PictureChoices, useEdit } from 'Library/Edit/edit';
import styles from 'Library/Edit/Edit.module.css';

interface NamedValue {
  name: string;
  value: string;
}

interface SeriesEntry {
  name: string;
  number: string;
}

interface BookEdit {
  id: string;
  title: string;
  subtitle: string;
  author: string;
  genre: string;
  language: string;
  releaseDate: string;
  isbn: string;
  workId: string;
  narrator: string;
  description: string;
  locked: boolean;
  addedBy: string;
  image: string;
  sourceIds: Record<string, string>;
  series: SeriesEntry[];
  authorSeries: string[];
  authors: string[];
  opfFields: NamedValue[];
  // a cover found, by its source
  cover: string;
  importFrom: string;
}

function EditBookModal({
  bookId,
  showNarrator,
  onModalClose,
}: {
  bookId: string;
  showNarrator: boolean;
  onModalClose: () => void;
}) {
  const edit = useEdit<BookEdit>(`/library/book/${encodeURIComponent(bookId)}/edit`, true);
  const book = edit.values;

  function setSeries(series: SeriesEntry[]) {
    edit.set('series', series);
  }

  return (
    <EditModal
      isOpen={true}
      title={book ? `Edit - ${book.title}` : 'Edit Book'}
      isLoading={edit.loaded.isLoading}
      loadError={edit.loaded.error}
      error={edit.error}
      isSaving={edit.isSaving}
      isChanged={Object.keys(edit.edited).length > 0}
      onSave={() => edit.save({}, onModalClose)}
      onModalClose={onModalClose}
    >
      {book ? (
        <>
          <EditField id="bookTitle" label="Title">
            <TextInput id="bookTitle" value={book.title} onChange={(title) => edit.set('title', title)} />
          </EditField>
          <EditField id="bookSubtitle" label="Subtitle">
            <TextInput id="bookSubtitle" value={book.subtitle} onChange={(subtitle) => edit.set('subtitle', subtitle)} />
          </EditField>
          <EditField id="bookAuthor" label="Author" help="Moving it to another author takes it off this one">
            <SelectInput
              id="bookAuthor"
              value={book.author}
              values={[...new Set([book.author, ...book.authors])].map((name) => ({ key: name, value: name }))}
              onChange={(author) => edit.set('author', author)}
            />
          </EditField>
          <EditColumns>
            <EditField id="bookDate" label="Released" help="A year, year-month or year-month-day">
              <TextInput
                id="bookDate"
                value={book.releaseDate}
                onChange={(releaseDate) => edit.set('releaseDate', releaseDate)}
              />
            </EditField>
            <EditField id="bookLanguage" label="Language">
              <TextInput id="bookLanguage" value={book.language} onChange={(language) => edit.set('language', language)} />
            </EditField>
            <EditField id="bookIsbn" label="ISBN">
              <TextInput id="bookIsbn" value={book.isbn} onChange={(isbn) => edit.set('isbn', isbn)} />
            </EditField>
            <EditField id="bookWork" label="Work ID">
              <TextInput id="bookWork" value={book.workId} onChange={(workId) => edit.set('workId', workId)} />
            </EditField>
          </EditColumns>
          <EditField id="bookGenre" label="Genres" help="Separated by commas">
            <TextInput id="bookGenre" value={book.genre} onChange={(genre) => edit.set('genre', genre)} />
          </EditField>
          {showNarrator ? (
            <EditField id="bookNarrator" label="Narrator">
              <TextInput id="bookNarrator" value={book.narrator} onChange={(narrator) => edit.set('narrator', narrator)} />
            </EditField>
          ) : null}

          <EditField
            label="Series"
            help="A series of its author's, or another LazyLibrarian has. One without a number is taken out"
          >
            <datalist id="authorSeries">
              {book.authorSeries.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <div className={styles.rows}>
              {book.series.map((entry, index) => (
                <div key={index} className={styles.row}>
                  <TextInput
                    aria-label="Series"
                    list="authorSeries"
                    value={entry.name}
                    onChange={(name) => setSeries(book.series.map((s, i) => (i === index ? { ...s, name } : s)))}
                  />
                  <TextInput
                    aria-label="Number"
                    className={styles.number}
                    placeholder="Number"
                    value={entry.number}
                    onChange={(number) => setSeries(book.series.map((s, i) => (i === index ? { ...s, number } : s)))}
                  />
                  <IconButton
                    name={X}
                    title="Take it out of the series"
                    onPress={() => setSeries(book.series.filter((_s, i) => i !== index))}
                  />
                </div>
              ))}
              <div>
                <Button onPress={() => setSeries([...book.series, { name: book.authorSeries[0] ?? '', number: '' }])}>
                  <Icon name={Plus} /> Add to a Series
                </Button>
              </div>
            </div>
          </EditField>

          <EditField id="bookDescription" label="Description">
            <TextArea
              id="bookDescription"
              rows={6}
              value={book.description}
              onChange={(description) => edit.set('description', description)}
            />
          </EditField>

          <EditField label="Cover" help="Choose one found online, or keep it">
            <PictureChoices<{ source: string; path: string }>
              url={`/library/book/${encodeURIComponent(bookId)}/covers`}
              label="cover"
              current={book.image}
              selected={book.cover ?? ''}
              name={(choice) => choice.source}
              onSelect={(choice) => edit.set('cover', choice && choice.source !== 'current' ? choice.source : '')}
            />
          </EditField>

          {book.opfFields.length ? (
            <EditField label="OPF Fields" help="The other fields of its opf file">
              <div className={styles.rows}>
                {book.opfFields.map((field, index) => (
                  <EditField key={field.name} id={`opf-${index}`} label={field.name}>
                    <TextInput
                      id={`opf-${index}`}
                      value={field.value}
                      onChange={(value) =>
                        edit.set(
                          'opfFields',
                          book.opfFields.map((f, i) => (i === index ? { ...f, value } : f))
                        )
                      }
                    />
                  </EditField>
                ))}
              </div>
            </EditField>
          ) : null}

          <EditField
            id="bookImport"
            label="Import Files From"
            help="A folder or file of this book's, imported into the library when it's saved"
          >
            <TextInput
              id="bookImport"
              value={book.importFrom ?? ''}
              onChange={(importFrom) => edit.set('importFrom', importFrom)}
            />
          </EditField>

          <label className={styles.check}>
            <CheckInput checked={book.locked} label="Lock" onChange={(locked) => edit.set('locked', locked)} />
            <span>Lock: a refresh doesn't change what's set here</span>
          </label>
          <p className={styles.readonly}>
            {Object.entries(book.sourceIds)
              .filter(([, id]) => id)
              .map(([source, id]) => (
                <span key={source}>
                  <Label>{source}</Label> {id}{' '}
                </span>
              ))}
          </p>
          {book.addedBy ? <p className={styles.readonly}>Added {book.addedBy}</p> : null}
        </>
      ) : null}
    </EditModal>
  );
}

export default EditBookModal;
