import { MediaType } from './Queue';

// Sonarr's history event types, for where a download got to
export type HistoryEventType = 'grabbed' | 'downloadFolderImported' | 'downloadFailed';

export interface HistoryItem {
  id: number;
  eventType: HistoryEventType;
  status: string;
  mediaType: MediaType;
  bookId: string;
  title: string;
  author: string;
  authorId: string | null;
  issue: string;
  sourceTitle: string;
  indexer: string;
  downloadClient: string;
  downloadId: string;
  protocol: string;
  size: number;
  date: string;
  message: string;
}

export interface BlocklistItem {
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
  size: number;
  date: string;
  message: string;
}
