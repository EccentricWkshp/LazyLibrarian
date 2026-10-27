export interface NotificationHeader {
  key: string;
  value: string;
}

export interface WebhookSettings {
  url: string;
  method: 'POST' | 'PUT';
  username: string;
  // sent back masked when there is one, saving it masked keeps it
  password: string;
  headers: NotificationHeader[];
}

export interface NotificationTriggers {
  onGrab: boolean;
  onDownload: boolean;
  onUpgrade: boolean;
  onDownloadFailure: boolean;
  onManualInteractionRequired: boolean;
  onHealthIssue: boolean;
  includeHealthWarnings: boolean;
  onHealthRestored: boolean;
  onApplicationUpdate: boolean;
}

export interface Notification extends NotificationTriggers {
  id: number;
  name: string;
  implementation: 'Webhook';
  settings: WebhookSettings;
}
