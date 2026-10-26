// Sonarr's SelectSeriesModal, for books: find one in the library by its title or author
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { TextInput } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { ImportTarget, LibraryBook } from 'typings/InteractiveImport';
import { api } from 'Utilities/api';
import styles from '../InteractiveImport.module.css';

// how long typing has to stop for before the library is searched
const DEBOUNCE = 300;

interface SelectBookModalProps {
  isOpen: boolean;
  onBookSelect: (book: ImportTarget) => void;
  onModalClose: () => void;
}

function SelectBookModal({ isOpen, onBookSelect, onModalClose }: SelectBookModalProps) {
  const [term, setTerm] = useState('');
  const [search, setSearch] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(term.trim()), DEBOUNCE);
    return () => window.clearTimeout(timer);
  }, [term]);

  useEffect(() => {
    if (isOpen) {
      setTerm('');
    }
  }, [isOpen]);

  const { data, error, isFetching } = useQuery({
    queryKey: ['book', search],
    queryFn: () => api<LibraryBook[]>('/book', { query: { term: search } }),
    enabled: isOpen && search.length > 1,
  });

  return (
    <Modal isOpen={isOpen} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Manual Import - Select Book</ModalHeader>
        <ModalBody>
          <TextInput value={term} placeholder="Title or author" autoFocus={true} onChange={setTerm} />

          <div className={styles.books}>
            {isFetching ? <LoadingIndicator /> : null}
            {error ? <Alert kind="danger">{error.message}</Alert> : null}
            {search.length > 1 && data && !data.length ? (
              <Alert kind="info">No books in the library match {search}</Alert>
            ) : null}
            {data?.map((book) => (
              <Link
                key={book.id}
                className={styles.bookResult}
                onPress={() => onBookSelect({ id: book.id, title: book.title, author: book.author })}
              >
                <span className={styles.bookTitle}>{book.title}</span>
                <span className={styles.bookAuthor}>{book.author}</span>
              </Link>
            ))}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default SelectBookModal;
