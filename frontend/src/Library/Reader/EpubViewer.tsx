// An EPUB in epub.js, page by page: the arrow keys or the buttons turn the page, and the contents
// go to a chapter. epub.js is fetched only when a book is opened, and the book's own scripts don't run
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { SelectInput } from 'Components/Form/Form';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import styles from './Reader.module.css';

interface Chapter {
  key: string;
  value: string;
}

// epub.js's own types, only what's used here
interface Rendition {
  display: (target?: string) => Promise<void>;
  next: () => Promise<void>;
  prev: () => Promise<void>;
  on: (event: string, listener: (...args: never[]) => void) => void;
  themes: { default: (styles: Record<string, Record<string, string>>) => void };
  destroy: () => void;
}

interface NavItem {
  href: string;
  label: string;
  subitems?: NavItem[];
}

function chapters(items: NavItem[], depth = 0): Chapter[] {
  return items.flatMap((item) => [
    { key: item.href, value: `${'  '.repeat(depth)}${item.label.trim()}` },
    ...chapters(item.subitems ?? [], depth + 1),
  ]);
}

function EpubViewer({ url, title }: { url: string; title: string }) {
  const area = useRef<HTMLDivElement>(null);
  const rendition = useRef<Rendition | null>(null);
  const [contents, setContents] = useState<Chapter[]>([]);
  const [chapter, setChapter] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let destroyed = false;
    let book: { destroy: () => void } | null = null;

    async function open() {
      try {
        const [{ default: ePub }, response] = await Promise.all([
          import('epubjs'),
          fetch(url, { credentials: 'same-origin' }),
        ]);
        if (!response.ok) {
          throw new Error(`The book couldn't be fetched (${response.status})`);
        }
        const data = await response.arrayBuffer();
        if (destroyed || !area.current) {
          return;
        }
        const opened = ePub(data);
        book = opened;
        const shown = opened.renderTo(area.current, {
          width: '100%',
          height: '100%',
          flow: 'paginated',
          spread: 'auto',
          allowScriptedContent: false,
        }) as unknown as Rendition;
        rendition.current = shown;
        const style = getComputedStyle(document.body);
        shown.themes.default({
          body: { color: style.color, background: style.backgroundColor },
          a: { color: style.getPropertyValue('--linkColor') || 'inherit' },
        });
        shown.on('relocated', ((location: { start: { href: string } }) => setChapter(location.start.href)) as never);
        await shown.display();
        const navigation = await opened.loaded.navigation;
        if (!destroyed) {
          setContents(chapters(navigation.toc as NavItem[]));
          setIsLoading(false);
        }
      } catch (why) {
        if (!destroyed) {
          setError((why as Error).message || `${title} couldn't be opened`);
          setIsLoading(false);
        }
      }
    }

    open();
    return () => {
      destroyed = true;
      rendition.current?.destroy();
      rendition.current = null;
      book?.destroy();
    };
  }, [url, title]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.target as HTMLElement)?.tagName === 'SELECT') {
        return;
      }
      if (['ArrowRight', 'PageDown'].includes(event.key)) {
        rendition.current?.next();
      } else if (['ArrowLeft', 'PageUp'].includes(event.key)) {
        rendition.current?.prev();
      }
    }

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className={styles.viewer}>
      <div className={styles.controls}>
        <Link className={styles.turn} onPress={() => rendition.current?.prev()}>
          <Icon name={ChevronLeft} />
        </Link>
        {contents.length ? (
          <SelectInput
            className={styles.pageSelect}
            value={contents.some((one) => one.key === chapter) ? chapter : ''}
            values={[{ key: '', value: 'Contents', isDisabled: true }, ...contents]}
            onChange={(href) => rendition.current?.display(href)}
          />
        ) : null}
        <Link className={styles.turn} onPress={() => rendition.current?.next()}>
          <Icon name={ChevronRight} />
        </Link>
      </div>
      {isLoading ? <LoadingIndicator /> : null}
      {error ? (
        <div className={styles.message}>
          <Alert kind="danger">{error}</Alert>
        </div>
      ) : null}
      <div ref={area} className={styles.epub} />
    </div>
  );
}

export default EpubViewer;
