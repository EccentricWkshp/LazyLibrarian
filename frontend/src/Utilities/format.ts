const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

export function formatBytes(bytes: number) {
  if (!bytes) {
    return '';
  }

  let size = bytes;
  let unit = 0;

  while (size >= 1024 && unit < UNITS.length - 1) {
    size /= 1024;
    unit += 1;
  }

  return `${size.toFixed(unit ? 1 : 0)} ${UNITS[unit]}`;
}

// LazyLibrarian's dates are local time, 2026-10-26 10:57:14
export function parseDate(value: string) {
  if (!value) {
    return null;
  }

  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T'));

  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string) {
  const date = parseDate(value);

  return date ? date.toLocaleString() : value;
}

const RELATIVE: [number, Intl.RelativeTimeFormatUnit][] = [
  [60, 'second'],
  [60, 'minute'],
  [24, 'hour'],
  [7, 'day'],
  [4.35, 'week'],
  [12, 'month'],
  [Infinity, 'year'],
];

// like Sonarr's relative dates: 5 minutes ago, yesterday
export function relativeDate(value: string) {
  const date = parseDate(value);

  if (!date) {
    return value;
  }

  const format = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  let amount = (date.getTime() - Date.now()) / 1000;

  for (const [size, unit] of RELATIVE) {
    if (Math.abs(amount) < size) {
      return format.format(Math.round(amount), unit);
    }

    amount /= size;
  }

  return date.toLocaleDateString();
}
