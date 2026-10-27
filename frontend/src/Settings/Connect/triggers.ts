// the events a connection can be sent, as Sonarr's notification triggers
import { NotificationTriggers } from 'typings/Notification';

export const TRIGGERS: { key: keyof NotificationTriggers; label: string; help: string }[] = [
  { key: 'onGrab', label: 'On Grab', help: 'A release is sent to a download client' },
  { key: 'onDownload', label: 'On Import', help: 'A download is imported into the library' },
  { key: 'onUpgrade', label: 'On Upgrade', help: 'A download replaces a file the library had' },
  { key: 'onDownloadFailure', label: 'On Download Failure', help: 'A download fails, or can\'t be sent' },
  {
    key: 'onManualInteractionRequired',
    label: 'On Manual Interaction Required',
    help: "A finished download can't be imported, see Activity, Queue",
  },
  { key: 'onHealthIssue', label: 'On Health Issue', help: 'An error appears in System, Status' },
  { key: 'onHealthRestored', label: 'On Health Restored', help: 'A health issue is gone' },
  { key: 'onApplicationUpdate', label: 'On Application Update', help: 'LazyLibrarian is updated' },
];
