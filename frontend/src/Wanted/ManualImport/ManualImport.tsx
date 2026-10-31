// Wanted, Manual Import: a folder's books, magazine and comic issues imported once each is chosen,
// for downloads LazyLibrarian didn't ask for or couldn't import itself, as Sonarr's Manual Import
import { useState } from 'react';
import Button from 'Components/Link/Button';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import useFolderPicker from 'InteractiveImport/Folder/useFolderPicker';
import InteractiveImportModal from 'InteractiveImport/InteractiveImportModal';
import { addRecentFolder } from 'InteractiveImport/recentFolders';
import styles from './ManualImport.module.css';

function ManualImport() {
  const { path, picker } = useFolderPicker();
  const [folder, setFolder] = useState('');

  return (
    <PageContent title="Manual Import">
      <PageContentBody>
        <p className={styles.note}>
          The post processor imports what LazyLibrarian downloaded itself. Anything else in a folder, a download made
          elsewhere or one it couldn't import, is imported here: choose the folder, then the book, magazine or comic
          issue each item is, where it isn't the one it looks like.
        </p>
        {picker}
        <div className={styles.actions}>
          <Button
            kind="primary"
            isDisabled={!path}
            onPress={() => {
              addRecentFolder(path);
              setFolder(path);
            }}
          >
            Interactive Import
          </Button>
        </div>
      </PageContentBody>

      <InteractiveImportModal isOpen={!!folder} initialFolder={folder} onModalClose={() => setFolder('')} />
    </PageContent>
  );
}

export default ManualImport;
