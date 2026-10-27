// SelectBookModal for a magazine or comic issue: find the magazine or comic in the library by its
// title, and say which issue
import { useQuery } from '@tanstack/react-query';
import classNames from 'classnames';
import { useEffect, useState } from 'react';
import { FormInputHelpText, FormLabel, FormRow, TextInput } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { ImportTarget } from 'typings/InteractiveImport';
import { api } from 'Utilities/api';
import styles from '../InteractiveImport.module.css';

// how long typing has to stop for before the library is searched
const DEBOUNCE = 300;

export type Periodical = 'magazine' | 'comic';

interface Title extends ImportTarget {
  dateType: string;
}

interface SelectIssueModalProps {
  isOpen: boolean;
  mediaType: Periodical;
  // the title and issue to start from, when one item is being chosen for
  initial?: ImportTarget | null;
  issue?: string;
  // several items are being chosen for, each keeps the issue its name says unless one is given
  isMany?: boolean;
  onIssueSelect: (target: ImportTarget, issue: string) => void;
  onModalClose: () => void;
}

function SelectIssueModal({
  isOpen,
  mediaType,
  initial,
  issue: initialIssue = '',
  isMany = false,
  onIssueSelect,
  onModalClose,
}: SelectIssueModalProps) {
  const [term, setTerm] = useState('');
  const [search, setSearch] = useState('');
  const [chosen, setChosen] = useState<ImportTarget | null>(null);
  const [issue, setIssue] = useState('');
  const noun = mediaType === 'magazine' ? 'Magazine' : 'Comic';

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(term.trim()), DEBOUNCE);
    return () => window.clearTimeout(timer);
  }, [term]);

  // what to start from is taken as it opens, not again as the page around it changes
  useEffect(() => {
    if (isOpen) {
      setTerm(initial?.title ?? '');
      setChosen(initial ?? null);
      setIssue(initialIssue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const { data, error, isFetching } = useQuery({
    queryKey: ['manualimport', 'titles', mediaType, search],
    queryFn: () => api<Title[]>('/manualimport/titles', { query: { mediaType, term: search } }),
    enabled: isOpen && search.length > 1,
  });
  const dateType = data?.find((title) => title.id === chosen?.id)?.dateType;

  return (
    <Modal isOpen={isOpen} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Manual Import - Select {noun}</ModalHeader>
        <ModalBody>
          <TextInput value={term} placeholder="Title" autoFocus={true} onChange={setTerm} />

          <div className={styles.books}>
            {isFetching ? <LoadingIndicator /> : null}
            {error ? <Alert kind="danger">{error.message}</Alert> : null}
            {search.length > 1 && data && !data.length ? (
              <Alert kind="info">
                No {noun.toLowerCase()}s in the library match {search}
              </Alert>
            ) : null}
            {data?.map((title) => (
              <Link
                key={title.id}
                className={classNames(styles.bookResult, chosen?.id === title.id && styles.chosenResult)}
                onPress={() => setChosen({ id: title.id, title: title.title, author: '', mediaType })}
              >
                <span className={styles.bookTitle}>{title.title}</span>
                {title.dateType ? <span className={styles.bookAuthor}>Issues by {title.dateType}</span> : null}
              </Link>
            ))}
          </div>

          <FormRow>
            <FormLabel htmlFor="manualImportIssue">{mediaType === 'magazine' ? 'Issue date or number' : 'Issue number'}</FormLabel>
            <div>
              <TextInput
                id="manualImportIssue"
                value={issue}
                placeholder={mediaType === 'magazine' ? 'eg 2024-05-01, May 2024 or 123' : 'eg 12'}
                onChange={setIssue}
              />
              {isMany ? <FormInputHelpText text="Leave it empty for each file to keep the issue its name says" /> : null}
              {dateType ? <FormInputHelpText text={`${chosen?.title} is dated by ${dateType}`} /> : null}
            </div>
          </FormRow>
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button
            kind="primary"
            isDisabled={!chosen || (!isMany && !issue.trim())}
            onPress={() => chosen && onIssueSelect(chosen, issue.trim())}
          >
            Choose
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default SelectIssueModal;
