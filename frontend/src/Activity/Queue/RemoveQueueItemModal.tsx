// Sonarr's RemoveQueueItemModal: remove from the download client or not, and blocklist or not
import { useState } from 'react';
import { FormInputHelpText, FormLabel, FormRow, SelectInput } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { RemovalOptions } from './useQueue';
import styles from './Queue.module.css';

interface RemoveQueueItemModalProps {
  isOpen: boolean;
  sourceTitle?: string;
  selectedCount?: number;
  onRemovePress: (options: RemovalOptions) => void;
  onModalClose: () => void;
}

function RemoveQueueItemModal({
  isOpen,
  sourceTitle = '',
  selectedCount,
  onRemovePress,
  onModalClose,
}: RemoveQueueItemModalProps) {
  const [removalMethod, setRemovalMethod] = useState('removeFromClient');
  const [blocklistMethod, setBlocklistMethod] = useState('doNotBlocklist');
  const multiple = !!selectedCount && selectedCount > 1;

  const title = selectedCount
    ? multiple
      ? 'Remove Selected Items'
      : 'Remove Selected Item'
    : `Remove - ${sourceTitle}`;
  const message = selectedCount
    ? `Are you sure you want to remove ${selectedCount} item${multiple ? 's' : ''} from the queue?`
    : `Are you sure you want to remove '${sourceTitle}' from the queue?`;

  function handleRemove() {
    onRemovePress({
      removeFromClient: removalMethod === 'removeFromClient',
      blocklist: blocklistMethod !== 'doNotBlocklist',
      skipRedownload: blocklistMethod === 'blocklistOnly',
    });
  }

  return (
    <Modal isOpen={isOpen} size="medium" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>{title}</ModalHeader>
        <ModalBody>
          <p className={styles.intro}>{message}</p>

          <FormRow>
            <FormLabel htmlFor="removalMethod">Removal Method</FormLabel>
            <FormInputHelpText
              text="Removing from the download client deletes the download and its files"
              isWarning={true}
            />
            <SelectInput
              id="removalMethod"
              value={removalMethod}
              values={[
                {
                  key: 'removeFromClient',
                  value: 'Remove from Download Client',
                  hint: `Removes the download${multiple ? 's' : ''} and the files from the download client`,
                },
                {
                  key: 'ignore',
                  value: multiple ? 'Ignore Downloads' : 'Ignore Download',
                  hint: `Stops LazyLibrarian from processing ${multiple ? 'these downloads' : 'this download'}, the download client keeps ${multiple ? 'them' : 'it'}`,
                },
              ]}
              onChange={setRemovalMethod}
            />
          </FormRow>

          <FormRow>
            <FormLabel htmlFor="blocklistMethod">{multiple ? 'Blocklist Releases' : 'Blocklist Release'}</FormLabel>
            <FormInputHelpText text="Stops LazyLibrarian from grabbing the same release again" />
            <SelectInput
              id="blocklistMethod"
              value={blocklistMethod}
              values={[
                { key: 'doNotBlocklist', value: 'Do not Blocklist', hint: 'Remove without blocklisting' },
                {
                  key: 'blocklistAndSearch',
                  value: 'Blocklist and Search',
                  hint: 'Start a search for a replacement after blocklisting',
                },
                {
                  key: 'blocklistOnly',
                  value: 'Blocklist Only',
                  hint: 'Blocklist without searching for a replacement',
                },
              ]}
              onChange={setBlocklistMethod}
            />
          </FormRow>
        </ModalBody>
        <ModalFooter>
          <Button onPress={onModalClose}>Close</Button>
          <Button kind="danger" onPress={handleRemove}>
            Remove
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default RemoveQueueItemModal;
