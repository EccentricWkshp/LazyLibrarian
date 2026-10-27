// Sonarr's Remote Path Mappings: where a download client's folders are here, when it runs elsewhere
import { useMutation, useQuery } from '@tanstack/react-query';
import { Pencil, Plus } from 'lucide-react';
import { useState } from 'react';
import queryClient from 'App/queryClient';
import { FormInputHelpText, FormLabel, FormRow, TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import { Alert } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { api } from 'Utilities/api';
import cardStyles from '../Profiles/Profiles.module.css';
import styles from './Providers.module.css';

interface Mapping {
  id: number;
  host: string;
  remotePath: string;
  localPath: string;
}

const NEW: Mapping = { id: 0, host: '', remotePath: '', localPath: '' };

function changed() {
  queryClient.invalidateQueries({ queryKey: ['remotepathmapping'] });
  queryClient.invalidateQueries({ queryKey: ['health'] });
}

function EditMappingModal({ mapping, onModalClose }: { mapping: Mapping; onModalClose: () => void }) {
  const [edited, setEdited] = useState(mapping);
  const save = useMutation({
    mutationFn: (saving: Mapping) =>
      saving.id
        ? api(`/remotepathmapping/${saving.id}`, { method: 'PUT', body: saving })
        : api('/remotepathmapping', { method: 'POST', body: saving }),
    onSuccess: () => {
      changed();
      onModalClose();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/remotepathmapping/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      changed();
      onModalClose();
    },
  });
  const error = save.error ?? remove.error;

  return (
    <ModalContent onModalClose={onModalClose}>
      <ModalHeader>{mapping.id ? 'Edit Remote Path Mapping' : 'Add Remote Path Mapping'}</ModalHeader>
      <ModalBody>
        <FormRow>
          <FormLabel htmlFor="mappingHost">Host</FormLabel>
          <FormInputHelpText text="The download client's host, as it's set in the client's settings" />
          <TextInput id="mappingHost" value={edited.host} onChange={(host) => setEdited({ ...edited, host })} />
        </FormRow>
        <FormRow>
          <FormLabel htmlFor="mappingRemote">Remote Path</FormLabel>
          <FormInputHelpText text="A folder as the download client sees it" />
          <TextInput
            id="mappingRemote"
            value={edited.remotePath}
            onChange={(remotePath) => setEdited({ ...edited, remotePath })}
          />
        </FormRow>
        <FormRow>
          <FormLabel htmlFor="mappingLocal">Local Path</FormLabel>
          <FormInputHelpText text="The same folder as LazyLibrarian reaches it" />
          <TextInput
            id="mappingLocal"
            value={edited.localPath}
            onChange={(localPath) => setEdited({ ...edited, localPath })}
          />
        </FormRow>
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
      </ModalBody>
      <ModalFooter>
        {mapping.id ? (
          <Button kind="danger" isSpinning={remove.isPending} onPress={() => remove.mutate(mapping.id)}>
            Delete
          </Button>
        ) : null}
        <Button onPress={onModalClose}>Cancel</Button>
        <Button kind="primary" isSpinning={save.isPending} onPress={() => save.mutate(edited)}>
          Save
        </Button>
      </ModalFooter>
    </ModalContent>
  );
}

function RemotePathMappings() {
  const [editing, setEditing] = useState<Mapping | null>(null);
  const { data, error } = useQuery({
    queryKey: ['remotepathmapping'],
    queryFn: () => api<Mapping[]>('/remotepathmapping'),
  });

  return (
    <section className={styles.section}>
      <h2 className={cardStyles.legend}>Remote Path Mappings</h2>
      {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
      <table className={styles.mappings}>
        <thead>
          <tr>
            <th>Host</th>
            <th>Remote Path</th>
            <th>Local Path</th>
            <th aria-label="Edit" />
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((mapping) => (
            <tr key={mapping.id}>
              <td>{mapping.host}</td>
              <td>{mapping.remotePath}</td>
              <td>{mapping.localPath}</td>
              <td className={styles.mappingActions}>
                <IconButton name={Pencil} title="Edit the mapping" onPress={() => setEditing(mapping)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Button className={styles.addMapping} onPress={() => setEditing(NEW)}>
        <Icon name={Plus} /> Add Mapping
      </Button>
      <Modal isOpen={!!editing} onModalClose={() => setEditing(null)}>
        {editing ? <EditMappingModal key={editing.id} mapping={editing} onModalClose={() => setEditing(null)} /> : null}
      </Modal>
    </section>
  );
}

export default RemotePathMappings;
