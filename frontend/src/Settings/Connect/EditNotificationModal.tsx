// Sonarr's EditNotificationModal for a webhook: the name, the events it's sent, where to and how,
// and a test that sends one as it's filled in
import { useMutation } from '@tanstack/react-query';
import { Plus, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import queryClient from 'App/queryClient';
import { CheckInput, FormInputHelpText, FormLabel, FormRow, SelectInput, TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import { Alert } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { Notification, WebhookSettings } from 'typings/Notification';
import { api } from 'Utilities/api';
import { TRIGGERS } from './triggers';
import styles from './Connect.module.css';

interface EditNotificationModalProps {
  isOpen: boolean;
  notification: Notification | null;
  onModalClose: () => void;
}

const METHODS = [
  { key: 'POST', value: 'POST' },
  { key: 'PUT', value: 'PUT' },
];

function changed() {
  queryClient.invalidateQueries({ queryKey: ['notification'] });
  queryClient.invalidateQueries({ queryKey: ['health'] });
}

function EditNotificationModal({ isOpen, notification, onModalClose }: EditNotificationModalProps) {
  const [edited, setEdited] = useState<Notification | null>(notification);

  useEffect(() => {
    setEdited(notification);
  }, [notification]);

  const save = useMutation({
    mutationFn: (saving: Notification) =>
      saving.id
        ? api<Notification>(`/notification/${saving.id}`, { method: 'PUT', body: saving })
        : api<Notification>('/notification', { method: 'POST', body: saving }),
    onSuccess: () => {
      changed();
      onModalClose();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/notification/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      changed();
      onModalClose();
    },
  });
  const test = useMutation({
    mutationFn: (testing: Notification) => api('/notification/test', { method: 'POST', body: testing }),
  });

  useEffect(() => {
    save.reset();
    remove.reset();
    test.reset();
    // only when another connection is opened
  }, [notification]);

  if (!edited) {
    return null;
  }

  const error = save.error ?? remove.error ?? test.error;

  function setSettings(settings: Partial<WebhookSettings>) {
    setEdited((current) => (current ? { ...current, settings: { ...current.settings, ...settings } } : current));
  }

  function setHeader(index: number, key: 'key' | 'value', value: string) {
    setSettings({
      headers: edited!.settings.headers.map((header, i) => (i === index ? { ...header, [key]: value } : header)),
    });
  }

  return (
    <Modal isOpen={isOpen} size="medium" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>{edited.id ? 'Edit Connection - Webhook' : 'Add Connection - Webhook'}</ModalHeader>
        <ModalBody>
          <FormRow>
            <FormLabel htmlFor="notificationName">Name</FormLabel>
            <TextInput
              id="notificationName"
              value={edited.name}
              onChange={(name) => setEdited({ ...edited, name })}
            />
          </FormRow>

          <FormRow>
            <FormLabel>Notification Triggers</FormLabel>
            <div className={styles.triggers}>
              {TRIGGERS.map((trigger) => (
                <div key={trigger.key}>
                  <label className={styles.trigger} title={trigger.help}>
                    <CheckInput
                      checked={edited[trigger.key]}
                      onChange={(on) => setEdited({ ...edited, [trigger.key]: on })}
                    />
                    {trigger.label}
                  </label>
                  {trigger.key === 'onHealthIssue' && edited.onHealthIssue ? (
                    <label className={styles.subTrigger}>
                      <CheckInput
                        checked={edited.includeHealthWarnings}
                        onChange={(includeHealthWarnings) => setEdited({ ...edited, includeHealthWarnings })}
                      />
                      Include Health Warnings
                    </label>
                  ) : null}
                </div>
              ))}
            </div>
          </FormRow>

          <FormRow>
            <FormLabel htmlFor="webhookUrl">URL</FormLabel>
            <TextInput
              id="webhookUrl"
              placeholder="https://example.com/hook"
              value={edited.settings.url}
              onChange={(url) => setSettings({ url })}
            />
          </FormRow>

          <FormRow>
            <FormLabel htmlFor="webhookMethod">Method</FormLabel>
            <FormInputHelpText text="Which HTTP method to send the JSON with" />
            <SelectInput
              id="webhookMethod"
              value={edited.settings.method}
              values={METHODS}
              onChange={(method) => setSettings({ method: method as WebhookSettings['method'] })}
            />
          </FormRow>

          <FormRow>
            <FormLabel htmlFor="webhookUsername">Username</FormLabel>
            <FormInputHelpText text="For HTTP basic authentication, leave empty for none" />
            <TextInput
              id="webhookUsername"
              autoComplete="off"
              value={edited.settings.username}
              onChange={(username) => setSettings({ username })}
            />
          </FormRow>

          <FormRow>
            <FormLabel htmlFor="webhookPassword">Password</FormLabel>
            <TextInput
              id="webhookPassword"
              type="password"
              autoComplete="new-password"
              value={edited.settings.password}
              onChange={(password) => setSettings({ password })}
            />
          </FormRow>

          <FormRow>
            <FormLabel>Headers</FormLabel>
            <FormInputHelpText text="Sent with each request, as for an API key or a token" />
            {edited.settings.headers.map((header, index) => (
              <div key={index} className={styles.header}>
                <TextInput
                  aria-label="Header name"
                  placeholder="Name"
                  value={header.key}
                  onChange={(value) => setHeader(index, 'key', value)}
                />
                <TextInput
                  aria-label="Header value"
                  placeholder="Value"
                  value={header.value}
                  onChange={(value) => setHeader(index, 'value', value)}
                />
                <IconButton
                  name={X}
                  title="Remove the header"
                  onPress={() => setSettings({ headers: edited.settings.headers.filter((_h, i) => i !== index) })}
                />
              </div>
            ))}
            <Button onPress={() => setSettings({ headers: [...edited.settings.headers, { key: '', value: '' }] })}>
              <Icon name={Plus} /> Add Header
            </Button>
          </FormRow>

          {test.isSuccess ? <Alert kind="success">The test was sent</Alert> : null}
          {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        </ModalBody>
        <ModalFooter>
          {edited.id ? (
            <Button kind="danger" isSpinning={remove.isPending} onPress={() => remove.mutate(edited.id)}>
              Delete
            </Button>
          ) : null}
          <Button isSpinning={test.isPending} onPress={() => test.mutate(edited)}>
            Test
          </Button>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button kind="primary" isSpinning={save.isPending} onPress={() => save.mutate(edited)}>
            Save
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default EditNotificationModal;
