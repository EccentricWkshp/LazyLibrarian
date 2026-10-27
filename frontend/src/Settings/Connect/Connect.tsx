// Sonarr's Settings, Connect: the connections, each a card with the events it's sent. Webhooks have
// settings of their own, Apprise and the other notifiers are settings as the other pages' are
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import Link from 'Components/Link/Link';
import { Label } from 'Components/Misc';
import { NOTIFIERS } from 'Settings/Providers/kinds';
import ProviderPage from 'Settings/Providers/ProviderPage';
import { Group } from 'Settings/Sections/fields';
import { Notification } from 'typings/Notification';
import { api } from 'Utilities/api';
import styles from '../Profiles/Profiles.module.css';
import EditNotificationModal from './EditNotificationModal';
import { TRIGGERS } from './triggers';

const GROUPS: Group[] = [
  {
    legend: 'Options',
    help: "For Apprise and the notifiers other than webhooks, a webhook's JSON has it all",
    fields: [
      { key: 'NOTIFY_WITH_TITLE', label: 'Say what was imported' },
      { key: 'NOTIFY_WITH_URL', label: 'Link to it', help: 'The link can have the API key in it' },
    ],
  },
];

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
  const { data } = useQuery({
    queryKey: ['notification'],
    queryFn: () => api<Notification[]>('/notification'),
  });

  async function add() {
    const [webhook] = await api<Notification[]>('/notification/schema');
    setEditing(webhook);
  }

  return (
    <ProviderPage
      title="Connect"
      heading="Connections"
      kinds={NOTIFIERS}
      groups={GROUPS}
      otherCards={(data ?? []).map((notification) => (
        <NotificationCard key={notification.id} notification={notification} onPress={() => setEditing(notification)} />
      ))}
      otherKinds={[
        {
          name: 'Webhook',
          description: "Each event as JSON, shaped as Readarr's, to an address of yours",
          protocol: 'Notifications',
          onAdd: add,
        },
      ]}
      note="A webhook is sent each event it is on for as JSON, shaped as Readarr's: its eventType, the author and books or the magazine or comic and issue, the release and the download client. The other notifiers are sent a grab and an import."
    >
      <EditNotificationModal isOpen={!!editing} notification={editing} onModalClose={() => setEditing(null)} />
    </ProviderPage>
  );
}

export default Connect;
