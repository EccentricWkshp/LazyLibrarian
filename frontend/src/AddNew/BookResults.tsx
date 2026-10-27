// The authors and books a lookup found, each to add, or to go to when it's in the library
import { BookOpen, Plus, Star, User } from 'lucide-react';
import { useState } from 'react';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Label } from 'Components/Misc';
import { BookLookup, Lookup } from 'typings/AddNew';
import { Adding } from './AddModal';
import styles from './AddNew.module.css';

const OWNED = ['Open', 'Have'];
// every book found brings its author, the best matches are shown until all are asked for
const AUTHORS_SHOWN = 8;

function statusLabel(status: string, format: string) {
  if (!status || status === 'Skipped' || status === 'Ignored') {
    return null;
  }

  const kind = OWNED.includes(status) ? 'success' : status === 'Wanted' ? 'warning' : 'info';

  return (
    <Label key={format} kind={kind}>
      {format} {OWNED.includes(status) ? 'in library' : status}
    </Label>
  );
}

function Cover({ book }: { book: BookLookup }) {
  const [failed, setFailed] = useState(false);

  if (!book.cover || failed) {
    return (
      <div className={styles.noCover}>
        <Icon name={BookOpen} size={28} />
      </div>
    );
  }

  return (
    <img
      className={styles.cover}
      src={book.cover}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

function BookResults({ lookup, onAdd }: { lookup: Lookup; onAdd: (adding: Adding) => void }) {
  const { authors, books } = lookup;
  const [allAuthors, setAllAuthors] = useState(false);
  const shownAuthors = allAuthors ? authors : authors.slice(0, AUTHORS_SHOWN);

  if (!authors.length && !books.length) {
    return <p className={styles.help}>Nothing was found. Try fewer words, or the other info sources in Settings.</p>;
  }

  return (
    <>
      {authors.length ? (
        <section>
          <h2 className={styles.legend}>Authors</h2>
          <div className={styles.authors}>
            {shownAuthors.map((author) => (
              <div key={author.id} className={styles.author}>
                <Icon name={User} size={22} className={styles.authorIcon} />
                <div className={styles.authorText}>
                  <div className={styles.authorName}>{author.name}</div>
                  <div className={styles.meta}>
                    {author.source} · {author.books} {author.books === 1 ? 'book' : 'books'} found
                  </div>
                </div>
                {author.inLibrary ? (
                  <Link className={styles.inLibrary} to={`/author_page?authorid=${encodeURIComponent(author.id)}`}>
                    <Label kind="success">In Library</Label>
                  </Link>
                ) : author.loading ? (
                  <Label kind="info">Adding</Label>
                ) : (
                  <Button
                    aria-label={`Add ${author.name}`}
                    onPress={() => onAdd({ kind: 'author', id: author.id, name: author.name })}
                  >
                    <Icon name={Plus} /> Add
                  </Button>
                )}
              </div>
            ))}
          </div>
          {authors.length > AUTHORS_SHOWN ? (
            <div className={styles.more}>
              <Button onPress={() => setAllAuthors(!allAuthors)}>
                {allAuthors ? 'Show fewer authors' : `Show all ${authors.length} authors`}
              </Button>
            </div>
          ) : null}
        </section>
      ) : null}

      {books.length ? (
        <section>
          <h2 className={styles.legend}>Books</h2>
          <ul className={styles.books}>
            {books.map((book) => (
              <li key={`${book.source}-${book.id}`} className={styles.book}>
                <Cover book={book} />
                <div className={styles.bookText}>
                  <div className={styles.bookTitle}>
                    {book.title}
                    {book.subtitle ? <span className={styles.subtitle}>: {book.subtitle}</span> : null}
                    {book.releaseDate ? <span className={styles.year}> ({book.releaseDate.slice(0, 4)})</span> : null}
                  </div>
                  <div className={styles.meta}>
                    {book.authorName}
                    {book.publisher ? ` · ${book.publisher}` : ''}
                    {book.pages ? ` · ${book.pages} pages` : ''}
                    {book.rating ? (
                      <span className={styles.rating}>
                        {' · '}
                        <Icon name={Star} size={12} /> {book.rating.toFixed(1)}
                      </span>
                    ) : null}
                    {' · '}
                    {book.source}
                  </div>
                  {book.overview ? <p className={styles.overview}>{book.overview}</p> : null}
                  <div className={styles.labels}>
                    {statusLabel(book.status, 'eBook')}
                    {statusLabel(book.audioStatus, 'Audiobook')}
                  </div>
                </div>
                <div className={styles.bookActions}>
                  {book.inLibrary ? (
                    <Link to={`/book_detail?bookid=${encodeURIComponent(book.id)}`} className={styles.inLibrary}>
                      <Label kind="success">In Library</Label>
                    </Link>
                  ) : null}
                  <Button
                    aria-label={`Add ${book.title}`}
                    onPress={() =>
                      onAdd({
                        kind: 'book',
                        id: book.id,
                        name: book.title,
                        source: book.source,
                        authorId: book.authorId,
                        status: book.status,
                        audioStatus: book.audioStatus,
                      })
                    }
                  >
                    <Icon name={Plus} /> {book.inLibrary ? 'Want' : 'Add'}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

export default BookResults;
