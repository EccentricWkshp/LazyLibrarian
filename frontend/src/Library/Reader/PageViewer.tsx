// A comic or magazine archive page by page, as the server draws them: the arrow keys, Page Up and
// Down, Home and End, or a click on either side turn the page. It fits the window's height or width,
// two pages can be shown side by side, and it zooms (+ and -, Ctrl and the mouse wheel, or the zoom
// menu), a zoomed page dragged to see the rest and drawn sharper by the server
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { SelectInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import IconButton from 'Components/Link/IconButton';
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
// times the fitted size
const ZOOMS = [1, 1.25, 1.5, 2, 2.5, 3, 4];
// a page's width as the server draws it unzoomed, 150 dpi of a letter page
const DRAWN_WIDTH = 1275;
// the space around the pages
const PADDING = 16;

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
  const [zoom, setZoom] = useState(1);
  const [box, setBox] = useState({ width: 0, height: 0 });
  const pagesRef = useRef<HTMLDivElement>(null);
  // a drag that pans a zoomed page, not a click that turns it
  const drag = useRef({ x: 0, y: 0, left: 0, top: 0, moved: false, down: false });
  // the cover is a page of its own, the pages after it pair up
  const step = spread === 2 && page > 1 ? 2 : 1;
  const shown = spread === 2 && page > 1 && page < pages ? [page, page + 1] : [page];

  function go(next: number) {
    const first = spread === 2 && next > 1 && next % 2 === 1 ? next - 1 : next;
    setPage(Math.min(Math.max(first, 1), pages));
  }

  function zoomBy(direction: number) {
    setZoom((current) => {
      const at = ZOOMS.findIndex((level) => level >= current);
      return ZOOMS[Math.min(Math.max((at < 0 ? ZOOMS.length - 1 : at) + direction, 0), ZOOMS.length - 1)];
    });
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
      } else if (['+', '='].includes(event.key)) {
        zoomBy(1);
      } else if (event.key === '-') {
        zoomBy(-1);
      } else if (event.key === '0') {
        setZoom(1);
      }
    }

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // the room the pages have, for their size zoomed
  useEffect(() => {
    const element = pagesRef.current;
    if (!element) {
      return undefined;
    }
    const observer = new ResizeObserver(() =>
      setBox({ width: element.clientWidth - PADDING, height: element.clientHeight - PADDING })
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [pages]);

  // Ctrl and the mouse wheel (or a pinch on a touchpad) zooms, not the browser
  useEffect(() => {
    const element = pagesRef.current;
    if (!element) {
      return undefined;
    }
    function onWheel(event: WheelEvent) {
      if (event.ctrlKey) {
        event.preventDefault();
        zoomBy(event.deltaY < 0 ? 1 : -1);
      }
    }
    element.addEventListener('wheel', onWheel, { passive: false });
    return () => element.removeEventListener('wheel', onWheel);
  }, [pages]);

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

  // drawn wider when zoomed, so it's sharp
  const drawnWidth = zoom > 1 ? Math.round(DRAWN_WIDTH * zoom) : 0;

  // the next pages are fetched before they're turned to
  useEffect(() => {
    [1, 2].forEach((ahead) => {
      if (page + step + ahead - 1 <= pages) {
        new Image().src = pageUrl(kind, id, page + step + ahead - 1, drawnWidth);
      }
    });
  }, [kind, id, page, step, pages, drawnWidth]);

  if (!pages) {
    return <p className={styles.message}>{title} has no pages that can be shown.</p>;
  }

  // the fitted size, times the zoom
  const gap = (shown.length - 1) * 4;
  const size =
    zoom === 1 || !box.width
      ? undefined
      : fit === 'height'
        ? { height: box.height * zoom, maxHeight: 'none', maxWidth: 'none', width: 'auto' }
        : { width: ((box.width - gap) / shown.length) * zoom, maxWidth: 'none' };

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
        <IconButton name={ZoomOut} title="Zoom out (-)" isDisabled={zoom <= ZOOMS[0]} onPress={() => zoomBy(-1)} />
        <SelectInput
          className={styles.fitSelect}
          value={String(zoom)}
          values={ZOOMS.map((level) => ({ key: String(level), value: `${Math.round(level * 100)}%` }))}
          onChange={(value) => setZoom(Number(value))}
        />
        <IconButton
          name={ZoomIn}
          title="Zoom in (+)"
          isDisabled={zoom >= ZOOMS[ZOOMS.length - 1]}
          onPress={() => zoomBy(1)}
        />
      </div>
      <div
        ref={pagesRef}
        className={`${fit === 'width' ? styles.pagesWidth : styles.pagesHeight} ${zoom > 1 ? styles.zoomed : ''}`}
        onPointerDown={(event) => {
          const element = event.currentTarget;
          drag.current = { x: event.clientX, y: event.clientY, left: element.scrollLeft, top: element.scrollTop,
            moved: false, down: true };
        }}
        onPointerMove={(event) => {
          const now = drag.current;
          if (!now.down || zoom === 1) {
            return;
          }
          const dx = event.clientX - now.x;
          const dy = event.clientY - now.y;
          if (Math.abs(dx) + Math.abs(dy) > 4) {
            now.moved = true;
          }
          event.currentTarget.scrollLeft = now.left - dx;
          event.currentTarget.scrollTop = now.top - dy;
        }}
        onPointerUp={() => {
          drag.current.down = false;
        }}
        onPointerLeave={() => {
          drag.current.down = false;
        }}
        onClick={(event) => {
          // zoomed, a click or a drag looks around the page; the arrows still turn it
          if (zoom > 1 || drag.current.moved) {
            return;
          }
          // the left third turns back, the rest forward
          const area = event.currentTarget.getBoundingClientRect();
          go(event.clientX - area.left < area.width / 3 ? page - (spread === 2 && page > 2 ? 2 : 1) : page + step);
        }}
      >
        <div className={styles.spread}>
          {shown.map((number) => (
            <img
              key={number}
              className={styles.page}
              style={size}
              draggable={false}
              src={pageUrl(kind, id, number, drawnWidth)}
              alt={`${title}, page ${number}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export default PageViewer;
