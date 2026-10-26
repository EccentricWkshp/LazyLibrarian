// Sonarr's ConfirmModal: a question, Cancel, and a button that does it
import { ReactNode } from 'react';
import Button, { ButtonKind } from 'Components/Link/Button';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from './Modal';

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  kind?: ButtonKind;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmModal({ isOpen, title, message, confirmLabel, kind = 'danger', onConfirm, onCancel }: ConfirmModalProps) {
  return (
    <Modal isOpen={isOpen} size="small" onModalClose={onCancel}>
      <ModalContent onModalClose={onCancel}>
        <ModalHeader>{title}</ModalHeader>
        <ModalBody>{message}</ModalBody>
        <ModalFooter>
          <Button onPress={onCancel}>Cancel</Button>
          <Button kind={kind} onPress={onConfirm}>
            {confirmLabel}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default ConfirmModal;
