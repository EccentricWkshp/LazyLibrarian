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

// a release of a magazine, with the issue it is
export interface IssueRelease {
  id: string;
  title: string;
  indexer: string;
  protocol: string;
  size: number;
  // yyyy-mm-dd, '' when it came without a date
  posted: string;
  // as the library keeps it, '' when the name doesn't say
  issue: string;
  quality: string;
  rejections: string[];
  approved: boolean;
  // it's the issue searched for
  matches: boolean;
}
