// Dates as Settings, UI says to show them, as the old pages' date_format does: a book's date and
// the others, an author's born and died, and an issue's date. An issue number or a year shows as it is
import { useQuery } from '@tanstack/react-query';
import { api } from './api';

interface DateFormats {
  dateFormat: string;
  authorDateFormat: string;
  issueDateFormat: string;
  // January to December, each [name, short name]
  months: string[][];
}

// $Y year, $y two digits, $m month, $d day, $D day unless it's the 1st, $B month name, $b short name
export function formatDate(value: string, format: string, months: string[][] = []) {
  const text = (value ?? '').trim();
  const found = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?/.exec(text);

  if (!text || !format || /^-?\d+$/.test(text) || !found) {
    return text;
  }

  const [, year, month, day] = found;
  if (!month || Number(month) < 1 || Number(month) > 12) {
    return year;
  }

  const m = month.padStart(2, '0');
  const d = (day ?? '01').padStart(2, '0');
  const names = months[Number(m) - 1] ?? [];

  return format
    .replace('$Y', year)
    .replace('$y', year.slice(2))
    .replace('$m', m)
    .replace('$D', d === '01' ? '' : d)
    .replace('$d', d)
    .replace('$B', names[0] ?? m)
    .replace('$b', names[1] ?? names[0] ?? m)
    .split(/\s+/)
    .join(' ')
    .trim();
}

// the formatters, which show dates as stored until the settings are in
export function useDates() {
  const { data } = useQuery({
    queryKey: ['config', 'dates'],
    queryFn: () => api<DateFormats>('/config/dates'),
    staleTime: Infinity,
  });
  const months = data?.months ?? [];

  return {
    date: (value: string) => formatDate(value, data?.dateFormat ?? '', months),
    author: (value: string) => formatDate(value, data?.authorDateFormat ?? '', months),
    issue: (value: string) => formatDate(value, data?.issueDateFormat ?? '', months),
  };
}
