// What Sonarr's edit modals share: the fields of what's edited, loaded when the modal opens, the ones
// changed sent back when it's saved, and pictures to choose one of
import { useQuery } from '@tanstack/react-query';
import classNames from 'classnames';
import { ReactNode, useState } from 'react';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import { FormInputHelpText, FormLabel, FormRow } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { api } from 'Utilities/api';
import { imageUrl } from 'Utilities/images';
import styles from './Edit.module.css';

// what the new pages show of the library, asked for again after a change
const LIBRARY_KEYS = [['author'], ['library'], ['wanted'], ['lookup']];

export function EditField({
  id,
  label,
  help,
  children,
}: {
  id?: string;
  label: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <FormRow>
      <FormLabel htmlFor={id}>{label}</FormLabel>
      {children}
      {help ? <FormInputHelpText text={help} /> : null}
    </FormRow>
  );
}

export function EditColumns({ children }: { children: ReactNode }) {
  return <div className={styles.columns}>{children}</div>;
}

// what's edited as it was loaded, the changes made, and saving them
export function useEdit<T extends object>(url: string, isOpen: boolean) {
  const [edited, setEdited] = useState<Partial<T>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');
  const loaded = useQuery({
    queryKey: ['edit', url],
    queryFn: () => api<T>(url),
    enabled: isOpen,
    gcTime: 0,
    staleTime: 0,
  });
  const values = loaded.data ? ({ ...loaded.data, ...edited } as T) : undefined;

  function set<K extends keyof T>(key: K, value: T[K]) {
    setEdited((current) => ({ ...current, [key]: value }));
  }

  // send the changes, true when they're saved. extra goes with them
  async function save<R extends { message: string }>(extra: object = {}, onSaved?: (saved: R) => void) {
    setIsSaving(true);
    setError('');
    try {
      const saved = await api<R>(url, { method: 'PUT', body: { ...edited, ...extra } });
      showMessage({ id: `edit-${Date.now()}`, text: saved.message, kind: 'success', isWorking: false });
      LIBRARY_KEYS.forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
      setEdited({});
      onSaved?.(saved);
      return true;
    } catch (saveError) {
      setError((saveError as Error).message);
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  return { loaded, values, edited, set, save, isSaving, error, setError, reset: () => setEdited({}) };
}

export function EditModal({
  isOpen,
  title,
  isLoading,
  loadError,
  error,
  isSaving,
  isChanged,
  children,
  footer,
  onSave,
  onModalClose,
}: {
  isOpen: boolean;
  title: string;
  isLoading: boolean;
  loadError: Error | null;
  error: string;
  isSaving: boolean;
  isChanged: boolean;
  children: ReactNode;
  footer?: ReactNode;
  onSave: () => void;
  onModalClose: () => void;
}) {
  return (
    <Modal isOpen={isOpen} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>{title}</ModalHeader>
        <ModalBody>
          {isLoading ? <LoadingIndicator /> : null}
          {loadError ? <Alert kind="danger">{loadError.message}</Alert> : null}
          {children}
          {error ? <Alert kind="danger">{error}</Alert> : null}
        </ModalBody>
        <ModalFooter className={styles.footer}>
          {footer}
          <span className={styles.spacer} />
          <Button onPress={onModalClose}>Cancel</Button>
          <Button kind="primary" isSpinning={isSaving} isDisabled={!isChanged} onPress={onSave}>
            Save
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

// pictures found online to choose one of, as the old edit pages' Find Images
export function PictureChoices<C extends { path: string }>({
  url,
  label,
  current,
  selected,
  name,
  onSelect,
}: {
  url: string;
  label: string;
  current: string;
  selected: string;
  name: (choice: C) => string;
  onSelect: (choice: C | null) => void;
}) {
  const [isLooking, setIsLooking] = useState(false);
  const found = useQuery({
    queryKey: ['edit', url],
    queryFn: () => api<C[]>(url),
    enabled: isLooking,
    gcTime: 0,
  });

  return (
    <div className={styles.pictures}>
      {current ? (
        <div className={styles.picture}>
          <img src={imageUrl(current)} alt="" referrerPolicy="no-referrer" />
          <span>Now</span>
        </div>
      ) : null}
      {(found.data ?? []).map((choice) => (
        <Link
          key={choice.path}
          className={classNames(styles.picture, styles.choice, selected === name(choice) && styles.selected)}
          title={`Use this ${label}`}
          onPress={() => onSelect(selected === name(choice) ? null : choice)}
        >
          <img src={imageUrl(choice.path)} alt="" referrerPolicy="no-referrer" />
          <span>{name(choice)}</span>
        </Link>
      ))}
      {!found.data ? (
        <Button isSpinning={found.isFetching} onPress={() => setIsLooking(true)}>
          Find {label}s
        </Button>
      ) : null}
      {found.data && !found.data.length ? <span className={styles.muted}>None were found</span> : null}
      {found.error ? <Alert kind="danger">{(found.error as Error).message}</Alert> : null}
    </div>
  );
}
