// Reading an eBook, magazine issue or comic issue in the browser: a PDF in the browser's own viewer,
// a comic or a magazine archive page by page, an EPUB in epub.js. And downloading it, or sending it
// to the owner's devices
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Download, ExternalLink, Send } from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import { SelectInput } from 'Components/Form/Form';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { api } from 'Utilities/api';
import EpubViewer from './EpubViewer';
import PageViewer from './PageViewer';
import { filePath, fileUrl, ReadKind, readerPath, sendToDevice } from './reading';
import styles from './Reader.module.css';

interface Reading {
  title: string;
  format: string;
  formats: string[];
  reader: '' | 'pdf' | 'pages' | 'epub';
  pages: number;
}

const KINDS: ReadKind[] = ['book', 'issue', 'comic'];

function Reader() {
  const params = useParams();
  const kind = (KINDS.includes(params.kind as ReadKind) ? params.kind : 'book') as ReadKind;
  const id = params.itemId ?? '';
  const [search] = useSearchParams();
  const format = search.get('format') ?? '';
  const navigate = useNavigate();

  const { data, error, isLoading } = useQuery({
    queryKey: ['read', kind, id, format],
    queryFn: () => api<Reading>(`/read/${kind}/${encodeURIComponent(id)}`, { query: { format } }),
    retry: false,
  });
  const shown = data?.format ?? format;

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
            <PageToolbarButton
              label="Open in New Tab"
              iconName={ExternalLink}
              onPress={() => window.open(fileUrl(kind, id, shown), '_blank', 'noopener')}
            />
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
        {data?.reader === 'pdf' ? (
          <iframe className={styles.frame} src={fileUrl(kind, id, shown)} title={data.title} />
        ) : null}
        {data?.reader === 'pages' ? <PageViewer kind={kind} id={id} pages={data.pages} title={data.title} /> : null}
        {data?.reader === 'epub' ? <EpubViewer url={fileUrl(kind, id, shown)} title={data.title} /> : null}
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
