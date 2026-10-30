export type AuthorStatus = 'Active' | 'Wanted' | 'Paused' | 'Ignored' | 'Loading' | string;

export interface Author {
  id: string;
  name: string;
  sortName: string;
  status: AuthorStatus;
  image: string;
  lastBook: { id: string; title: string; date: string } | null;
  added: string;
  // books in the library, and the ones not ignored
  have: number;
  total: number;
  percent: number;
  source: string;
  addedReason: string;
}

export interface AuthorDetail extends Author {
  born: string;
  died: string;
  age: number | null;
  about: string;
  aka: string;
  links: { source: string; url: string }[];
  locked: boolean;
  ebookCounts: Record<string, number>;
  audioCounts: Record<string, number>;
  // the details filled in from the other info sources, and from which
  filledFrom: string;
}

export interface AuthorBook {
  id: string;
  title: string;
  subtitle: string;
  releaseDate: string;
  image: string;
  rating: number;
  language: string;
  genres: string;
  pages: number;
  status: string;
  audioStatus: string;
  // the format of the file the library has, empty when it has none
  ebookFormat: string;
  audioFormat: string;
  added: string;
  scanResult: string;
  isPrimary: boolean;
  series: { id: string; name: string; number: string }[];
}
