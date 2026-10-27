// Reading in the browser and Send to Device, for an eBook, a magazine issue or a comic issue (its id
// comicid_issueid): where its file and reader are, and which formats can be read here
import { showMessage } from 'App/messagesStore';
import { api, urlBase } from 'Utilities/api';

export type ReadKind = 'book' | 'issue' | 'comic';

// the browser shows PDFs itself, the reader the others
const READABLE = ['pdf', 'epub', 'cbz', 'cbr', 'cb7'];

export function canRead(format: string) {
  return READABLE.includes(format.toLowerCase());
}

function formatQuery(format?: string) {
  return format ? `?format=${encodeURIComponent(format.toLowerCase())}` : '';
}

// the reader's page in the front end
export function readerPath(kind: ReadKind, id: string, format?: string) {
  return `/read/${kind}/${encodeURIComponent(id)}${formatQuery(format)}`;
}

// the file itself, to open in the browser or to save: its path, as a Link takes it, and its address
export function filePath(kind: ReadKind, id: string, format?: string, download = false) {
  const query = new URLSearchParams();
  if (format) {
    query.set('format', format.toLowerCase());
  }
  if (download) {
    query.set('download', 'true');
  }
  const search = query.toString();
  return `/api/v1/read/${kind}/${encodeURIComponent(id)}/file${search ? `?${search}` : ''}`;
}

export function fileUrl(kind: ReadKind, id: string, format?: string, download = false) {
  return `${urlBase()}${filePath(kind, id, format, download)}`;
}

export function pageUrl(kind: ReadKind, id: string, page: number, width = 0) {
  return `${urlBase()}/api/v1/read/${kind}/${encodeURIComponent(id)}/page/${page}${width ? `?width=${width}` : ''}`;
}

// emailed to the owner's devices, told of in the sidebar
export async function sendToDevice(kind: ReadKind, id: string, name: string, format?: string) {
  const messageId = `send-${kind}-${id}-${Date.now()}`;
  showMessage({ id: messageId, text: `Sending ${name}`, kind: 'info', isWorking: true });

  try {
    const result = await api<{ message: string }>(`/read/${kind}/${encodeURIComponent(id)}/send`, {
      method: 'POST',
      query: { format: format?.toLowerCase() },
    });
    showMessage({ id: messageId, text: result.message, kind: 'success', isWorking: false });
  } catch (error) {
    showMessage({ id: messageId, text: (error as Error).message, kind: 'danger', isWorking: false });
  }
}
