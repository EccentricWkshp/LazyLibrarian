// Sonarr's System, Backup: the backups, made on a schedule, by hand or before an update, to
// download, restore or delete, Backup Now, and restoring one from a file
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArchiveRestore, Clock, Download, History, Save, Trash2, User } from 'lucide-react';
import { useState } from 'react';
import { runCommand } from 'App/commands';
import queryClient from 'App/queryClient';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { Backup } from 'typings/System';
import { api, ApiError, urlBase } from 'Utilities/api';
import { formatBytes, formatDateTime, relativeDate } from 'Utilities/format';
import Restarting from '../Restarting';
import styles from '../System.module.css';

const COLUMNS: Column[] = [
  { name: 'type', label: 'Type', isVisuallyHidden: true },
  { name: 'name', label: 'Name' },
  { name: 'size', label: 'Size' },
  { name: 'time', label: 'Time' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

const TYPES = {
  scheduled: { iconName: Clock, title: 'Scheduled' },
  manual: { iconName: User, title: 'Manual' },
  update: { iconName: Download, title: 'Before an update' },
  restore: { iconName: History, title: 'Before a restore' },
};

function BackupRow({ backup, onRestore }: { backup: Backup; onRestore: () => void }) {
  const [isConfirming, setIsConfirming] = useState<'restore' | 'delete' | null>(null);
  const remove = useMutation({
    mutationFn: () => api(`/system/backup/${backup.id}`, { method: 'DELETE' }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['backups'] }),
  });
  const restore = useMutation({
    mutationFn: () => api(`/system/backup/restore/${backup.id}`, { method: 'POST' }),
    onSuccess: onRestore,
  });
  const type = TYPES[backup.type] ?? TYPES.manual;

  return (
    <TableRow>
      <TableRowCell className={styles.icon}>
        <Icon name={type.iconName} title={type.title} />
      </TableRowCell>
      <TableRowCell className={styles.message}>
        <Link to={`/api/v1/system/backup/file/${backup.id}`} noRouter={true}>
          {backup.name}
        </Link>
        {restore.isError ? <div className={styles.muted}>{restore.error.message}</div> : null}
      </TableRowCell>
      <TableRowCell className={styles.nowrap}>{formatBytes(backup.size)}</TableRowCell>
      <TableRowCell className={styles.nowrap} title={formatDateTime(backup.time)}>
        {relativeDate(backup.time)}
      </TableRowCell>
      <TableRowCell className={styles.actions}>
        <IconButton
          name={ArchiveRestore}
          title="Restore Backup"
          isSpinning={restore.isPending}
          onPress={() => setIsConfirming('restore')}
        />
        <IconButton
          name={Trash2}
          title={remove.isError ? remove.error.message : 'Delete Backup'}
          isSpinning={remove.isPending}
          onPress={() => setIsConfirming('delete')}
        />
      </TableRowCell>
      <ConfirmModal
        isOpen={isConfirming === 'restore'}
        title="Restore Backup"
        message={`Restore ${backup.name}? LazyLibrarian restarts to put it in place, and keeps what's there now as a backup of its own.`}
        confirmLabel="Restore"
        kind="warning"
        onConfirm={() => {
          setIsConfirming(null);
          restore.mutate();
        }}
        onCancel={() => setIsConfirming(null)}
      />
      <ConfirmModal
        isOpen={isConfirming === 'delete'}
        title="Delete Backup"
        message={`Are you sure you want to delete the backup ${backup.name}?`}
        confirmLabel="Delete"
        onConfirm={() => {
          setIsConfirming(null);
          remove.mutate();
        }}
        onCancel={() => setIsConfirming(null)}
      />
    </TableRow>
  );
}

function RestoreFromFileModal({
  isOpen,
  onRestore,
  onModalClose,
}: {
  isOpen: boolean;
  onRestore: () => void;
  onModalClose: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [isUploading, setIsUploading] = useState(false);

  async function upload() {
    if (!file) {
      return;
    }

    setIsUploading(true);
    setError('');

    try {
      const response = await fetch(`${urlBase()}/api/v1/system/backup/upload`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': file.name },
        body: file,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new ApiError(response.status, data.detail ?? `The upload failed (${response.status})`);
      }

      onRestore();
    } catch (why) {
      setError((why as Error).message);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <Modal isOpen={isOpen} size="medium" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Restore Backup</ModalHeader>
        <ModalBody>
          <p className={styles.note}>
            Choose a backup, a .tgz from System, Backup. LazyLibrarian restarts to put it in place, and keeps what's
            there now as a backup of its own.
          </p>
          <input
            className={styles.fileInput}
            type="file"
            accept=".tgz,.gz,application/gzip"
            aria-label="Backup file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          {error ? <Alert kind="danger">{error}</Alert> : null}
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button kind="warning" isDisabled={!file} isSpinning={isUploading} onPress={upload}>
            Restore
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

function Backups() {
  const [isBackingUp, setIsBackingUp] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);
  const { data, error, isLoading } = useQuery({
    queryKey: ['backups'],
    queryFn: () => api<Backup[]>('/system/backup'),
  });

  function restarting() {
    setIsUploadOpen(false);
    setIsRestarting(true);
  }

  return (
    <PageContent title="Backups">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Backup Now"
            iconName={Save}
            isSpinning={isBackingUp}
            onPress={() => {
              setIsBackingUp(true);
              runCommand('Backup', {}, 'Backing up').finally(() => setIsBackingUp(false));
            }}
          />
          <PageToolbarButton label="Restore Backup" iconName={ArchiveRestore} onPress={() => setIsUploadOpen(true)} />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the backups: {(error as Error).message}</Alert> : null}
        {data && !data.length ? <Alert kind="info">No backups are available</Alert> : null}
        {data?.length ? (
          <Table columns={COLUMNS}>
            {data.map((backup) => (
              <BackupRow key={backup.id} backup={backup} onRestore={restarting} />
            ))}
          </Table>
        ) : null}
        <p className={styles.note}>
          Backups hold the database and settings, in the Backups folder of LazyLibrarian's data folder. How often
          they're made, and how long scheduled ones are kept, are in Settings.
        </p>
      </PageContentBody>

      <RestoreFromFileModal isOpen={isUploadOpen} onRestore={restarting} onModalClose={() => setIsUploadOpen(false)} />
      <Restarting isOpen={isRestarting} message="Restoring the backup, LazyLibrarian is restarting to put it in place." />
    </PageContent>
  );
}

export default Backups;
