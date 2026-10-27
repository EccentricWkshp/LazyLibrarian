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
