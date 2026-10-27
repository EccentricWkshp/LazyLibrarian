// The authors that were added only for contributing to a book, before nobody was: what merging and
// removing them does, and doing it
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import Button from 'Components/Link/Button';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import styles from 'Library/Library.module.css';
import { api } from 'Utilities/api';
import { removeContributorAuthors } from './authors';

interface Contributors {
  merge: { id: string; name: string; intoId: string; intoName: string }[];
  remove: { id: string; name: string; reason: string }[];
}

interface ContributorAuthorsModalProps {
  isOpen: boolean;
  onModalClose: () => void;
}

function ContributorAuthorsModal({ isOpen, onModalClose }: ContributorAuthorsModalProps) {
  const [isRemoving, setIsRemoving] = useState(false);
  const { data, error, isLoading } = useQuery({
    queryKey: ['author', 'contributors'],
    queryFn: () => api<Contributors>('/author/contributors'),
    enabled: isOpen,
  });
  const nothing = data && !data.merge.length && !data.remove.length;

  return (
    <Modal isOpen={isOpen} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Contributor Authors</ModalHeader>
        <ModalBody>
          <p>
            Authors used to be added for contributing to a book, so an anthology brought in every one of its authors.
            Now a book is only linked to its other authors that are in the library already. These are the ones added
            that way. Their books stay, under their main authors.
          </p>
          {isLoading ? <LoadingIndicator /> : null}
          {error ? <Alert kind="danger">{error.message}</Alert> : null}
          {nothing ? <Alert kind="info">There are none to merge or remove</Alert> : null}

          {data?.merge.length ? (
            <>
              <h3>Merged into the author they are ({data.merge.length})</h3>
              <ul className={styles.contributorList}>
                {data.merge.map((merge) => (
                  <li key={merge.id}>
                    {merge.name} into {merge.intoName}
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {data?.remove.length ? (
            <>
              <h3>Removed, with none of their books in the library ({data.remove.length})</h3>
              <ul className={styles.contributorList}>
                {data.remove.map((author) => (
                  <li key={author.id} title={author.reason}>
                    {author.name} <span className={styles.muted}>{author.reason}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button
            kind="danger"
            isDisabled={!data || nothing}
            isSpinning={isRemoving}
            onPress={() => {
              setIsRemoving(true);
              removeContributorAuthors().then(() => {
                setIsRemoving(false);
                onModalClose();
              });
            }}
          >
            Merge and Remove
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default ContributorAuthorsModal;
