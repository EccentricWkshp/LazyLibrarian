import classNames from 'classnames';
import { X } from 'lucide-react';
import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import IconButton from 'Components/Link/IconButton';
import styles from './Modal.module.css';

type ModalSize = 'small' | 'medium' | 'large' | 'extraLarge' | 'extraExtraLarge';

interface ModalProps {
  isOpen: boolean;
  size?: ModalSize;
  onModalClose: () => void;
  children: React.ReactNode;
}

// the open modals, the last is on top. Escape only closes that one
const openModals: object[] = [];

// Sonarr's modal: over the page, closed by Escape, the backdrop or its close button
export function Modal({ isOpen, size = 'medium', onModalClose, children }: ModalProps) {
  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const me = {};

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && openModals[openModals.length - 1] === me) {
        onModalClose();
      }
    }

    openModals.push(me);
    window.addEventListener('keydown', onKeyDown);
    document.body.style.overflow = 'hidden';

    return () => {
      openModals.splice(openModals.indexOf(me), 1);
      window.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = openModals.length ? 'hidden' : '';
    };
  }, [isOpen, onModalClose]);

  if (!isOpen) {
    return null;
  }

  return createPortal(
    <div className={styles.backdrop} onMouseDown={(event) => event.target === event.currentTarget && onModalClose()}>
      <div className={classNames(styles.modal, styles[size])} role="dialog" aria-modal="true">
        {children}
      </div>
    </div>,
    document.body
  );
}

export function ModalContent({ onModalClose, children }: { onModalClose: () => void; children: React.ReactNode }) {
  return (
    <div className={styles.content}>
      <IconButton className={styles.closeButton} name={X} size={18} aria-label="Close" onPress={onModalClose} />
      {children}
    </div>
  );
}

export function ModalHeader({ children }: { children: React.ReactNode }) {
  return <div className={styles.header}>{children}</div>;
}

export function ModalBody({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={classNames(styles.body, className)}>{children}</div>;
}

export function ModalFooter({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={classNames(styles.footer, className)}>{children}</div>;
}
