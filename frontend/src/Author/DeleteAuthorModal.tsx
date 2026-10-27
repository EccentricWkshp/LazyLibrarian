// Sonarr's DeleteSeriesModal: take authors out of the library, their book folders too if asked
import { useState } from 'react';
import { CheckInput, FormInputHelpText, FormRow } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import styles from 'Library/Library.module.css';
import { deleteAuthors } from './authors';

interface DeleteAuthorModalProps {
  isOpen: boolean;
  authors: { id: string; name: string }[];
  onModalClose: () => void;
  onDeleted?: () => void;
}

function DeleteAuthorModal({ isOpen, authors, onModalClose, onDeleted }: DeleteAuthorModalProps) {
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const title = authors.length === 1 ? authors[0].name : `${authors.length} authors`;

  return (
    <Modal isOpen={isOpen} size="small" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Delete {title}</ModalHeader>
        <ModalBody>
          <FormRow>
            <label className={styles.check}>
              <CheckInput checked={deleteFiles} onChange={setDeleteFiles} />
              Delete their book files
            </label>
            <FormInputHelpText
              text={
                deleteFiles
                  ? 'The folders of their books in the library are deleted, with everything in them'
                  : "Their books stay in the library's folders, a library scan would find them again"
              }
              isWarning={deleteFiles}
            />
          </FormRow>
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button
            kind="danger"
            isSpinning={isDeleting}
            onPress={() => {
              setIsDeleting(true);
              deleteAuthors(
                authors.map((author) => author.id),
                deleteFiles
              ).then((result) => {
                setIsDeleting(false);
                onModalClose();
                if (result) {
                  onDeleted?.();
                }
              });
            }}
          >
            Delete
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default DeleteAuthorModal;
