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
import { MEDIA_TYPE_NAMES, MediaType, QueueItem } from 'typings/Queue';
import { api } from 'Utilities/api';
import SelectBookModal from '../Book/SelectBookModal';
import SelectIssueModal from '../Book/SelectIssueModal';
import InteractiveImportRow from './InteractiveImportRow';
import styles from '../InteractiveImport.module.css';

// the start of the rejection for a book that already has its files, manualimport.ALREADY
const ALREADY = 'Already in the library:';

const BOOK_TYPES: MediaType[] = ['ebook', 'audiobook'];
const ALL_TYPES: MediaType[] = ['ebook', 'audiobook', 'magazine', 'comic'];

function isBookType(mediaType: MediaType) {
  return BOOK_TYPES.includes(mediaType);
}

// what is chosen for an item stays when its type changes within its kind, a book as an ebook or
// audiobook, not when a book becomes a magazine or a magazine a comic
function kindOf(mediaType: MediaType) {
  return isBookType(mediaType) ? 'book' : mediaType;
}

function nounOf(mediaType: MediaType) {
  return isBookType(mediaType) ? 'book' : mediaType;
}

// a queued download's items are another of the same kind, the rest anything
function typesFor(item: InteractiveImportItem): MediaType[] {
  if (item.queueId === null) {
    return ALL_TYPES;
  }
  return isBookType(item.mediaType) ? BOOK_TYPES : [item.mediaType];
}

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
  // the items a book, magazine or comic is being chosen for, all of one type
  const [choosing, setChoosing] = useState<{ paths: string[]; mediaType: MediaType } | null>(null);
  const [importError, setImportError] = useState('');

  const items: InteractiveImportItem[] = useMemo(
    () =>
      (data?.items ?? []).map((item) => {
        const choice = choices[item.path] ?? {};
        const mediaType = choice.mediaType ?? item.mediaType;
        const sameKind = kindOf(mediaType) === kindOf(item.mediaType);
        const book = choice.book !== undefined ? choice.book : sameKind ? item.book : null;
        // the rejections that choosing has dealt with go, and what's still to choose is worked out
        // again. Another book or type may not have files yet
        const changed = choice.book !== undefined || choice.mediaType !== undefined;
        const rejections = item.rejections.filter(
          (rejection) =>
            !rejection.startsWith('Choose the ') &&
            !(choice.mediaType && rejection.startsWith('No ')) &&
            !(changed && rejection.startsWith(ALREADY))
        );
        const toChoose = !book
          ? `Choose the ${nounOf(mediaType)}`
          : !isBookType(mediaType) && !book.issue
            ? 'Choose the issue'
            : '';

        return { ...item, book, mediaType, rejections: toChoose ? [...rejections, toChoose] : rejections };
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
  // several items get the same book, magazine or comic when they are all one kind
  const selectedKind =
    selectedItems.length && selectedItems.every((item) => kindOf(item.mediaType) === kindOf(selectedItems[0].mediaType))
      ? selectedItems[0].mediaType
      : null;
  const choosingItem = choosing?.paths.length === 1 ? items.find((item) => item.path === choosing.paths[0]) : undefined;

  function choose(paths: string[], choice: Choice) {
    setChoices((current) => {
      const next = { ...current };
      paths.forEach((path) => (next[path] = { ...next[path], ...choice }));
      return next;
    });
    setSelected((current) => new Set([...current, ...paths]));
  }

  function handleImport() {
    const missing = selectedItems.filter((item) => !item.book || (!isBookType(item.mediaType) && !item.book.issue));

    if (missing.length) {
      setImportError('Choose the book for each selected item, or the magazine or comic and its issue');
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
          issue: isBookType(item.mediaType) ? '' : (item.book?.issue ?? ''),
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
                types={typesFor(data?.items.find((original) => original.path === item.path) ?? item)}
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
                onMediaTypeChange={(mediaType) =>
                  // a book chosen isn't the magazine or comic, nor a magazine the comic
                  choose(
                    [item.path],
                    kindOf(mediaType) === kindOf(item.mediaType) ? { mediaType } : { mediaType, book: undefined }
                  )
                }
                onChooseBookPress={() => setChoosing({ paths: [item.path], mediaType: item.mediaType })}
              />
            ))}
          </Table>
        ) : null}

        {importError ? <Alert kind="danger">{importError}</Alert> : null}
      </ModalBody>

      <ModalFooter className={styles.footer}>
        <div className={styles.leftButtons}>
          {selectedItems.length > 1 && selectedKind ? (
            <Button
              onPress={() => setChoosing({ paths: selectedItems.map((item) => item.path), mediaType: selectedKind })}
            >
              Choose {isBookType(selectedKind) ? 'Book' : MEDIA_TYPE_NAMES[selectedKind]}
            </Button>
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
        isOpen={!!choosing && isBookType(choosing.mediaType)}
        onBookSelect={(book) => {
          if (choosing) {
            choose(choosing.paths, { book });
          }
          setChoosing(null);
        }}
        onModalClose={() => setChoosing(null)}
      />

      <SelectIssueModal
        isOpen={!!choosing && !isBookType(choosing.mediaType)}
        mediaType={choosing?.mediaType === 'comic' ? 'comic' : 'magazine'}
        initial={choosingItem?.book}
        issue={choosingItem ? choosingItem.book?.issue || choosingItem.issues?.[choosingItem.mediaType] || '' : ''}
        isMany={(choosing?.paths.length ?? 0) > 1}
        onIssueSelect={(target, issue) => {
          // several items each keep the issue their name says, unless one is given
          choosing?.paths.forEach((path) => {
            const item = items.find((one) => one.path === path);
            choose([path], { book: { ...target, issue: issue || item?.issues?.[target.mediaType as MediaType] || '' } });
          });
          setChoosing(null);
        }}
        onModalClose={() => setChoosing(null)}
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
