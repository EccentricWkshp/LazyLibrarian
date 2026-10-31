// Sonarr's InteractiveImportSelectFolderModalContent and its file browser in one: type a folder or
// find it, starting from the folders downloads are in and the ones imported from lately
import Button from 'Components/Link/Button';
import { ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { addRecentFolder } from '../recentFolders';
import useFolderPicker from './useFolderPicker';

interface SelectFolderModalContentProps {
  initialPath?: string;
  onFolderSelect: (path: string) => void;
  onModalClose: () => void;
}

function SelectFolderModalContent({ initialPath = '', onFolderSelect, onModalClose }: SelectFolderModalContentProps) {
  const { path, picker } = useFolderPicker(initialPath);

  function select() {
    addRecentFolder(path);
    onFolderSelect(path);
  }

  return (
    <ModalContent onModalClose={onModalClose}>
      <ModalHeader>Manual Import - Select Folder</ModalHeader>
      <ModalBody>{picker}</ModalBody>
      <ModalFooter>
        <Button onPress={onModalClose}>Cancel</Button>
        <Button kind="primary" isDisabled={!path} onPress={select}>
          Interactive Import
        </Button>
      </ModalFooter>
    </ModalContent>
  );
}

export default SelectFolderModalContent;
