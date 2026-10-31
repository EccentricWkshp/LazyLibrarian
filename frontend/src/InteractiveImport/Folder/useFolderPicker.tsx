// Sonarr's file browser for Manual Import: type a folder or find it, starting from the folders
// downloads are in and the ones imported from lately. The picker and the folder chosen in it, for the
// Select Folder modal and the Manual Import page
import { useQuery } from '@tanstack/react-query';
import { ArrowUp, Clock, Download, Folder } from 'lucide-react';
import { useEffect, useState } from 'react';
import { TextInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { FileSystem, SuggestedFolder } from 'typings/InteractiveImport';
import { api } from 'Utilities/api';
import { recentFolders } from '../recentFolders';
import styles from '../InteractiveImport.module.css';

function useFolderPicker(initialPath = '') {
  const recent = recentFolders();
  const [path, setPath] = useState(initialPath || recent[0] || '');
  const [browsing, setBrowsing] = useState<string | null>(initialPath || recent[0] || null);
  const suggestions = useQuery({
    queryKey: ['manualimport', 'folders'],
    queryFn: () => api<SuggestedFolder[]>('/manualimport/folders'),
  });
  const { data, error, isLoading } = useQuery({
    queryKey: ['filesystem', browsing],
    queryFn: () => api<FileSystem>('/filesystem', { query: { path: browsing } }),
    enabled: browsing !== null,
  });

  // with nowhere to start from yet, start where downloads are, keeping a folder typed meanwhile
  useEffect(() => {
    if (browsing === null && suggestions.data) {
      const first = suggestions.data[0]?.path ?? '';
      setBrowsing(first);
      setPath((typed) => typed || first);
    }
  }, [browsing, suggestions.data]);

  // a folder that isn't there shows the nearest one that is
  useEffect(() => {
    if (data && browsing && data.path && data.path !== browsing) {
      setPath(data.path);
    }
  }, [data, browsing]);

  function browse(folder: string) {
    setBrowsing(folder);
    setPath(folder);
  }

  const shortcuts = [
    ...recent.map((folder) => ({ path: folder, label: 'Recent', icon: Clock })),
    ...(suggestions.data ?? [])
      .filter((folder) => !recent.includes(folder.path))
      .map((folder) => ({ path: folder.path, label: folder.label, icon: Download })),
  ];

  const picker = (
    <>
      {shortcuts.length ? (
        <ul className={styles.shortcuts}>
          {shortcuts.map((shortcut) => (
            <li key={shortcut.path}>
              <Link className={styles.shortcut} onPress={() => browse(shortcut.path)}>
                <Icon name={shortcut.icon} />
                <span className={styles.shortcutPath}>{shortcut.path}</span>
                <span className={styles.shortcutLabel}>{shortcut.label}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}

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
    </>
  );

  return { path, picker };
}

export default useFolderPicker;
