// Sonarr's System, Log Files: the log files, to read or download, the support zip, which has the
// passwords and keys taken out, and deleting them
import { useMutation, useQuery } from '@tanstack/react-query';
import { FileArchive, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import queryClient from 'App/queryClient';
import { Alert, LoadingIndicator } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { LogFile } from 'typings/System';
import { api, urlBase } from 'Utilities/api';
import { formatBytes, formatDateTime, relativeDate } from 'Utilities/format';
import styles from '../System.module.css';

const COLUMNS: Column[] = [
  { name: 'filename', label: 'Filename' },
  { name: 'lastWriteTime', label: 'Last Write Time' },
  { name: 'size', label: 'Size' },
  { name: 'download', label: 'Download', isVisuallyHidden: true },
];

function LogFiles() {
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['logfiles'],
    queryFn: () => api<LogFile[]>('/log/file'),
  });
  const remove = useMutation({
    mutationFn: () => api<{ message: string }>('/log/file', { method: 'DELETE' }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['logfiles'] }),
  });

  return (
    <PageContent title="Log Files">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Refresh" iconName={RefreshCw} isSpinning={isFetching} onPress={() => refetch()} />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Support Zip"
            iconName={FileArchive}
            onPress={() => {
              window.location.href = `${urlBase()}/api/v1/log/supportzip`;
            }}
          />
          <PageToolbarButton
            label="Delete Log Files"
            iconName={Trash2}
            isSpinning={remove.isPending}
            onPress={() => setIsDeleteOpen(true)}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        <p className={styles.note}>
          The log files are in the Logs folder of LazyLibrarian's data folder. The support zip has the log and settings
          with passwords and keys taken out, to send with a problem.
        </p>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the log files: {(error as Error).message}</Alert> : null}
        {remove.data ? <Alert kind="info">{remove.data.message}</Alert> : null}
        {data && !data.length ? <Alert kind="info">No log files</Alert> : null}
        {data?.length ? (
          <Table columns={COLUMNS}>
            {data.map((file) => (
              <TableRow key={file.filename}>
                <TableRowCell className={styles.message}>{file.filename}</TableRowCell>
                <TableRowCell className={styles.nowrap} title={formatDateTime(file.lastWriteTime)}>
                  {relativeDate(file.lastWriteTime)}
                </TableRowCell>
                <TableRowCell className={styles.nowrap}>{formatBytes(file.size)}</TableRowCell>
                <TableRowCell className={styles.actions}>
                  <a href={`${urlBase()}/api/v1/log/file/${encodeURIComponent(file.filename)}`} target="_blank" rel="noreferrer">
                    View
                  </a>
                </TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}
      </PageContentBody>

      <ConfirmModal
        isOpen={isDeleteOpen}
        title="Delete Log Files"
        message="Delete every log file? LazyLibrarian starts new ones."
        confirmLabel="Delete"
        onConfirm={() => {
          setIsDeleteOpen(false);
          remove.mutate();
        }}
        onCancel={() => setIsDeleteOpen(false)}
      />
    </PageContent>
  );
}

export default LogFiles;
