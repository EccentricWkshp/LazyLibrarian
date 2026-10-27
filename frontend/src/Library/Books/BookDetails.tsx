// A book, as Sonarr's episode details: who wrote it and what it is, each format with its status,
// its file to open or delete and searches for it, and its downloads
import { useQuery } from '@tanstack/react-query';
import { BookOpen, Download, ExternalLink, RefreshCw, SquarePen, Star, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { runCommand } from 'App/commands';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import ConfirmModal from 'Components/Modal/ConfirmModal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { BookSearchButtons, FormatInfo, FormatStatus, shownFormats } from 'Library/BookFormats';
import { Cover } from 'Library/library';
import styles from 'Library/Library.module.css';
import { BookDetail } from 'typings/Library';
import { api, urlBase } from 'Utilities/api';
import { formatBytes, formatDateTime, relativeDate } from 'Utilities/format';

const LIBRARIES = { ebook: 'eBook', audiobook: 'AudioBook' };

const DOWNLOAD_COLUMNS: Column[] = [
  { name: 'date', label: 'Date' },
  { name: 'type', label: 'Format' },
  { name: 'status', label: 'Status' },
  { name: 'title', label: 'Release' },
  { name: 'indexer', label: 'Indexer' },
  { name: 'message', label: 'Result' },
];

const DOWNLOAD_KINDS: Record<string, 'success' | 'danger' | 'purple' | 'default'> = {
  Processed: 'success',
  Seeding: 'success',
  Failed: 'danger',
  Snatched: 'purple',
};

// about this many characters show before More
const DESCRIPTION_SHOWN = 600;

function FormatPanel({ book, format }: { book: BookDetail; format: FormatInfo }) {
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const file = format.format === 'ebook' ? book.ebookFile : book.audioFile;

  function deleteFile() {
    const id = `delete-${Date.now()}`;
    api('/library/books/mark', { method: 'PUT', body: { ids: [book.id], mediaType: format.format, action: 'Delete' } })
      .then(() => showMessage({ id, text: `Deleted the ${format.label} of ${book.title}`, kind: 'success', isWorking: false }))
      .catch((error) => showMessage({ id, text: `Deleting failed: ${error.message}`, kind: 'danger', isWorking: false }))
      .finally(() => {
        queryClient.invalidateQueries({ queryKey: ['library'] });
        queryClient.invalidateQueries({ queryKey: ['author'] });
      });
  }

  return (
    <div className={styles.formatPanel}>
      <div className={styles.formatPanelHeader}>
        <h3>{format.label}</h3>
        <span>
          <FormatStatus book={book} format={format} />
        </span>
        <span className={styles.formatPanelActions}>
          <BookSearchButtons book={book} formats={[format]} />
        </span>
      </div>
      {file ? (
        <div className={styles.fileRow}>
          <code title={file.path}>{file.path}</code>
          <span className={styles.muted}>
            {file.exists ? formatBytes(file.size) : "the file isn't there"}
          </span>
          {file.exists ? (
            <a
              href={`${urlBase()}/open_book?bookid=${encodeURIComponent(book.id)}&library=${LIBRARIES[format.format]}`}
              title="Open"
            >
              <Icon name={Download} size={15} />
            </a>
          ) : null}
          <button type="button" className={styles.iconLink} title="Delete the file" onClick={() => setIsDeleteOpen(true)}>
            <Icon name={Trash2} size={15} />
          </button>
        </div>
      ) : (
        <p className={styles.muted}>No file</p>
      )}
      <ConfirmModal
        isOpen={isDeleteOpen}
        title={`Delete the ${format.label}`}
        message={`${file?.path ?? ''} is deleted, and the ${format.label} is ignored from now on.`}
        confirmLabel="Delete"
        onConfirm={() => {
          setIsDeleteOpen(false);
          deleteFile();
        }}
        onCancel={() => setIsDeleteOpen(false)}
      />
    </div>
  );
}

function BookDetails() {
  const { bookId = '' } = useParams();
  const formats = shownFormats();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDescriptionOpen, setIsDescriptionOpen] = useState(false);

  const { data, error, isLoading } = useQuery({
    queryKey: ['library', 'book', bookId],
    queryFn: () => api<BookDetail>(`/library/book/${encodeURIComponent(bookId)}`),
    retry: false,
  });

  // the sources give the description as HTML, shown as its text
  const description = useMemo(
    () =>
      data?.description
        ? (new DOMParser().parseFromString(data.description, 'text/html').body.textContent?.trim() ?? '')
        : '',
    [data?.description]
  );

  return (
    <PageContent title={data?.title ?? 'Book'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label="Refresh"
            iconName={RefreshCw}
            isDisabled={!data}
            isSpinning={isRefreshing}
            onPress={() => {
              setIsRefreshing(true);
              runCommand('RefreshBook', { bookId }, `Refresh ${data?.title}`).finally(() => {
                setIsRefreshing(false);
                queryClient.invalidateQueries({ queryKey: ['library', 'book', bookId] });
              });
            }}
          />
          <PageToolbarButton
            label="Edit"
            iconName={SquarePen}
            isDisabled={!data}
            to={`/edit_book?bookid=${encodeURIComponent(bookId)}`}
          />
          <PageToolbarButton
            label="Old Page"
            iconName={ExternalLink}
            isDisabled={!data}
            to={`/book_detail?bookid=${encodeURIComponent(bookId)}`}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}
        {data ? (
          <>
            <div className={styles.header}>
              <div className={styles.headerImage}>
                <Cover src={data.image} icon={BookOpen} size={64} />
              </div>
              <div className={styles.headerInfo}>
                <h1 className={styles.headerName}>
                  {data.title}
                  {data.subtitle ? <span className={styles.muted}>: {data.subtitle}</span> : null}
                </h1>
                <div className={styles.headerLabels}>
                  <span>
                    by <Link to={`/author/${encodeURIComponent(data.authorId)}`}>{data.authorName}</Link>
                  </span>
                  {data.series.map((series) => (
                    <Link key={series.id} to={`/series/${encodeURIComponent(series.id)}`}>
                      <Label kind="info">
                        {series.name}
                        {series.number ? ` #${series.number}` : ''}
                      </Label>
                    </Link>
                  ))}
                </div>
                <div className={styles.headerLabels}>
                  {data.releaseDate ? <Label>Released {data.releaseDate}</Label> : null}
                  {data.originalDate && data.originalDate !== data.releaseDate ? (
                    <Label>First published {data.originalDate}</Label>
                  ) : null}
                  {data.publisher ? <Label>{data.publisher}</Label> : null}
                  {data.pages ? <Label>{data.pages} pages</Label> : null}
                  {data.language ? <Label>{data.language}</Label> : null}
                  {data.isbn ? <Label title="ISBN">{data.isbn}</Label> : null}
                  {data.narrator ? <Label>Read by {data.narrator}</Label> : null}
                  {data.rating ? (
                    <Label>
                      <Icon name={Star} size={11} /> {data.rating.toFixed(1)}
                    </Label>
                  ) : null}
                  {data.locked ? (
                    <Label kind="warning" title="Its details aren't changed by a refresh">
                      Locked
                    </Label>
                  ) : null}
                  {data.added ? <Label>Added {data.added}</Label> : null}
                </div>
                {data.genres ? <p className={styles.muted}>{data.genres}</p> : null}
                {data.links.length ? (
                  <div className={styles.links}>
                    {data.links.map((link) =>
                      link.url ? (
                        <Link key={link.source} to={link.url}>
                          <Icon name={ExternalLink} size={13} /> {link.source}
                        </Link>
                      ) : (
                        <span key={link.source} className={styles.muted}>
                          {link.source} {link.id}
                        </span>
                      )
                    )}
                  </div>
                ) : null}
                {description ? (
                  <div className={isDescriptionOpen ? styles.about : styles.aboutClosed}>
                    <p>{description}</p>
                    {description.length > DESCRIPTION_SHOWN ? (
                      <button type="button" className={styles.more} onClick={() => setIsDescriptionOpen(!isDescriptionOpen)}>
                        {isDescriptionOpen ? 'Less' : 'More'}
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>

            <div className={styles.formatPanels}>
              {formats.map((format) => (
                <FormatPanel key={format.format} book={data} format={format} />
              ))}
            </div>

            <h2 className={styles.legend}>Downloads</h2>
            {data.downloads.length ? (
              <Table columns={DOWNLOAD_COLUMNS}>
                {data.downloads.map((download) => (
                  <TableRow key={download.id}>
                    <TableRowCell className={styles.date} title={formatDateTime(download.date)}>
                      {relativeDate(download.date)}
                    </TableRowCell>
                    <TableRowCell>{download.mediaType === 'ebook' ? 'eBook' : 'Audiobook'}</TableRowCell>
                    <TableRowCell>
                      <Label kind={DOWNLOAD_KINDS[download.status] ?? 'default'}>{download.status}</Label>
                    </TableRowCell>
                    <TableRowCell>{download.title}</TableRowCell>
                    <TableRowCell>{download.indexer}</TableRowCell>
                    <TableRowCell className={styles.message}>{download.message}</TableRowCell>
                  </TableRow>
                ))}
              </Table>
            ) : (
              <p className={styles.muted}>It hasn't been downloaded</p>
            )}
          </>
        ) : null}
      </PageContentBody>
    </PageContent>
  );
}

export default BookDetails;
