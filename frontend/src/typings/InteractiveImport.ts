import { MediaType } from './Queue';

export interface ImportTarget {
  id: string;
  title: string;
  author: string;
  issue?: string;
  mediaType?: string;
}

export interface InteractiveImportItem {
  path: string;
  files: string[];
  relativePath: string;
  size: number;
  mediaType: MediaType;
  book: ImportTarget | null;
  queueId: number | null;
  rejections: string[];
}

export interface InteractiveImportFolder {
  folder: string;
  items: InteractiveImportItem[];
  error: string;
}

export interface LibraryBook {
  id: string;
  title: string;
  author: string;
  status: string | null;
  audioStatus: string | null;
}

export interface FileSystem {
  path: string;
  parent: string | null;
  directories: { name: string; path: string }[];
}

export interface CommandResult {
  path: string;
  imported: boolean;
  message: string;
}

export interface Command {
  id: number;
  name: string;
  status: 'queued' | 'started' | 'completed' | 'failed';
  message: string;
  queued: string;
  started: string | null;
  ended: string | null;
  result: CommandResult[] | null;
}
