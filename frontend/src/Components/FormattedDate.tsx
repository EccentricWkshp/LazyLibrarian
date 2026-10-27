// A date as Settings, UI says to show it: a book's or another (date), an author's born or died
// (author), or an issue's (issue)
import { useDates } from 'Utilities/dates';

function FormattedDate({ value, kind = 'date' }: { value: string; kind?: 'date' | 'author' | 'issue' }) {
  const dates = useDates();

  return <>{dates[kind](value)}</>;
}

export default FormattedDate;
