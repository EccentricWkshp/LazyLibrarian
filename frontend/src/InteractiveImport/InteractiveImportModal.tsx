// Sonarr's InteractiveImportModal: for a queued download, or for a folder chosen first
import { useEffect, useState } from 'react';
import { Modal } from 'Components/Modal/Modal';
import { QueueItem } from 'typings/Queue';
import SelectFolderModalContent from './Folder/SelectFolderModalContent';
import InteractiveImportModalContent from './Interactive/InteractiveImportModalContent';

interface InteractiveImportModalProps {
  isOpen: boolean;
  queueItem?: QueueItem;
  onModalClose: () => void;
}

function InteractiveImportModal({ isOpen, queueItem, onModalClose }: InteractiveImportModalProps) {
  const [folder, setFolder] = useState('');
  const [isChoosingFolder, setIsChoosingFolder] = useState(!queueItem);

  const fromQueue = !!queueItem;

  // each time it opens it starts again
  useEffect(() => {
    if (isOpen) {
      setFolder('');
      setIsChoosingFolder(!fromQueue);
    }
  }, [isOpen, fromQueue]);

  return (
    <Modal isOpen={isOpen} size={isChoosingFolder ? 'large' : 'extraLarge'} onModalClose={onModalClose}>
      {isChoosingFolder ? (
        <SelectFolderModalContent
          initialPath={folder}
          onFolderSelect={(path) => {
            setFolder(path);
            setIsChoosingFolder(false);
          }}
          onModalClose={onModalClose}
        />
      ) : (
        <InteractiveImportModalContent
          folder={folder}
          queueItem={queueItem}
          onChooseFolderPress={(path) => {
            setFolder(path);
            setIsChoosingFolder(true);
          }}
          onModalClose={onModalClose}
        />
      )}
    </Modal>
  );
}

export default InteractiveImportModal;
