// Sonarr's EditQualityProfileModal: the name, whether to upgrade and until which quality, and the
// qualities wanted, best first
import { useMutation } from '@tanstack/react-query';
import { ArrowDown, ArrowUp } from 'lucide-react';
import { useEffect, useState } from 'react';
import queryClient from 'App/queryClient';
import { CheckInput, FormInputHelpText, FormLabel, FormRow, SelectInput, TextInput } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import { Alert } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { QualityProfile } from 'typings/Profiles';
import { api } from 'Utilities/api';
import styles from './Profiles.module.css';

interface EditQualityProfileModalProps {
  isOpen: boolean;
  profile: QualityProfile | null;
  onModalClose: () => void;
}

function changed() {
  queryClient.invalidateQueries({ queryKey: ['qualityprofile'] });
  queryClient.invalidateQueries({ queryKey: ['wanted'] });
}

function EditQualityProfileModal({ isOpen, profile, onModalClose }: EditQualityProfileModalProps) {
  const [edited, setEdited] = useState<QualityProfile | null>(profile);

  useEffect(() => {
    setEdited(profile);
  }, [profile]);

  const save = useMutation({
    mutationFn: (saving: QualityProfile) =>
      saving.id
        ? api<QualityProfile>(`/qualityprofile/${saving.id}`, { method: 'PUT', body: saving })
        : api<QualityProfile>('/qualityprofile', { method: 'POST', body: saving }),
    onSuccess: () => {
      changed();
      onModalClose();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/qualityprofile/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      changed();
      onModalClose();
    },
  });
  const makeDefault = useMutation({
    mutationFn: (id: number) => api<QualityProfile>(`/qualityprofile/${id}/default`, { method: 'POST' }),
    onSuccess: (saved) => {
      changed();
      setEdited((current) => (current ? { ...current, isDefault: saved.isDefault } : current));
    },
  });

  if (!edited) {
    return null;
  }

  const allowed = edited.items.filter((item) => item.allowed);
  const error = save.error ?? remove.error ?? makeDefault.error;

  function move(index: number, by: number) {
    setEdited((current) => {
      if (!current) {
        return current;
      }

      const items = [...current.items];
      const [item] = items.splice(index, 1);
      items.splice(index + by, 0, item);

      return { ...current, items };
    });
  }

  function setAllowed(index: number, isAllowed: boolean) {
    setEdited((current) => {
      if (!current) {
        return current;
      }

      const items = current.items.map((item, i) => (i === index ? { ...item, allowed: isAllowed } : item));
      const stillAllowed = items.filter((item) => item.allowed).map((item) => item.quality);
      // the cutoff has to be one the profile wants
      const cutoff = stillAllowed.includes(current.cutoff) ? current.cutoff : (stillAllowed[0] ?? '');

      return { ...current, items, cutoff };
    });
  }

  return (
    <Modal isOpen={isOpen} size="medium" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>{edited.id ? 'Edit Quality Profile' : 'Add Quality Profile'}</ModalHeader>
        <ModalBody>
          <FormRow>
            <FormLabel htmlFor="profileName">Name</FormLabel>
            <TextInput
              id="profileName"
              value={edited.name}
              onChange={(name) => setEdited({ ...edited, name })}
            />
          </FormRow>

          <FormRow>
            <FormLabel htmlFor="upgradeAllowed">Upgrades Allowed</FormLabel>
            <FormInputHelpText text="If off, a book isn't downloaded again once it has a file it wants" />
            <CheckInput
              checked={edited.upgradeAllowed}
              label="Upgrades Allowed"
              onChange={(upgradeAllowed) => setEdited({ ...edited, upgradeAllowed })}
            />
          </FormRow>

          {edited.upgradeAllowed ? (
            <FormRow>
              <FormLabel htmlFor="cutoff">Upgrade Until</FormLabel>
              <FormInputHelpText text="Once a book has this quality or better, it isn't searched for again" />
              <SelectInput
                id="cutoff"
                value={edited.cutoff}
                values={allowed.map((item) => ({ key: item.quality, value: item.name }))}
                onChange={(cutoff) => setEdited({ ...edited, cutoff })}
              />
            </FormRow>
          ) : null}

          <FormRow>
            <FormLabel>Qualities</FormLabel>
            <FormInputHelpText text="Qualities higher in the list are preferred, the search takes the best it finds. Only the checked ones are wanted" />
            <ul className={styles.qualities}>
              {edited.items.map((item, index) => (
                <li key={item.quality} className={styles.qualityRow}>
                  <CheckInput
                    checked={item.allowed}
                    label={`Want ${item.name}`}
                    onChange={(isAllowed) => setAllowed(index, isAllowed)}
                  />
                  <span className={item.allowed ? styles.qualityName : styles.qualityOff}>{item.name}</span>
                  {!item.imported ? <span className={styles.notImported}>not imported, see the types in Settings</span> : null}
                  <span className={styles.moves}>
                    <IconButton
                      name={ArrowUp}
                      title={`Prefer ${item.name}`}
                      isDisabled={index === 0}
                      onPress={() => move(index, -1)}
                    />
                    <IconButton
                      name={ArrowDown}
                      title={`Prefer ${item.name} less`}
                      isDisabled={index === edited.items.length - 1}
                      onPress={() => move(index, 1)}
                    />
                  </span>
                </li>
              ))}
            </ul>
          </FormRow>

          {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        </ModalBody>
        <ModalFooter>
          {edited.id && !edited.isDefault ? (
            <Button kind="danger" isSpinning={remove.isPending} onPress={() => remove.mutate(edited.id)}>
              Delete
            </Button>
          ) : null}
          {edited.id && !edited.isDefault ? (
            <Button isSpinning={makeDefault.isPending} onPress={() => makeDefault.mutate(edited.id)}>
              Make Default
            </Button>
          ) : null}
          <Button onPress={onModalClose}>Cancel</Button>
          <Button kind="primary" isSpinning={save.isPending} onPress={() => save.mutate(edited)}>
            Save
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default EditQualityProfileModal;
