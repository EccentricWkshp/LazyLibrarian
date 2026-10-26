// Sonarr's InteractiveImportSelectFolderModalContent and its file browser in one: type a folder
// or find it, then import from it
import { useQuery } from '@tanstack/react-query';
import { ArrowUp, Folder } from 'lucide-react';
import { useState } from 'react';
import { TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { FileSystem } from 'typings/InteractiveImport';
import { api } from 'Utilities/api';
import styles from '../InteractiveImport.module.css';

interface SelectFolderModalContentProps {
  initialPath?: string;
  onFolderSelect: (path: string) => void;
  onModalClose: () => void;
}

function SelectFolderModalContent({ initialPath = '', onFolderSelect, onModalClose }: SelectFolderModalContentProps) {
  const [path, setPath] = useState(initialPath);
  const [browsing, setBrowsing] = useState(initialPath);
  const { data, error, isLoading } = useQuery({
    queryKey: ['filesystem', browsing],
    queryFn: () => api<FileSystem>('/filesystem', { query: { path: browsing } }),
  });

  function browse(folder: string) {
    setBrowsing(folder);
    setPath(folder);
  }

  return (
    <ModalContent onModalClose={onModalClose}>
      <ModalHeader>Manual Import - Select Folder</ModalHeader>
      <ModalBody>
        <TextInput
          value={path}
          placeholder="The folder to import from, as a full path"
          onChange={setPath}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && path) {
              browse(path);
            }
          }}
        />

        <div className={styles.browser}>
          {isLoading ? <LoadingIndicator /> : null}
          {error ? <Alert kind="danger">{error.message}</Alert> : null}
          {data ? (
            <ul className={styles.folders}>
              {data.parent !== null ? (
                <li>
                  <Link className={styles.folder} onPress={() => browse(data.parent ?? '')}>
                    <Icon name={ArrowUp} /> ..
                  </Link>
                </li>
              ) : null}
              {data.directories.map((folder) => (
                <li key={folder.path}>
                  <Link className={styles.folder} onPress={() => browse(folder.path)}>
                    <Icon name={Folder} /> {folder.name}
                  </Link>
                </li>
              ))}
              {!data.directories.length ? <li className={styles.empty}>No folders in here</li> : null}
            </ul>
          ) : null}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onPress={onModalClose}>Cancel</Button>
        <Button kind="primary" isDisabled={!path} onPress={() => onFolderSelect(path)}>
          Interactive Import
        </Button>
      </ModalFooter>
    </ModalContent>
  );
}

export default SelectFolderModalContent;
