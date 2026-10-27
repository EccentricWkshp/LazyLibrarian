// Sonarr's InteractiveSearch: every release the providers have, the reasons the automatic search
// would turn each down, and grabbing one anyway
import { useMutation, useQuery } from '@tanstack/react-query';
import { CircleAlert, CircleCheck, Download } from 'lucide-react';
import { useState } from 'react';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import Icon from 'Components/Icon';
import IconButton from 'Components/Link/IconButton';
import { Alert, Label, LoadingIndicator, Popover } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import Button from 'Components/Link/Button';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { ProtocolLabel } from 'Activity/Queue/QueueRow';
import { MEDIA_TYPE_NAMES, MediaType } from 'typings/Queue';
import { Release } from 'typings/Wanted';
import { api } from 'Utilities/api';
import { formatBytes } from 'Utilities/format';
import styles from './InteractiveSearch.module.css';

const COLUMNS: Column[] = [
  { name: 'protocol', label: 'Source' },
  { name: 'title', label: 'Title' },
  { name: 'indexer', label: 'Indexer' },
  { name: 'size', label: 'Size' },
  { name: 'peers', label: 'Peers' },
  { name: 'quality', label: 'Quality' },
  { name: 'score', label: 'Score' },
  { name: 'rejections', label: 'Rejections', isVisuallyHidden: true },
  { name: 'download', label: 'Download', isVisuallyHidden: true },
];

function ReleaseRow({ release }: { release: Release }) {
  const [isConfirming, setIsConfirming] = useState(false);
  const grab = useMutation({
    mutationFn: () => api<{ message: string }>('/release', { method: 'POST', body: { id: release.id } }),
    onSuccess: (result) => {
      showMessage({ id: `grab-${release.id}`, text: result.message, kind: 'success', isWorking: false });
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
    },
  });

  function handleDownload() {
    // like Sonarr, a rejected release can be grabbed, after saying so
    if (!release.approved && !isConfirming) {
      setIsConfirming(true);
      return;
    }
    setIsConfirming(false);
    grab.mutate();
  }

  return (
    <TableRow>
      <TableRowCell>
        <ProtocolLabel protocol={release.protocol} />
      </TableRowCell>
      <TableRowCell className={styles.title}>{release.title}</TableRowCell>
      <TableRowCell>{release.indexer}</TableRowCell>
      <TableRowCell className={styles.nowrap}>{formatBytes(release.size)}</TableRowCell>
      <TableRowCell>{release.seeders >= 0 ? release.seeders : ''}</TableRowCell>
      <TableRowCell>
        <Label>{release.quality}</Label>
      </TableRowCell>
      <TableRowCell className={release.approved ? styles.good : styles.poor}>{release.score}</TableRowCell>
      <TableRowCell className={styles.rejections}>
        {release.rejections.length ? (
          <Popover
            anchor={<Icon name={CircleAlert} kind="danger" />}
            title="Release Rejected"
            body={
              <ul>
                {release.rejections.map((rejection) => (
                  <li key={rejection}>{rejection}</li>
                ))}
              </ul>
            }
          />
        ) : null}
      </TableRowCell>
      <TableRowCell className={styles.download}>
        {grab.isSuccess ? (
          <Icon name={CircleCheck} kind="success" title={grab.data.message} />
        ) : (
          <IconButton
            name={Download}
            kind={grab.isError ? 'danger' : release.approved ? 'default' : 'warning'}
            title={grab.isError ? grab.error.message : release.approved ? 'Add to download queue' : 'Download anyway'}
            isSpinning={grab.isPending}
            onPress={handleDownload}
          />
        )}
        {isConfirming ? (
          <div className={styles.confirm}>
            The automatic search would reject this.{' '}
            <Button kind="warning" onPress={handleDownload}>
              Download anyway
            </Button>
          </div>
        ) : null}
        {grab.isError ? <div className={styles.error}>{grab.error.message}</div> : null}
      </TableRowCell>
    </TableRow>
  );
}

interface InteractiveSearchModalProps {
  isOpen: boolean;
  bookId: string;
  mediaType: MediaType;
  title: string;
  onModalClose: () => void;
}

export function InteractiveSearchModal({ isOpen, bookId, mediaType, title, onModalClose }: InteractiveSearchModalProps) {
  return (
    <Modal isOpen={isOpen} size="extraExtraLarge" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>
          Interactive Search - {title} ({MEDIA_TYPE_NAMES[mediaType]})
        </ModalHeader>
        <ModalBody>
          <InteractiveSearch bookId={bookId} mediaType={mediaType} />
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Close</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

function InteractiveSearch({ bookId, mediaType }: { bookId: string; mediaType: MediaType }) {
  const { data, error, isFetching } = useQuery({
    queryKey: ['release', bookId, mediaType],
    queryFn: () => api<Release[]>('/release', { query: { bookId, mediaType } }),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });

  if (isFetching) {
    return (
      <div>
        <LoadingIndicator />
        <p className={styles.searching}>Searching the providers, this can take a while</p>
      </div>
    );
  }

  if (error) {
    return <Alert kind="danger">{error.message}</Alert>;
  }

  if (!data?.length) {
    return <Alert kind="info">No results found</Alert>;
  }

  const approved = data.filter((release) => release.approved).length;

  return (
    <>
      <p className={styles.summary}>
        {data.length} {data.length === 1 ? 'release' : 'releases'}, {approved} the automatic search would take.
        Hover the red icon to see why one would be rejected.
      </p>
      <Table columns={COLUMNS}>
        {data.map((release) => (
          <ReleaseRow key={release.id} release={release} />
        ))}
      </Table>
    </>
  );
}

export default InteractiveSearch;
