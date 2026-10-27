// Sonarr's System, Status: what needs looking at, the disk space where the libraries and downloads
// are, and what's running where
import { useQuery } from '@tanstack/react-query';
import { CircleX, Info, Power, RotateCcw, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator, ProgressBar } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { DiskSpace, HealthCheck, SystemStatus } from 'typings/System';
import { api } from 'Utilities/api';
import { formatBytes, formatDateTime, relativeDate } from 'Utilities/format';
import Restarting from '../Restarting';
import { useHealth } from './useHealth';
import styles from './Status.module.css';

const HEALTH_COLUMNS: Column[] = [
  { name: 'type', label: 'Type', isVisuallyHidden: true },
  { name: 'message', label: 'Message' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

const DISK_COLUMNS: Column[] = [
  { name: 'path', label: 'Location' },
  { name: 'freeSpace', label: 'Free Space' },
  { name: 'totalSpace', label: 'Total Space' },
  { name: 'progress', label: 'Used', isVisuallyHidden: true },
];

const TYPES = {
  error: { iconName: CircleX, kind: 'danger', title: 'Error' },
  warning: { iconName: TriangleAlert, kind: 'warning', title: 'Warning' },
  notice: { iconName: Info, kind: 'primary', title: 'Notice' },
} as const;

function Health() {
  const { data, error, isLoading } = useHealth();

  return (
    <>
      <h2 className={styles.legend}>Health</h2>
      {isLoading ? <LoadingIndicator /> : null}
      {error ? <Alert kind="danger">Failed to check health: {error.message}</Alert> : null}
      {data && !data.length ? <Alert kind="success">No issues with your configuration</Alert> : null}
      {data?.length ? (
        <Table columns={HEALTH_COLUMNS}>
          {data.map((check: HealthCheck) => {
            const type = TYPES[check.type] ?? TYPES.notice;

            return (
              <TableRow key={`${check.source}-${check.message}`}>
                <TableRowCell className={styles.type}>
                  <Icon name={type.iconName} kind={type.kind} title={type.title} />
                </TableRowCell>
                <TableRowCell className={styles.message}>{check.message}</TableRowCell>
                <TableRowCell className={styles.actions}>
                  {check.link ? <Link to={check.link}>{check.link === '/config' ? 'Settings' : 'Show'}</Link> : null}
                </TableRowCell>
              </TableRow>
            );
          })}
        </Table>
      ) : null}
    </>
  );
}

function Disks() {
  const { data, error } = useQuery({ queryKey: ['diskspace'], queryFn: () => api<DiskSpace[]>('/diskspace') });

  return (
    <>
      <h2 className={styles.legend}>Disk Space</h2>
      {error ? <Alert kind="danger">Failed to load the disk space: {error.message}</Alert> : null}
      {data?.length ? (
        <Table columns={DISK_COLUMNS}>
          {data.map((disk) => {
            const used = disk.totalSpace ? Math.round((100 * (disk.totalSpace - disk.freeSpace)) / disk.totalSpace) : 0;

            return (
              <TableRow key={disk.path}>
                <TableRowCell>
                  {disk.path}
                  <div className={styles.label}>{disk.label}</div>
                </TableRowCell>
                <TableRowCell className={styles.nowrap}>{formatBytes(disk.freeSpace)}</TableRowCell>
                <TableRowCell className={styles.nowrap}>{formatBytes(disk.totalSpace)}</TableRowCell>
                <TableRowCell className={styles.progress}>
                  <ProgressBar
                    progress={used}
                    kind={used > 95 ? 'danger' : used > 85 ? 'warning' : 'primary'}
                    title={`${used}% used`}
                  />
                </TableRowCell>
              </TableRow>
            );
          })}
        </Table>
      ) : null}
    </>
  );
}

function About() {
  const { data, error } = useQuery({ queryKey: ['status'], queryFn: () => api<SystemStatus>('/system/status') });

  if (error) {
    return <Alert kind="danger">Failed to load the status: {error.message}</Alert>;
  }

  if (!data) {
    return null;
  }

  const rows: [string, string][] = [
    ['Version', data.version ? data.version.slice(0, 8) : ''],
    ['Branch', data.branch],
    [
      'Updates',
      data.commitsBehind > 0 ? `${data.commitsBehind} behind` : data.commitsBehind === 0 ? 'Up to date' : 'Unknown',
    ],
    ['Install', data.isDocker ? `${data.installType}, Docker` : data.installType],
    ['Python', data.pythonVersion],
    ['OS', `${data.osName} ${data.osVersion}`],
    ['Database', `SQLite, version ${data.databaseVersion}, ${data.databasePath}`],
    ['AppData Directory', data.appData],
    ['Startup Directory', data.startupPath],
    ['Started', `${relativeDate(data.startTime)}, ${formatDateTime(data.startTime)}`],
  ];

  return (
    <>
      <h2 className={styles.legend}>About</h2>
      <dl className={styles.about}>
        {rows
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label} className={styles.detail}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
    </>
  );
}

function Status() {
  const [isConfirming, setIsConfirming] = useState<'restart' | 'shutdown' | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [isShutDown, setIsShutDown] = useState(false);

  return (
    <PageContent title="Status">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Restart" iconName={RotateCcw} onPress={() => setIsConfirming('restart')} />
          <PageToolbarButton label="Shutdown" iconName={Power} onPress={() => setIsConfirming('shutdown')} />
        </PageToolbarSection>
      </PageToolbar>
      <PageContentBody>
        {isShutDown ? <Alert kind="warning">LazyLibrarian has shut down</Alert> : null}
        <Health />
        <Disks />
        <About />
      </PageContentBody>
      <ConfirmModal
        isOpen={isConfirming === 'restart'}
        title="Restart"
        message="Are you sure you want to restart LazyLibrarian?"
        confirmLabel="Restart"
        kind="primary"
        onConfirm={() => {
          setIsConfirming(null);
          api('/system/restart', { method: 'POST' }).then(() => setIsRestarting(true));
        }}
        onCancel={() => setIsConfirming(null)}
      />
      <ConfirmModal
        isOpen={isConfirming === 'shutdown'}
        title="Shutdown"
        message="Are you sure you want to shut down LazyLibrarian? It has to be started again on the computer it runs on."
        confirmLabel="Shutdown"
        onConfirm={() => {
          setIsConfirming(null);
          api('/system/shutdown', { method: 'POST' }).then(() => setIsShutDown(true));
        }}
        onCancel={() => setIsConfirming(null)}
      />
      <Restarting isOpen={isRestarting} message="LazyLibrarian is restarting." />
    </PageContent>
  );
}

export default Status;
