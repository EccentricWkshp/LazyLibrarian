// Sonarr's AddNewSeriesModal: what to want of what's being added, and whether to search for it now.
// An author or a book is added by a command, it shows in the sidebar; a magazine or comic at once.
// It's made again for each thing added, by its key, so it starts from what that is
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { runCommand } from 'App/commands';
import queryClient from 'App/queryClient';
import { CheckInput, FormInputHelpText, FormLabel, FormRow, SelectInput, TextInput } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import { Alert } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { BookMediaType } from 'typings/AddNew';
import { api } from 'Utilities/api';
import styles from './AddNew.module.css';

export interface Adding {
  kind: 'author' | 'book' | 'magazine' | 'comic';
  id: string;
  name: string;
  source?: string;
  authorId?: string;
  rejectWords?: string;
  status?: string;
  audioStatus?: string;
}

const MONITOR = [
  { key: 'new', value: 'New books', hint: 'Their books are wanted as Settings says for a new author' },
  { key: 'all', value: 'All books', hint: 'Every book of theirs that the library has no file of is wanted' },
  { key: 'none', value: 'None', hint: "The author is paused, none of their books are wanted" },
];

const FORMATS: Record<BookMediaType, string> = { ebook: 'eBook', audiobook: 'Audiobook' };
const OWNED = ['Open', 'Have'];

interface AddModalProps {
  adding: Adding | null;
  mediaTypes: BookMediaType[];
  onModalClose: () => void;
}

// a book is wanted in one format, one the library doesn't have; an author's books in every one
function initialFormats(adding: Adding | null, mediaTypes: BookMediaType[]) {
  const owned = (format: BookMediaType) =>
    OWNED.includes((format === 'ebook' ? adding?.status : adding?.audioStatus) ?? '');
  const wantable = mediaTypes.filter((format) => !owned(format));

  return adding?.kind === 'book' && wantable.length ? wantable.slice(0, 1) : mediaTypes;
}

function changed() {
  queryClient.invalidateQueries({ queryKey: ['lookup'] });
  queryClient.invalidateQueries({ queryKey: ['wanted'] });
}

function AddModal({ adding, mediaTypes, onModalClose }: AddModalProps) {
  const [monitor, setMonitor] = useState('new');
  const [formats, setFormats] = useState<BookMediaType[]>(() => initialFormats(adding, mediaTypes));
  const [search, setSearch] = useState(false);
  const [rejectWords, setRejectWords] = useState(adding?.rejectWords ?? '');

  const addNow = useMutation({
    mutationFn: (item: Adding) =>
      item.kind === 'magazine'
        ? api('/magazine', { method: 'POST', body: { title: item.name, rejectWords, search } })
        : api('/comic', { method: 'POST', body: { id: item.id, search } }),
    onSuccess: () => {
      changed();
      onModalClose();
    },
  });

  if (!adding) {
    return null;
  }

  const item = adding;
  const isBook = item.kind === 'author' || item.kind === 'book';
  const showFormats = isBook && mediaTypes.length > 1 && (item.kind === 'book' || monitor === 'all' || search);

  function add() {
    if (item.kind === 'author') {
      runCommand(
        'AddAuthor',
        { authorId: item.id, authorName: item.name, monitor, mediaTypes: formats, search },
        `Adding ${item.name}`,
      ).then(changed);
      onModalClose();
    } else if (item.kind === 'book') {
      runCommand(
        'AddBook',
        { bookId: item.id, source: item.source, authorId: item.authorId, mediaTypes: formats, search },
        `Adding ${item.name}`,
      ).then(changed);
      onModalClose();
    } else {
      addNow.mutate(item);
    }
  }

  function toggleFormat(format: BookMediaType, on: boolean) {
    setFormats((current) => (on ? [...current, format] : current.filter((f) => f !== format)));
  }

  return (
    <Modal isOpen={true} size="small" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Add {item.name}</ModalHeader>
        <ModalBody>
          {item.kind === 'author' ? (
            <FormRow>
              <FormLabel htmlFor="monitor">Monitor</FormLabel>
              <SelectInput id="monitor" value={monitor} values={MONITOR} onChange={setMonitor} />
            </FormRow>
          ) : null}

          {showFormats ? (
            <FormRow>
              <FormLabel>{item.kind === 'author' ? 'Want Them As' : 'Want It As'}</FormLabel>
              <div className={styles.formats}>
                {mediaTypes.map((format) => (
                  <label key={format} className={styles.format}>
                    <CheckInput checked={formats.includes(format)} onChange={(on) => toggleFormat(format, on)} />
                    {FORMATS[format]}
                  </label>
                ))}
              </div>
            </FormRow>
          ) : null}

          {item.kind === 'magazine' ? (
            <FormRow>
              <FormLabel htmlFor="rejectWords">Reject Words</FormLabel>
              <FormInputHelpText text="A release with any of these words in its name isn't this magazine, separated by commas" />
              <TextInput id="rejectWords" value={rejectWords} onChange={setRejectWords} />
            </FormRow>
          ) : null}

          <FormRow>
            <label className={styles.format}>
              <CheckInput checked={search} onChange={setSearch} />
              {item.kind === 'author' ? 'Start search for the wanted books' : 'Start search for it'}
            </label>
          </FormRow>

          {item.kind === 'author' ? (
            <FormInputHelpText text="Adding an author fetches all their books, which can take a few minutes. The sidebar shows how it's going." />
          ) : null}
          {addNow.error ? <Alert kind="danger">{(addNow.error as Error).message}</Alert> : null}
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button
            kind="success"
            isDisabled={isBook && !formats.length}
            isSpinning={addNow.isPending}
            onPress={add}
          >
            Add {item.kind === 'author' ? 'Author' : item.kind === 'book' ? 'Book' : item.kind === 'magazine' ? 'Magazine' : 'Comic'}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default AddModal;
