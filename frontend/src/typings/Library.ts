export interface SeriesRef {
  id: string;
  name: string;
  number: string;
}

export interface LibraryBook {
  id: string;
  title: string;
  subtitle: string;
  authorId: string;
  authorName: string;
  series: SeriesRef[];
  releaseDate: string;
  image: string;
  rating: number;
  language: string;
  status: string;
  // the format of the file the library has, empty when it has none
  format: string;
  // when it came into the library
  added: string;
  // the reading list it's on
  readingList: string;
  // searches that found nothing, the last, and the hours until the next
  search: { count: number; last: string; interval: number } | null;
}

export interface BookFile {
  path: string;
  format: string;
  size: number;
  exists: boolean;
}

export interface BookDownload {
  id: number;
  title: string;
  indexer: string;
  date: string;
  status: string;
  source: string;
  mediaType: 'ebook' | 'audiobook';
  message: string;
}

export interface BookDetail {
  id: string;
  title: string;
  subtitle: string;
  authorId: string;
  authorName: string;
  series: SeriesRef[];
  releaseDate: string;
  originalDate: string;
  publisher: string;
  isbn: string;
  pages: number;
  language: string;
  genres: string;
  rating: number;
  image: string;
  description: string;
  narrator: string;
  locked: boolean;
  added: string;
  links: { source: string; id: string; url: string }[];
  status: string;
  audioStatus: string;
  ebookFormat: string;
  audioFormat: string;
  scanResult: string;
  ebookFile: BookFile | null;
  audioFile: BookFile | null;
  downloads: BookDownload[];
}

export interface Magazine {
  title: string;
  status: string;
  issues: number;
  latestIssue: string;
  lastAcquired: string;
  cover: string;
  added: string;
  rejectWords: string;
  language: string;
  genre: string;
}

export interface MagazineIssue {
  id: string;
  date: string;
  acquired: string;
  cover: string;
  format: string;
}

export interface MagazineDetail extends Magazine {
  issueList: MagazineIssue[];
}

export interface Comic {
  id: string;
  title: string;
  status: string;
  issues: number;
  latestIssue: string;
  lastAcquired: string;
  cover: string;
  added: string;
  publisher: string;
  start: string;
  first: number;
  last: number;
  overview: string;
  link: string;
}

export interface ComicIssue {
  id: string;
  acquired: string;
  cover: string;
  overview: string;
  format: string;
}

export interface ComicDetail extends Comic {
  issueList: ComicIssue[];
}

export interface Series {
  id: string;
  name: string;
  status: string;
  authorId: string;
  authorName: string;
  have: number;
  total: number;
  percent: number;
  source: string;
}

export interface SeriesBook {
  id: string;
  title: string;
  subtitle: string;
  number: string;
  authorId: string;
  authorName: string;
  image: string;
  releaseDate: string;
  status: string;
  audioStatus: string;
  ebookFormat: string;
  audioFormat: string;
}

export interface SeriesDetail extends Series {
  books: SeriesBook[];
}
