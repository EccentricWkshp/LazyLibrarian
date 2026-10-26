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
  rejections: string[];
  approved: boolean;
}
