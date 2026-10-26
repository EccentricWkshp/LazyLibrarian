// Sonarr's InteractiveImportRow: an item, the type and book it will be imported as, and why it can't
import { CircleAlert } from 'lucide-react';
import { CheckInput, SelectInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Popover } from 'Components/Misc';
import { TableRow, TableRowCell } from 'Components/Table/Table';
import { InteractiveImportItem } from 'typings/InteractiveImport';
import { MEDIA_TYPE_NAMES, MediaType } from 'typings/Queue';
import { formatBytes } from 'Utilities/format';
import styles from '../InteractiveImport.module.css';

const BOOK_TYPES = [
  { key: 'ebook', value: MEDIA_TYPE_NAMES.ebook },
  { key: 'audiobook', value: MEDIA_TYPE_NAMES.audiobook },
];

interface InteractiveImportRowProps {
  item: InteractiveImportItem;
  isSelected: boolean;
  canChangeType: boolean;
  onSelectedChange: (isSelected: boolean) => void;
  onMediaTypeChange: (mediaType: MediaType) => void;
  onChooseBookPress: () => void;
}

function InteractiveImportRow({
  item,
  isSelected,
  canChangeType,
  onSelectedChange,
  onMediaTypeChange,
  onChooseBookPress,
}: InteractiveImportRowProps) {
  const { relativePath, files, mediaType, book, size, rejections } = item;
  const isBook = mediaType === 'ebook' || mediaType === 'audiobook';
  const bookName = book ? [book.author, book.issue ? `${book.title} - ${book.issue}` : book.title].filter(Boolean).join(' - ') : '';

  return (
    <TableRow>
      <TableRowCell className={styles.select}>
        <CheckInput checked={isSelected} label={`Select ${relativePath}`} onChange={onSelectedChange} />
      </TableRowCell>

      <TableRowCell className={styles.relativePath} title={files.length > 1 ? files.join('\n') : relativePath}>
        {relativePath}
        {files.length > 1 ? <span className={styles.fileCount}> and {files.length - 1} more</span> : null}
      </TableRowCell>

      <TableRowCell className={styles.mediaType}>
        {canChangeType && isBook ? (
          <SelectInput
            className={styles.typeSelect}
            value={mediaType}
            values={BOOK_TYPES}
            onChange={(value) => onMediaTypeChange(value as MediaType)}
          />
        ) : (
          MEDIA_TYPE_NAMES[mediaType]
        )}
      </TableRowCell>

      <TableRowCell className={styles.book}>
        {isBook ? (
          <Link className={styles.chooseBook} onPress={onChooseBookPress} title="Choose the book">
            {bookName || <span className={styles.placeholder}>Select Book</span>}
          </Link>
        ) : (
          bookName
        )}
      </TableRowCell>

      <TableRowCell className={styles.size}>{formatBytes(size)}</TableRowCell>

      <TableRowCell className={styles.rejections}>
        {rejections.length ? (
          <Popover
            anchor={<Icon name={CircleAlert} kind="danger" />}
            title="Release Rejected"
            body={
              <ul>
                {rejections.map((rejection) => (
                  <li key={rejection}>{rejection}</li>
                ))}
              </ul>
            }
          />
        ) : null}
      </TableRowCell>
    </TableRow>
  );
}

export default InteractiveImportRow;
