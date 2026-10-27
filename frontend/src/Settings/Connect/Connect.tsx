// Sonarr's Settings, Connect: the connections, each a card with the events it's sent. Webhooks for
// now, the other notifiers are still in the old Settings
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useState } from 'react';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { Notification } from 'typings/Notification';
import { api } from 'Utilities/api';
import styles from '../Profiles/Profiles.module.css';
import EditNotificationModal from './EditNotificationModal';
import { TRIGGERS } from './triggers';

function NotificationCard({ notification, onPress }: { notification: Notification; onPress: () => void }) {
  const on = TRIGGERS.filter((trigger) => notification[trigger.key]);

  return (
    <Link className={styles.card} onPress={onPress}>
      <div className={styles.cardName}>{notification.name}</div>
      <div className={styles.chips}>
        {on.length ? (
          on.map((trigger) => (
            <Label key={trigger.key} kind="success">
              {trigger.label}
            </Label>
          ))
        ) : (
          <Label>Disabled</Label>
        )}
      </div>
      <div className={styles.cardNote}>{notification.implementation}</div>
    </Link>
  );
}

function Connect() {
  const [editing, setEditing] = useState<Notification | null>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ['notification'],
    queryFn: () => api<Notification[]>('/notification'),
  });

  async function add() {
    const [webhook] = await api<Notification[]>('/notification/schema');
    setEditing(webhook);
  }

  return (
    <PageContent title="Connect">
      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the connections: {(error as Error).message}</Alert> : null}
        {data ? (
          <section>
            <h2 className={styles.legend}>Connections</h2>
            <div className={styles.cards}>
              {data.map((notification) => (
                <NotificationCard
                  key={notification.id}
                  notification={notification}
                  onPress={() => setEditing(notification)}
                />
              ))}
              <Link className={styles.addCard} onPress={add} aria-label="Add Connection">
                <Icon name={Plus} size={36} />
              </Link>
            </div>
          </section>
        ) : null}
        <p className={styles.note}>
          A webhook is sent each event it is on for as JSON, shaped as Readarr's: its eventType, the author and books or
          the magazine or comic and issue, the release and the download client. Email, Pushover, Telegram and the other
          notifiers are in the old <Link to="/config">Settings</Link>, Notifications.
        </p>
      </PageContentBody>

      <EditNotificationModal isOpen={!!editing} notification={editing} onModalClose={() => setEditing(null)} />
    </PageContent>
  );
}

export default Connect;
