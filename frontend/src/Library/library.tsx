// What the library pages share: changing magazines, comics and series, their cover cards, a
// delete that can take the files too, and the choices kept in the browser for next time
import { BookOpen, Rss } from 'lucide-react';
import React, { useState } from 'react';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import { CheckInput, FormInputHelpText, FormRow } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { PageToolbarButton } from 'Components/Page/Toolbar/PageToolbar';
import { api } from 'Utilities/api';
import { imageUrl } from 'Utilities/images';
import styles from 'Library/Library.module.css';

export function remembered(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

export function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private windows can't keep it
  }
}

// a request that changes the library, told of in the sidebar, the pages asked again after it
export async function change(
  path: string,
  method: 'PUT' | 'DELETE',
  body: Record<string, unknown>,
  done: (changed: number) => string,
  failed: string
) {
  const id = `library-${Date.now()}`;

  try {
    const result = await api<{ changed: number }>(path, { method, body });
    showMessage({ id, text: done(result.changed), kind: 'success', isWorking: false });
    return result;
  } catch (error) {
    showMessage({ id, text: `${failed}: ${(error as Error).message}`, kind: 'danger', isWorking: false });
    return null;
  } finally {
    queryClient.invalidateQueries({ queryKey: ['library'] });
    queryClient.invalidateQueries({ queryKey: ['wanted'] });
    queryClient.invalidateQueries({ queryKey: ['author'] });
  }
}

export function Cover({ src, size = 48, icon = BookOpen }: { src: string; size?: number; icon?: typeof BookOpen }) {
  const [failed, setFailed] = useState(false);
  const url = imageUrl(src);

  return url && !failed ? (
    <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
  ) : (
    <Icon name={icon} size={size} />
  );
}

// the RSS feed of a library's recent downloads, one magazine's or comic's when only is given, as
// the old pages link it; nothing when Settings has the feeds off
export function RssButton({ type, only, label }: { type: 'eBook' | 'AudioBook' | 'Magazine' | 'Comic'; only?: string; label: string }) {
  if (!window.LazyLibrarian?.rss) {
    return null;
  }
  const onetitle = only ? `&onetitle=${encodeURIComponent(only)}` : '';

  return (
    <PageToolbarButton
      label={label}
      iconName={Rss}
      to={`/rss_feed?type=${type}${onetitle}&limit=10.xml`}
      noRouter={true}
    />
  );
}

// Sonarr's series poster: the cover, a corner label, a footer
export function PosterCard({
  to,
  cover,
  icon,
  corner,
  name,
  children,
}: {
  to: string;
  cover: string;
  icon?: typeof BookOpen;
  corner?: React.ReactNode;
  name: string;
  children?: React.ReactNode;
}) {
  return (
    <Link className={styles.poster} to={to}>
      <div className={styles.posterImage}>
        <Cover src={cover} icon={icon} />
        {corner ? <span className={styles.posterStatus}>{corner}</span> : null}
      </div>
      {children}
      <div className={styles.posterName}>{name}</div>
    </Link>
  );
}

interface DeleteModalProps {
  isOpen: boolean;
  title: string;
  filesLabel: string;
  filesHelp: string;
  keepHelp: string;
  onDelete: (deleteFiles: boolean) => Promise<unknown>;
  onModalClose: () => void;
}

export function DeleteModal({ isOpen, title, filesLabel, filesHelp, keepHelp, onDelete, onModalClose }: DeleteModalProps) {
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  return (
    <Modal isOpen={isOpen} size="small" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Delete {title}</ModalHeader>
        <ModalBody>
          <FormRow>
            <label className={styles.check}>
              <CheckInput checked={deleteFiles} onChange={setDeleteFiles} />
              {filesLabel}
            </label>
            <FormInputHelpText text={deleteFiles ? filesHelp : keepHelp} isWarning={deleteFiles} />
          </FormRow>
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button
            kind="danger"
            isSpinning={isDeleting}
            onPress={() => {
              setIsDeleting(true);
              onDelete(deleteFiles).finally(() => {
                setIsDeleting(false);
                onModalClose();
              });
            }}
          >
            Delete
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export function plural(count: number, word: string) {
  return `${count} ${count === 1 ? word : `${word}s`}`;
}
