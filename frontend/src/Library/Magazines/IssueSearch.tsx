// Sonarr's Interactive Search for an episode, for a magazine's issue: every release the providers have
// for the magazine, the issue each one is, the ones of the issue searched for first, the reasons the
// magazine search would turn each down, and grabbing one anyway. One that doesn't say its issue is
// filed under the one searched for
import { useMutation, useQuery } from '@tanstack/react-query';
import { CircleAlert, CircleCheck, Download } from 'lucide-react';
import { useState } from 'react';
import { ProtocolLabel } from 'Activity/Queue/QueueRow';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import { Alert, Label, LoadingIndicator, Popover } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import styles from 'InteractiveSearch/InteractiveSearch.module.css';
import { IssueRelease } from 'typings/Wanted';
import { api } from 'Utilities/api';
import { useDates } from 'Utilities/dates';
import { formatBytes } from 'Utilities/format';

const COLUMNS: Column[] = [
  { name: 'protocol', label: 'Source' },
  { name: 'title', label: 'Title' },
  { name: 'issue', label: 'Issue' },
  { name: 'indexer', label: 'Indexer' },
  { name: 'posted', label: 'Posted' },
  { name: 'size', label: 'Size' },
  { name: 'quality', label: 'Quality' },
  { name: 'rejections', label: 'Rejections', isVisuallyHidden: true },
  { name: 'download', label: 'Download', isVisuallyHidden: true },
];

function IssueReleaseRow({ release, title, issue }: { release: IssueRelease; title: string; issue: string }) {
  const dates = useDates();
  const [isConfirming, setIsConfirming] = useState(false);
  // one that doesn't say its issue is the one searched for
  const fileUnder = release.issue ? '' : issue;
  const grab = useMutation({
    mutationFn: () => api<{ message: string }>('/release', { method: 'POST', body: { id: release.id, issue: fileUnder } }),
    onSuccess: (result) => {
      showMessage({ id: `grab-${release.id}`, text: result.message, kind: 'success', isWorking: false });
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['library', 'magazine', title] });
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
      <TableRowCell className={release.matches ? styles.good : styles.nowrap}>
        {release.issue ? dates.issue(release.issue) : fileUnder ? `As ${dates.issue(fileUnder)}` : ''}
      </TableRowCell>
      <TableRowCell>{release.indexer}</TableRowCell>
      <TableRowCell className={styles.nowrap}>{release.posted ? dates.date(release.posted) : ''}</TableRowCell>
      <TableRowCell className={styles.nowrap}>{release.size ? formatBytes(release.size) : ''}</TableRowCell>
      <TableRowCell>
        <Label>{release.quality}</Label>
      </TableRowCell>
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
            The magazine search would reject this.{' '}
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

function IssueSearch({ title, issue }: { title: string; issue: string }) {
  const { data, error, isFetching } = useQuery({
    queryKey: ['release', 'issue', title, issue],
    queryFn: () => api<IssueRelease[]>('/release/issue', { query: { title, issue } }),
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

  const matching = data.filter((release) => release.matches).length;
  const approved = data.filter((release) => release.approved).length;

  return (
    <>
      <p className={styles.summary}>
        {data.length} {data.length === 1 ? 'release' : 'releases'}
        {issue ? `, ${matching} of this issue, first` : ''}, {approved} the magazine search would take. Hover the red
        icon to see why one would be rejected.
      </p>
      <Table columns={COLUMNS}>
        {data.map((release) => (
          <IssueReleaseRow key={release.id} release={release} title={title} issue={issue} />
        ))}
      </Table>
    </>
  );
}

interface IssueSearchModalProps {
  isOpen: boolean;
  title: string;
  // the issue as the library keeps it, '' for every release of the magazine
  issue: string;
  onModalClose: () => void;
}

export function IssueSearchModal({ isOpen, title, issue, onModalClose }: IssueSearchModalProps) {
  const dates = useDates();

  return (
    <Modal isOpen={isOpen} size="extraExtraLarge" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>
          Interactive Search - {title}
          {issue ? ` ${dates.issue(issue)}` : ''}
        </ModalHeader>
        <ModalBody>{isOpen ? <IssueSearch title={title} issue={issue} /> : null}</ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Close</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default IssueSearch;
