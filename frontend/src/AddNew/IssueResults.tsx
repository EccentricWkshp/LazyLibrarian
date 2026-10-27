// The magazines and comics a lookup found, each to add, or to go to when it's in the library
import { Layers, Newspaper, Plus } from 'lucide-react';
import Icon from 'Components/Icon';
import Button from 'Components/Link/Button';
import Link from 'Components/Link/Link';
import { Label } from 'Components/Misc';
import { ComicLookup, MagazineLookup } from 'typings/AddNew';
import { Adding } from './AddModal';
import styles from './AddNew.module.css';

export function MagazineResults({ found, onAdd }: { found: MagazineLookup[]; onAdd: (adding: Adding) => void }) {
  return (
    <ul className={styles.books}>
      {found.map((magazine) => (
        <li key={magazine.title} className={styles.book}>
          <div className={styles.noCover}>
            <Icon name={Newspaper} size={28} />
          </div>
          <div className={styles.bookText}>
            <div className={styles.bookTitle}>{magazine.title}</div>
            <div className={styles.meta}>
              {magazine.inLibrary
                ? `${magazine.issues} ${magazine.issues === 1 ? 'issue' : 'issues'}`
                : magazine.rejectWords
                  ? `Releases with ${magazine.rejectWords} are ruled out`
                  : 'Not in the library'}
            </div>
          </div>
          <div className={styles.bookActions}>
            {magazine.inLibrary ? (
              <Link to={`/issue_page?title=${encodeURIComponent(magazine.title)}`} className={styles.inLibrary}>
                <Label kind="success">In Library</Label>
              </Link>
            ) : (
              <Button
                aria-label={`Add ${magazine.title}`}
                onPress={() =>
                  onAdd({ kind: 'magazine', id: magazine.title, name: magazine.title, rejectWords: magazine.rejectWords })
                }
              >
                <Icon name={Plus} /> Add
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ComicResults({ found, onAdd }: { found: ComicLookup[]; onAdd: (adding: Adding) => void }) {
  if (!found.length) {
    return <p className={styles.help}>Nothing was found, or the comic is in the library already.</p>;
  }

  return (
    <ul className={styles.books}>
      {found.map((comic) => (
        <li key={comic.id} className={styles.book}>
          <div className={styles.noCover}>
            <Icon name={Layers} size={28} />
          </div>
          <div className={styles.bookText}>
            <div className={styles.bookTitle}>
              {comic.title}
              {comic.start ? <span className={styles.year}> ({comic.start})</span> : null}
            </div>
            <div className={styles.meta}>
              {[comic.publisher, comic.issues ? `${comic.issues} issues` : '', comic.id.startsWith('CV') ? 'ComicVine' : 'Comixology']
                .filter(Boolean)
                .join(' · ')}
            </div>
            {comic.overview ? <p className={styles.overview}>{comic.overview}</p> : null}
          </div>
          <div className={styles.bookActions}>
            {comic.inLibrary ? (
              <Link to={`/comicissue_page?comicid=${encodeURIComponent(comic.id)}`} className={styles.inLibrary}>
                <Label kind="success">In Library</Label>
              </Link>
            ) : (
              <Button aria-label={`Add ${comic.title}`} onPress={() => onAdd({ kind: 'comic', id: comic.id, name: comic.title })}>
                <Icon name={Plus} /> Add
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
