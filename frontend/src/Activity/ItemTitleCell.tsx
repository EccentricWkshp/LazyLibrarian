// The book, magazine issue or comic issue a download was for, linked to it in the old pages, as
// the queue, history and blocklist show it
import Link from 'Components/Link/Link';
import { TableRowCell } from 'Components/Table/Table';
import { MediaType } from 'typings/Queue';
import styles from './ItemTitleCell.module.css';

export interface DownloadTarget {
  mediaType: MediaType;
  bookId: string;
  title: string;
  author: string;
  authorId: string | null;
  issue: string;
}

export function itemLink(item: DownloadTarget) {
  if (item.mediaType === 'magazine') {
    return `/magazine?title=${encodeURIComponent(item.bookId)}`;
  }

  if (item.mediaType === 'comic') {
    return `/comic/${encodeURIComponent(item.bookId.split('_')[0])}`;
  }

  return `/book/${encodeURIComponent(item.bookId)}`;
}

// subtitle is a line under the title, a magazine's latest issue
function ItemTitleCell({ item, subtitle }: { item: DownloadTarget; subtitle?: string }) {
  const title = item.issue ? `${item.title} - ${item.issue}` : item.title;

  return (
    <TableRowCell className={styles.title}>
      <Link className={styles.titleLink} to={itemLink(item)}>
        {title}
      </Link>
      {item.author ? (
        <div className={styles.author}>
          {item.authorId ? (
            <Link to={`/author_page?authorid=${encodeURIComponent(item.authorId)}`}>{item.author}</Link>
          ) : (
            item.author
          )}
        </div>
      ) : null}
      {subtitle ? <div className={styles.author}>{subtitle}</div> : null}
    </TableRowCell>
  );
}

export default ItemTitleCell;
