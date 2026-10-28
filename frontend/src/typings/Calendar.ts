// downloaded, being downloaded, out and not had, not out yet, or not looked for, as Sonarr's
export type CalendarState = 'downloaded' | 'downloading' | 'missing' | 'unreleased' | 'unmonitored';

export interface CalendarFormat {
  format: 'ebook' | 'audiobook';
  status: string;
  state: CalendarState;
}

export interface CalendarEntry {
  id: string;
  // a book, an issue there is, or one missing or due
  kind: 'book' | 'issue' | 'due';
  itemId: string;
  // yyyy-mm-dd
  date: string;
  title: string;
  subtitle: string;
  // the author's id or the magazine's title, and the author's name or the magazine's title
  parentId: string;
  parent: string;
  series: string;
  image: string;
  formats: CalendarFormat[];
  state: CalendarState;
  monitored: boolean;
}
