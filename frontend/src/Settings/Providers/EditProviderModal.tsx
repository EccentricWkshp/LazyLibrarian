// Sonarr's EditDownloadClientModal, EditIndexerModal and EditNotificationModal in one: a download
// client's, indexer's or notifier's settings, a test with them as they are, and taking it out
import { useState } from 'react';
import queryClient from 'App/queryClient';
import Button from 'Components/Link/Button';
import { Alert } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { ConfigChoices, ConfigValue, Field, FieldValue, TestResult, Values } from 'Settings/Sections/fields';
import { FieldRows } from 'Settings/Sections/SettingsSection';
import { api } from 'Utilities/api';
import { Kind, kindKeys } from './kinds';
import styles from './Providers.module.css';

export interface Editing {
  kind: Kind;
  // a list's item, none for a new one
  index: number | null;
  isNew: boolean;
  values: Values;
  configs: Record<string, ConfigValue>;
}

interface EditProviderModalProps {
  editing: Editing | null;
  choices: ConfigChoices | undefined;
  onModalClose: () => void;
}

function changed() {
  return queryClient.invalidateQueries({ queryKey: ['config'] });
}

function EditProviderModalContent({ editing, choices, onModalClose }: EditProviderModalProps & { editing: Editing }) {
  const { kind } = editing;
  // a new one is switched on
  const [edited, setEdited] = useState<Values>(editing.isNew && kind.enable ? { [kind.enable]: true } : {});
  const [index, setIndex] = useState(editing.index);
  const [isNew, setIsNew] = useState(editing.isNew);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState<TestResult | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [isConfirming, setIsConfirming] = useState(false);

  const values = { ...editing.values, ...edited };
  const changes = Object.fromEntries(
    Object.entries(edited).filter(([key, value]) => isNew || String(value) !== String(editing.values[key]))
  );
  const fields: Field[] =
    kind.enable && !kind.fields.some((field) => field.key === kind.enable)
      ? [{ key: kind.enable, label: 'Enable' }, ...kind.fields]
      : kind.fields;
  const hasAdvanced = fields.some((field) => field.advanced);

  async function run(what: string, action: () => Promise<void>) {
    setBusy(what);
    setProblems([]);
    try {
      await action();
    } catch (error) {
      setProblems([(error as Error).message]);
    } finally {
      setBusy('');
    }
  }

  function save() {
    return run('save', async () => {
      let messages: string[];
      if (!kind.list) {
        messages = (await api<{ messages: string[] }>('/config', { method: 'PUT', body: { values: changes } })).messages;
      } else if (isNew) {
        const saved = await api<{ index: number; messages: string[] }>(`/config/list/${kind.id}`, {
          method: 'POST',
          body: { values: changes },
        });
        setIndex(saved.index);
        setIsNew(false);
        messages = saved.messages;
      } else {
        messages = (
          await api<{ messages: string[] }>(`/config/list/${kind.id}/${index}`, { method: 'PUT', body: { values: changes } })
        ).messages;
      }
      await changed();
      if (messages.length) {
        setProblems(messages);
      } else {
        onModalClose();
      }
    });
  }

  function test() {
    setResult(null);
    return run('test', async () => {
      const tested = await api<TestResult>('/config/test', {
        method: 'POST',
        body: kind.list
          ? { listName: kind.id, index: isNew ? null : index, values: changes }
          : { test: kind.test, values: changes },
      });
      setResult(tested);
      if (tested.ok) {
        // it's saved, a new one is added
        if (kind.list && isNew) {
          setIndex(tested.index);
          setIsNew(false);
        }
        await changed();
      }
    });
  }

  function remove() {
    setIsConfirming(false);
    return run('delete', async () => {
      if (kind.list) {
        await api(`/config/list/${kind.id}/${index}`, { method: 'DELETE' });
      } else {
        await api('/config/reset', { method: 'POST', body: { keys: [...new Set(kindKeys(kind))] } });
      }
      await changed();
      onModalClose();
    });
  }

  return (
    <ModalContent onModalClose={onModalClose}>
      <ModalHeader>
        {isNew ? 'Add' : 'Edit'} {kind.protocol === 'Notifications' ? 'Connection' : ''} - {kind.name}
      </ModalHeader>
      <ModalBody>
        <p className={styles.description}>{kind.description}</p>
        <FieldRows
          fields={fields}
          configs={editing.configs}
          values={values}
          choices={choices}
          showAdvanced={showAdvanced}
          onChange={(key: string, value: FieldValue) => setEdited((current) => ({ ...current, [key]: value }))}
        />
        {result ? (
          <Alert kind={result.ok ? 'success' : 'danger'}>
            <span className={styles.message}>
              {result.message || (result.ok ? 'It works' : "It didn't work")}
              {result.ok ? '\nIt works, so its settings are saved' : ''}
            </span>
          </Alert>
        ) : null}
        {problems.length ? (
          <Alert kind="warning">
            {problems.map((problem) => (
              <div key={problem}>{problem}</div>
            ))}
          </Alert>
        ) : null}
      </ModalBody>
      <ModalFooter className={styles.footer}>
        {isNew ? null : (
          <Button kind="danger" isSpinning={busy === 'delete'} onPress={() => setIsConfirming(true)}>
            Delete
          </Button>
        )}
        {hasAdvanced ? (
          <Button onPress={() => setShowAdvanced(!showAdvanced)}>
            {showAdvanced ? 'Hide Advanced' : 'Show Advanced'}
          </Button>
        ) : null}
        <span className={styles.spacer} />
        {kind.test || kind.list ? (
          <Button isSpinning={busy === 'test'} onPress={test}>
            Test
          </Button>
        ) : null}
        <Button onPress={onModalClose}>Cancel</Button>
        <Button kind="primary" isSpinning={busy === 'save'} onPress={save}>
          Save
        </Button>
      </ModalFooter>
      <ConfirmModal
        isOpen={isConfirming}
        title={`Delete ${kind.name}`}
        message={
          kind.list
            ? `Delete ${String(values.DISPNAME || kind.name)}?`
            : `Delete ${kind.name}? Its settings go back to their defaults.`
        }
        confirmLabel="Delete"
        onConfirm={remove}
        onCancel={() => setIsConfirming(false)}
      />
    </ModalContent>
  );
}

function EditProviderModal({ editing, choices, onModalClose }: EditProviderModalProps) {
  return (
    <Modal isOpen={!!editing} size="large" onModalClose={onModalClose}>
      {editing ? (
        <EditProviderModalContent
          key={`${editing.kind.id}-${editing.index}`}
          editing={editing}
          choices={choices}
          onModalClose={onModalClose}
        />
      ) : null}
    </Modal>
  );
}

export default EditProviderModal;
