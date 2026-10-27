// A comic or magazine archive page by page, as the server draws them: the arrow keys, Page Up and
// Down, Home and End, or a click on either side turn the page. It fits the window's height or width,
// and two pages can be shown side by side
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { SelectInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { remember, remembered } from 'Library/library';
import { pageUrl, ReadKind } from './reading';
import styles from './Reader.module.css';

type Fit = 'height' | 'width';

const FITS = [
  { key: 'height', value: 'Fit Height' },
  { key: 'width', value: 'Fit Width' },
];
const SPREADS = [
  { key: '1', value: 'One Page' },
  { key: '2', value: 'Two Pages' },
];

function PageViewer({
  kind,
  id,
  pages,
  title,
  startPage = 1,
  onPage,
}: {
  kind: ReadKind;
  id: string;
  pages: number;
  title: string;
  startPage?: number;
  // the last page showing, once it's been turned to a moment
  onPage?: (page: number) => void;
}) {
  const [page, setPage] = useState(Math.max(startPage, 1));
  const [fit, setFit] = useState<Fit>(() => (remembered('reader.fit', 'height') === 'width' ? 'width' : 'height'));
  const [spread, setSpread] = useState(() => (remembered('reader.spread', '1') === '2' ? 2 : 1));
  // the cover is a page of its own, the pages after it pair up
  const step = spread === 2 && page > 1 ? 2 : 1;
  const shown = spread === 2 && page > 1 && page < pages ? [page, page + 1] : [page];

  function go(next: number) {
    const first = spread === 2 && next > 1 && next % 2 === 1 ? next - 1 : next;
    setPage(Math.min(Math.max(first, 1), pages));
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.target as HTMLElement)?.tagName === 'SELECT') {
        return;
      }
      if (['ArrowRight', 'PageDown', ' '].includes(event.key)) {
        event.preventDefault();
        go(page + step);
      } else if (['ArrowLeft', 'PageUp'].includes(event.key)) {
        event.preventDefault();
        go(page - (spread === 2 && page > 2 ? 2 : 1));
      } else if (event.key === 'Home') {
        go(1);
      } else if (event.key === 'End') {
        go(pages);
      }
    }

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // where the owner is, kept once they stop on a page
  const last = shown[shown.length - 1];
  useEffect(() => {
    if (!onPage || !pages) {
      return undefined;
    }
    const timer = window.setTimeout(() => onPage(last), 800);
    return () => window.clearTimeout(timer);
    // onPage is made again each render, the page is what matters
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [last, pages]);

  // the next pages are fetched before they're turned to
  useEffect(() => {
    [1, 2].forEach((ahead) => {
      if (page + step + ahead - 1 <= pages) {
        new Image().src = pageUrl(kind, id, page + step + ahead - 1);
      }
    });
  }, [kind, id, page, step, pages]);

  if (!pages) {
    return <p className={styles.message}>{title} has no pages that can be shown.</p>;
  }

  return (
    <div className={styles.viewer}>
      <div className={styles.controls}>
        <Link className={styles.turn} isDisabled={page <= 1} onPress={() => go(page - (spread === 2 && page > 2 ? 2 : 1))}>
          <Icon name={ChevronLeft} />
        </Link>
        <SelectInput
          className={styles.pageSelect}
          value={String(page)}
          values={Array.from({ length: pages }, (_, index) => ({
            key: String(index + 1),
            value: `Page ${index + 1} of ${pages}`,
          }))}
          onChange={(value) => go(Number(value))}
        />
        <Link className={styles.turn} isDisabled={page + step > pages} onPress={() => go(page + step)}>
          <Icon name={ChevronRight} />
        </Link>
        <SelectInput
          className={styles.fitSelect}
          value={fit}
          values={FITS}
          onChange={(value) => {
            setFit(value as Fit);
            remember('reader.fit', value);
          }}
        />
        <SelectInput
          className={styles.fitSelect}
          value={String(spread)}
          values={SPREADS}
          onChange={(value) => {
            setSpread(Number(value));
            remember('reader.spread', value);
          }}
        />
      </div>
      <div
        className={fit === 'width' ? styles.pagesWidth : styles.pagesHeight}
        onClick={(event) => {
          // the left third turns back, the rest forward
          const box = event.currentTarget.getBoundingClientRect();
          go(event.clientX - box.left < box.width / 3 ? page - (spread === 2 && page > 2 ? 2 : 1) : page + step);
        }}
      >
        {shown.map((number) => (
          <img
            key={number}
            className={styles.page}
            src={pageUrl(kind, id, number)}
            alt={`${title}, page ${number}`}
          />
        ))}
      </div>
    </div>
  );
}

export default PageViewer;
