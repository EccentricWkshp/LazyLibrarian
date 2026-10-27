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

interface InteractiveImportRowProps {
  item: InteractiveImportItem;
  isSelected: boolean;
  // the types it can be imported as, one when it can't be changed
  types: MediaType[];
  onSelectedChange: (isSelected: boolean) => void;
  onMediaTypeChange: (mediaType: MediaType) => void;
  onChooseBookPress: () => void;
}

function InteractiveImportRow({
  item,
  isSelected,
  types,
  onSelectedChange,
  onMediaTypeChange,
  onChooseBookPress,
}: InteractiveImportRowProps) {
  const { relativePath, files, mediaType, book, size, rejections } = item;
  const isBook = mediaType === 'ebook' || mediaType === 'audiobook';
  const issue = book && !isBook ? book.issue || 'which issue?' : '';
  const bookName = book ? [book.author, issue ? `${book.title} - ${issue}` : book.title].filter(Boolean).join(' - ') : '';
  const noun = isBook ? 'Book' : MEDIA_TYPE_NAMES[mediaType];

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
        {types.length > 1 ? (
          <SelectInput
            className={styles.typeSelect}
            value={mediaType}
            values={types.map((type) => ({ key: type, value: MEDIA_TYPE_NAMES[type] }))}
            onChange={(value) => onMediaTypeChange(value as MediaType)}
          />
        ) : (
          MEDIA_TYPE_NAMES[mediaType]
        )}
      </TableRowCell>

      <TableRowCell className={styles.book}>
        <Link className={styles.chooseBook} onPress={onChooseBookPress} title={`Choose the ${noun.toLowerCase()}`}>
          {bookName || <span className={styles.placeholder}>Select {noun}</span>}
        </Link>
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
