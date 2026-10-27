// Sonarr's System, Updates: the version running, what has changed since, installing it, or how to
// when LazyLibrarian can't do it itself
import { useQuery } from '@tanstack/react-query';
import { CloudDownload, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { runCommand } from 'App/commands';
import queryClient from 'App/queryClient';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { UpdateInfo } from 'typings/System';
import { api } from 'Utilities/api';
import { formatDateTime, relativeDate } from 'Utilities/format';
import Restarting from '../Restarting';
import styles from '../System.module.css';

function short(version: string) {
  return /^[0-9a-f]{40}$/.test(version) ? version.slice(0, 8) : version;
}

function Updates() {
  const [isChecking, setIsChecking] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);
  const { data, error, isLoading } = useQuery({ queryKey: ['update'], queryFn: () => api<UpdateInfo>('/update') });

  return (
    <PageContent title="Updates">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Check for Update"
            iconName={RefreshCw}
            isSpinning={isChecking}
            onPress={() => {
              setIsChecking(true);
              runCommand('RunTask', { task: 'check_for_updates' }, 'Checking for updates').finally(() => {
                setIsChecking(false);
                queryClient.invalidateQueries({ queryKey: ['update'] });
              });
            }}
          />
          <PageToolbarButton
            label="Install Latest"
            iconName={CloudDownload}
            isDisabled={!data?.canInstall}
            onPress={() => setIsConfirming(true)}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the updates: {(error as Error).message}</Alert> : null}

        {data ? (
          <>
            <div className={styles.version}>
              Version {short(data.version)} ({data.branch})
            </div>
            <p className={styles.note}>
              {data.lastChecked
                ? `Last checked ${relativeDate(data.lastChecked)}, ${formatDateTime(data.lastChecked)}`
                : 'Not checked yet'}
            </p>

            {data.message ? <Alert kind="warning">{data.message}</Alert> : null}
            {data.behind === 0 ? <Alert kind="success">LazyLibrarian is up to date</Alert> : null}
            {data.behind > 0 && data.whyNot ? <Alert kind="info">{data.whyNot}</Alert> : null}

            {data.changes.length ? (
              <>
                <h2 className={styles.legend}>
                  {data.behind} {data.behind === 1 ? 'change' : 'changes'} to {short(data.latestVersion)}
                </h2>
                <ul className={styles.changes}>
                  {data.changes.map((change, index) => (
                    <li key={`${index}-${change}`}>{change}</li>
                  ))}
                </ul>
                <Link to={`${data.repo}/compare/${data.version}...${data.latestVersion}`}>Every change, on GitHub</Link>
              </>
            ) : null}
          </>
        ) : null}
      </PageContentBody>

      <ConfirmModal
        isOpen={isConfirming}
        title="Install Latest"
        message="LazyLibrarian backs up, updates and restarts. The page loads again when it's back."
        confirmLabel="Install"
        kind="primary"
        onConfirm={() => {
          setIsConfirming(false);
          runCommand('ApplicationUpdate', {}, 'Updating').then((command) => {
            if (command?.status === 'completed') {
              setIsRestarting(true);
            }
          });
        }}
        onCancel={() => setIsConfirming(false)}
      />
      <Restarting isOpen={isRestarting} message="Updating, LazyLibrarian will restart." />
    </PageContent>
  );
}

export default Updates;
