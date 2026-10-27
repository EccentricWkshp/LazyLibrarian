// Reading an eBook, magazine issue or comic issue in the browser: a PDF or comic archive page by
// page, an EPUB in epub.js, or a PDF in the browser's own viewer. Where the owner is, is kept, and
// the reader opens there again; a page asked for (?page=, from a search) wins. And downloading it,
// or sending it to the owner's devices
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Download, ExternalLink, FileText, Send } from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import queryClient from 'App/queryClient';
import { SelectInput } from 'Components/Form/Form';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { remember, remembered } from 'Library/library';
import { api } from 'Utilities/api';
import EpubViewer from './EpubViewer';
import PageViewer from './PageViewer';
import { filePath, fileUrl, ReadKind, readerPath, sendToDevice } from './reading';
import styles from './Reader.module.css';

interface Progress {
  position: string;
  page: number;
  pages: number;
  finished: boolean;
  updated: string;
}

interface Reading {
  title: string;
  format: string;
  formats: string[];
  reader: '' | 'pdf' | 'pages' | 'epub';
  pages: number;
  progress: Progress;
}

const KINDS: ReadKind[] = ['book', 'issue', 'comic'];

// where the owner is, kept as they read; the library pages show what's read
function saveProgress(kind: ReadKind, id: string, progress: Partial<Progress>) {
  api(`/read/${kind}/${encodeURIComponent(id)}/progress`, { method: 'PUT', body: progress })
    .then(() => queryClient.invalidateQueries({ queryKey: ['library'] }))
    .catch(() => undefined);
}

function Reader() {
  const params = useParams();
  const kind = (KINDS.includes(params.kind as ReadKind) ? params.kind : 'book') as ReadKind;
  const id = params.itemId ?? '';
  const [search] = useSearchParams();
  const format = search.get('format') ?? '';
  const asked = Number(search.get('page')) || 0;
  const navigate = useNavigate();
  // a PDF shows page by page, so where the owner is can be kept, unless they'd rather the browser's viewer
  const [pdfViewer, setPdfViewer] = useState(() => remembered('reader.pdf', 'pages'));

  const { data, error, isLoading } = useQuery({
    queryKey: ['read', kind, id, format],
    queryFn: () => api<Reading>(`/read/${kind}/${encodeURIComponent(id)}`, { query: { format } }),
    retry: false,
    // where the owner was is read once, as the reader opens
    staleTime: Infinity,
    gcTime: 0,
  });
  const shown = data?.format ?? format;
  const byPage = data?.reader === 'pages' || (data?.reader === 'pdf' && pdfViewer === 'pages' && data.pages > 0);
  const progress = data?.progress;
  const startPage = asked || (progress && !progress.finished ? progress.page : 0) || 1;

  return (
    <PageContent title={data?.title ?? 'Read'}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="Back" iconName={ArrowLeft} onPress={() => navigate(-1)} />
          <PageToolbarSeparator />
          <PageToolbarButton
            label="Download"
            iconName={Download}
            isDisabled={!data}
            to={filePath(kind, id, shown, true)}
            noRouter={true}
          />
          <PageToolbarButton
            label="Send to Device"
            iconName={Send}
            isDisabled={!data}
            onPress={() => sendToDevice(kind, id, data?.title ?? id, shown)}
          />
          {data?.reader === 'pdf' ? (
            <>
              <PageToolbarButton
                label={byPage ? "Browser's PDF Viewer" : 'Page by Page'}
                iconName={FileText}
                onPress={() => {
                  const next = byPage ? 'browser' : 'pages';
                  setPdfViewer(next);
                  remember('reader.pdf', next);
                }}
              />
              <PageToolbarButton
                label="Open in New Tab"
                iconName={ExternalLink}
                onPress={() => window.open(fileUrl(kind, id, shown), '_blank', 'noopener')}
              />
            </>
          ) : null}
        </PageToolbarSection>
        {data && data.formats.length > 1 ? (
          <PageToolbarSection alignContent="right">
            <SelectInput
              className={styles.formatSelect}
              value={shown}
              values={data.formats.map((one) => ({ key: one, value: one.toUpperCase() }))}
              onChange={(next) => navigate(readerPath(kind, id, next), { replace: true })}
            />
          </PageToolbarSection>
        ) : null}
      </PageToolbar>

      <div className={styles.body}>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? (
          <div className={styles.message}>
            <Alert kind="danger">{(error as Error).message}</Alert>
          </div>
        ) : null}
        {data && byPage ? (
          <PageViewer
            key={`${kind}-${id}`}
            kind={kind}
            id={id}
            pages={data.pages}
            title={data.title}
            startPage={Math.min(startPage, data.pages)}
            onPage={(page) => saveProgress(kind, id, { page, pages: data.pages })}
          />
        ) : null}
        {data?.reader === 'pdf' && !byPage ? (
          <iframe className={styles.frame} src={fileUrl(kind, id, shown)} title={data.title} />
        ) : null}
        {data?.reader === 'epub' ? (
          <EpubViewer
            url={fileUrl(kind, id, shown)}
            title={data.title}
            startAt={progress && !progress.finished ? progress.position : ''}
            onLocation={(position, percent, atEnd) =>
              saveProgress(kind, id, { position, page: percent, pages: 100, finished: atEnd })
            }
          />
        ) : null}
        {data && !data.reader ? (
          <div className={styles.message}>
            <Alert kind="info">
              A {data.format.toUpperCase()} file can't be read in the browser. Download it, or send it to a device.
            </Alert>
          </div>
        ) : null}
      </div>
    </PageContent>
  );
}

export default Reader;
