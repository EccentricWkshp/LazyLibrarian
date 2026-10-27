import { MediaType } from './Queue';

export interface MissingBook {
  id: string;
  bookId: string;
  title: string;
  subtitle: string;
  author: string;
  authorId: string | null;
  mediaType: MediaType;
  added: string;
  published: string;
}

export interface CutoffBook extends MissingBook {
  // a magazine's issue date or a comic's issue number, '' for a book
  issue: string;
  // the quality of the file there is, and the one to upgrade until, as names
  quality: string;
  cutoff: string;
  profile: string;
}

export interface PagedResult<T> {
  page: number;
  pageSize: number;
  sortKey: string;
  sortDirection: 'ascending' | 'descending';
  totalRecords: number;
  records: T[];
}

export interface Release {
  id: string;
  title: string;
  indexer: string;
  protocol: string;
  size: number;
  seeders: number;
  score: number;
  quality: string;
  rejections: string[];
  approved: boolean;
}
