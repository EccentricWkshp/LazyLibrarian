export type BookMediaType = 'ebook' | 'audiobook';

export interface AuthorLookup {
  id: string;
  name: string;
  source: string;
  inLibrary: boolean;
  loading: boolean;
  // how many of the books found are theirs
  books: number;
  score: number;
}

export interface BookLookup {
  id: string;
  title: string;
  subtitle: string;
  authorId: string;
  authorName: string;
  authorInLibrary: boolean;
  isbn: string;
  publisher: string;
  releaseDate: string;
  language: string;
  pages: number;
  genres: string;
  overview: string;
  cover: string;
  link: string;
  rating: number;
  ratings: number;
  source: string;
  score: number;
  inLibrary: boolean;
  status: string;
  audioStatus: string;
}

export interface Lookup {
  authors: AuthorLookup[];
  books: BookLookup[];
  mediaTypes: BookMediaType[];
}

export interface MagazineLookup {
  title: string;
  rejectWords: string;
  inLibrary: boolean;
  issues: number;
  // the periodical on Wikidata, empty for the title as it was typed
  wikidataId: string;
  description: string;
  started: string;
}

export interface ComicLookup {
  id: string;
  title: string;
  publisher: string;
  start: string;
  first: number;
  last: number;
  issues: number;
  overview: string;
  link: string;
  score: number;
  inLibrary: boolean;
}
