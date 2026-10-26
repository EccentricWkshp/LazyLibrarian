// Sonarr's InteractiveImportModalContent: each item that could be imported, the book it is for,
// anything that stops it, and Import for the ones chosen
import { useQuery } from '@tanstack/react-query';
import { FolderOpen } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { runCommand } from 'App/commands';
import { CheckInput } from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import { Alert, LoadingIndicator } from 'Components/Misc';
import { ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { Column, Table } from 'Components/Table/Table';
import Icon from 'Components/Icon';
import { ImportTarget, InteractiveImportFolder, InteractiveImportItem } from 'typings/InteractiveImport';
import { MediaType, QueueItem } from 'typings/Queue';
import { api } from 'Utilities/api';
import SelectBookModal from '../Book/SelectBookModal';
import InteractiveImportRow from './InteractiveImportRow';
import styles from '../InteractiveImport.module.css';

// the start of the rejection for a book that already has its files, manualimport.ALREADY
const ALREADY = 'Already in the library:';

const COLUMNS: Column[] = [
  { name: 'relativePath', label: 'Relative Path' },
  { name: 'mediaType', label: 'Type' },
  { name: 'book', label: 'Book' },
  { name: 'size', label: 'Size' },
  { name: 'rejections', label: 'Rejections', isVisuallyHidden: true },
];

// what the person has changed about an item, by its path
interface Choice {
  mediaType?: MediaType;
  book?: ImportTarget | null;
}

interface InteractiveImportModalContentProps {
  folder?: string;
  queueItem?: QueueItem;
  onChooseFolderPress: (path: string) => void;
  onModalClose: () => void;
}

function InteractiveImportModalContent({
  folder = '',
  queueItem,
  onChooseFolderPress,
  onModalClose,
}: InteractiveImportModalContentProps) {
  const { data, error, isLoading } = useQuery({
    queryKey: ['manualimport', folder, queueItem?.id],
    queryFn: () =>
      api<InteractiveImportFolder>('/manualimport', { query: { folder, queueId: queueItem?.id } }),
    refetchOnWindowFocus: false,
  });
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [choosingBookFor, setChoosingBookFor] = useState<string[] | null>(null);
  const [importError, setImportError] = useState('');

  const items: InteractiveImportItem[] = useMemo(
    () =>
      (data?.items ?? []).map((item) => {
        const choice = choices[item.path] ?? {};
        const book = choice.book === undefined ? item.book : choice.book;
        const mediaType = choice.mediaType ?? item.mediaType;
        // the rejections that choosing has dealt with go. Another book or type may not have files yet
        const changed = choice.book !== undefined || choice.mediaType !== undefined;
        const rejections = item.rejections.filter(
          (rejection) =>
            !(book && rejection === 'Choose the book') &&
            !(choice.mediaType && rejection.startsWith('No ')) &&
            !(changed && rejection.startsWith(ALREADY))
        );

        return { ...item, book, mediaType, rejections: book ? rejections : [...new Set([...rejections, 'Choose the book'])] };
      }),
    [data, choices]
  );

  // items that can be imported start selected, as in Sonarr
  useEffect(() => {
    setSelected(new Set((data?.items ?? []).filter((item) => !item.rejections.length).map((item) => item.path)));
    setChoices({});
  }, [data]);

  const selectedItems = items.filter((item) => selected.has(item.path));
  const allSelected = items.length > 0 && selectedItems.length === items.length;
  const fromQueue = !!queueItem;

  function choose(paths: string[], choice: Choice) {
    setChoices((current) => {
      const next = { ...current };
      paths.forEach((path) => (next[path] = { ...next[path], ...choice }));
      return next;
    });
    setSelected((current) => new Set([...current, ...paths]));
  }

  function handleImport() {
    const missing = selectedItems.filter((item) => !item.book);

    if (missing.length) {
      setImportError('Choose the book for each selected item');
      return;
    }

    setImportError('');
    runCommand(
      'ManualImport',
      {
        files: selectedItems.map((item) => ({
          path: item.path,
          files: item.files,
          mediaType: item.mediaType,
          bookId: item.book?.id ?? '',
          queueId: item.queueId,
        })),
      },
      'Manual Import'
    );
    onModalClose();
  }

  const title = queueItem ? `Manual Import - ${queueItem.sourceTitle}` : `Manual Import - ${data?.folder || folder}`;

  return (
    <ModalContent onModalClose={onModalClose}>
      <ModalHeader>{title}</ModalHeader>
      <ModalBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{error.message}</Alert> : null}
        {data?.error ? (
          <Alert kind="warning">
            {data.error}
            <div className={styles.alertAction}>
              <Button onPress={() => onChooseFolderPress(data.folder ? parentOf(data.folder) : '')}>
                Choose the folder
              </Button>
            </div>
          </Alert>
        ) : null}
        {data && !data.error && !items.length ? (
          <Alert kind="info">No files found that could be imported in {data.folder}</Alert>
        ) : null}

        {items.length ? (
          <Table
            columns={COLUMNS}
            selectAll={
              <CheckInput
                checked={allSelected}
                isIndeterminate={!allSelected && selectedItems.length > 0}
                label="Select all"
                onChange={(checked) => setSelected(checked ? new Set(items.map((item) => item.path)) : new Set())}
              />
            }
          >
            {items.map((item) => (
              <InteractiveImportRow
                key={item.path}
                item={item}
                isSelected={selected.has(item.path)}
                canChangeType={!fromQueue || item.mediaType === 'ebook' || item.mediaType === 'audiobook'}
                onSelectedChange={(isSelected) =>
                  setSelected((current) => {
                    const next = new Set(current);
                    if (isSelected) {
                      next.add(item.path);
                    } else {
                      next.delete(item.path);
                    }
                    return next;
                  })
                }
                onMediaTypeChange={(mediaType) => choose([item.path], { mediaType })}
                onChooseBookPress={() => setChoosingBookFor([item.path])}
              />
            ))}
          </Table>
        ) : null}

        {importError ? <Alert kind="danger">{importError}</Alert> : null}
      </ModalBody>

      <ModalFooter className={styles.footer}>
        <div className={styles.leftButtons}>
          {selectedItems.length > 1 ? (
            <Button onPress={() => setChoosingBookFor(selectedItems.map((item) => item.path))}>Choose Book</Button>
          ) : null}
          {data && !data.error ? (
            <Button onPress={() => onChooseFolderPress(data.folder)}>
              <Icon name={FolderOpen} /> Another Folder
            </Button>
          ) : null}
        </div>
        <div className={styles.rightButtons}>
          <Button onPress={onModalClose}>Cancel</Button>
          <Button kind="success" isDisabled={!selectedItems.length} onPress={handleImport}>
            Import
          </Button>
        </div>
      </ModalFooter>

      <SelectBookModal
        isOpen={!!choosingBookFor}
        onBookSelect={(book) => {
          if (choosingBookFor) {
            choose(choosingBookFor, { book });
          }
          setChoosingBookFor(null);
        }}
        onModalClose={() => setChoosingBookFor(null)}
      />
    </ModalContent>
  );
}

function parentOf(path: string) {
  const trimmed = path.replace(/[\\/]+$/, '');
  const at = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));

  return at > 0 ? trimmed.slice(0, at) : trimmed;
}

export default InteractiveImportModalContent;
