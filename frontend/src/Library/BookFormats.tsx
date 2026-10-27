// What the book lists share: a book's status as an eBook and as an audiobook, wanting or skipping a
// format with one click, and searching for it automatically or interactively
import { Bookmark, BookmarkX, Search, UserSearch } from 'lucide-react';
import { useState } from 'react';
import { runCommand } from 'App/commands';
import { setBookStatus } from 'Author/authors';
import IconButton from 'Components/Link/IconButton';
import { Label } from 'Components/Misc';
import { TableRowCell } from 'Components/Table/Table';
import { InteractiveSearchModal } from 'InteractiveSearch/InteractiveSearch';
import styles from 'Library/Library.module.css';

export type Format = 'ebook' | 'audiobook';

export interface FormatInfo {
  format: Format;
  label: string;
  tab: 'ebook' | 'audio';
  status: 'status' | 'audioStatus';
  file: 'ebookFormat' | 'audioFormat';
}

// a book as the lists have it, its status and file format for each
export interface BookStatuses {
  id: string;
  title: string;
  status: string;
  audioStatus: string;
  ebookFormat: string;
  audioFormat: string;
  scanResult?: string;
}

export const FORMATS: FormatInfo[] = [
  { format: 'ebook', label: 'eBook', tab: 'ebook', status: 'status', file: 'ebookFormat' },
  { format: 'audiobook', label: 'Audiobook', tab: 'audio', status: 'audioStatus', file: 'audioFormat' },
];

export const OWNED = ['Open', 'Have'];

// the formats whose libraries are switched on
export function shownFormats() {
  const tabs = window.LazyLibrarian?.tabs ?? { ebook: true, audio: true, series: true, mag: true, comic: false };
  const shown = FORMATS.filter((f) => tabs[f.tab]);

  return shown.length ? shown : FORMATS.slice(0, 1);
}

export function bookKind(status: string) {
  if (OWNED.includes(status)) {
    return 'success';
  }

  switch (status) {
    case 'Wanted':
      return 'danger';
    case 'Snatched':
      return 'purple';
    default:
      return 'default';
  }
}

// the status, or the file's format when the library has it, and a button to want or skip it
export function FormatStatus({ book, format }: { book: BookStatuses; format: FormatInfo }) {
  const status = book[format.status] || 'Skipped';
  const fileFormat = book[format.file];
  const owned = OWNED.includes(status);
  const wanted = status === 'Wanted';

  return (
    <>
      <Label kind={bookKind(status)} title={book.scanResult || undefined}>
        {owned && fileFormat ? fileFormat : status}
      </Label>
      {owned || status === 'Snatched' ? null : (
        <IconButton
          name={wanted ? BookmarkX : Bookmark}
          title={wanted ? `Skip the ${format.label}` : `Want the ${format.label}`}
          onPress={() => setBookStatus([book.id], [format.format], wanted ? 'Skipped' : 'Wanted')}
        />
      )}
    </>
  );
}

export function FormatCell({ book, format }: { book: BookStatuses; format: FormatInfo }) {
  return (
    <TableRowCell className={styles.formatCell}>
      <FormatStatus book={book} format={format} />
    </TableRowCell>
  );
}

// automatic search for the wanted formats, and Interactive Search for the one most likely wanted
export function BookSearchButtons({ book, formats }: { book: BookStatuses; formats: FormatInfo[] }) {
  const [isSearching, setIsSearching] = useState(false);
  const [interactive, setInteractive] = useState<Format | null>(null);
  const wanted = formats.filter((f) => book[f.status] === 'Wanted').map((f) => f.format);
  const choice =
    formats.find((f) => book[f.status] === 'Wanted') ??
    formats.find((f) => !OWNED.includes(book[f.status])) ??
    formats[0];

  return (
    <>
      <IconButton
        name={Search}
        title={wanted.length ? 'Automatic Search' : 'Want it first to search for it'}
        isDisabled={!wanted.length}
        isSpinning={isSearching}
        onPress={() => {
          setIsSearching(true);
          runCommand(
            'BookSearch',
            { books: wanted.map((mediaType) => ({ bookId: book.id, mediaType })) },
            `Search for ${book.title}`
          ).finally(() => setIsSearching(false));
        }}
      />
      <IconButton
        name={UserSearch}
        title={`Interactive Search (${choice.label})`}
        onPress={() => setInteractive(choice.format)}
      />
      {interactive ? (
        <InteractiveSearchModal
          isOpen={true}
          bookId={book.id}
          mediaType={interactive}
          title={book.title}
          onModalClose={() => setInteractive(null)}
        />
      ) : null}
    </>
  );
}
