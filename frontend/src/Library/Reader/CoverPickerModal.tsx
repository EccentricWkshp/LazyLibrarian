// Choosing an issue's cover by looking at its pages: a page clicked is made its cover, for a magazine
// issue or a comic issue (comicid_issueid)
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import Button from 'Components/Link/Button';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { api } from 'Utilities/api';
import { pageUrl } from './reading';
import styles from './CoverPicker.module.css';

// pages shown at a time
const BATCH = 12;

interface CoverPickerProps {
  kind: 'issue' | 'comic';
  id: string;
  name: string;
  current?: number;
  onModalClose: () => void;
}

function CoverPickerModal({ kind, id, name, current, onModalClose }: CoverPickerProps) {
  const [shown, setShown] = useState(BATCH);
  const { data, error, isLoading } = useQuery({
    queryKey: ['read', kind, id, ''],
    queryFn: () => api<{ pages: number }>(`/read/${kind}/${encodeURIComponent(id)}`),
    retry: false,
  });
  const choose = useMutation({
    mutationFn: (page: number) => {
      const [comicId, issueId] = id.split('_');
      const path =
        kind === 'comic'
          ? `/library/comic/${encodeURIComponent(comicId)}/issue/${encodeURIComponent(issueId)}/cover`
          : `/library/magazine/issue/${encodeURIComponent(id)}/cover`;
      return api<{ message: string }>(path, { method: 'PUT', body: { page } });
    },
    onSuccess: (result) => {
      showMessage({ id: `cover-${id}`, text: `${name}: ${result.message}`, kind: 'success', isWorking: false });
      queryClient.invalidateQueries({ queryKey: ['library'] });
      onModalClose();
    },
  });
  const pages = data?.pages ?? 0;

  return (
    <Modal isOpen={true} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Choose the Cover - {name}</ModalHeader>
        <ModalBody>
          {isLoading ? <LoadingIndicator /> : null}
          {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
          {data && !pages ? <Alert kind="info">Its pages can't be shown, it isn't a PDF or comic archive.</Alert> : null}
          {choose.error ? <Alert kind="danger">{(choose.error as Error).message}</Alert> : null}
          <div className={styles.pages}>
            {Array.from({ length: Math.min(shown, pages) }, (_, index) => index + 1).map((page) => (
              <button
                key={page}
                type="button"
                className={page === current ? styles.chosen : styles.page}
                disabled={choose.isPending}
                onClick={() => choose.mutate(page)}
              >
                <img src={pageUrl(kind, id, page, 240)} alt={`Page ${page}`} loading="lazy" />
                <span>Page {page}</span>
              </button>
            ))}
          </div>
        </ModalBody>
        <ModalFooter>
          {shown < pages ? <Button onPress={() => setShown(shown + BATCH)}>More Pages</Button> : null}
          <Button onPress={onModalClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default CoverPickerModal;
