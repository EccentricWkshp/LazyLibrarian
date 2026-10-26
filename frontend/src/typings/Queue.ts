export type MediaType = 'ebook' | 'audiobook' | 'magazine' | 'comic';

export interface StatusMessage {
  title: string;
  messages: string[];
}

// Sonarr's: completed, importBlocked and warning is a download that couldn't be imported
export type QueueStatus = 'downloading' | 'completed' | 'warning' | 'downloadClientUnavailable';
export type TrackedDownloadState = 'downloading' | 'importPending' | 'importBlocked';
export type TrackedDownloadStatus = 'ok' | 'warning' | 'error';

export interface QueueItem {
  id: number;
  mediaType: MediaType;
  bookId: string;
  title: string;
  author: string;
  authorId: string | null;
  issue: string;
  sourceTitle: string;
  indexer: string;
  protocol: string;
  downloadClient: string;
  downloadId: string;
  size: number;
  added: string;
  progress: number;
  status: QueueStatus;
  trackedDownloadState: TrackedDownloadState;
  trackedDownloadStatus: TrackedDownloadStatus;
  statusMessages: StatusMessage[];
  errorMessage: string;
}

export const MEDIA_TYPE_NAMES: Record<MediaType, string> = {
  ebook: 'eBook',
  audiobook: 'Audiobook',
  magazine: 'Magazine',
  comic: 'Comic',
};
