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

function count(amount: number, unit: string) {
  return `${amount} ${unit}${amount === 1 ? '' : 's'}`;
}

// a task's interval, as Sonarr says it: 10 minutes, 6 hours, 1 day
export function formatInterval(minutes: number) {
  if (!minutes) {
    return '';
  }

  if (minutes % 1440 === 0) {
    return count(minutes / 1440, 'day');
  }

  if (minutes % 60 === 0) {
    return count(minutes / 60, 'hour');
  }

  return count(minutes, 'minute');
}

// how long something took: 0.4 seconds, 12 seconds, 3 minutes, 1 hour 5 minutes
export function formatDuration(seconds: number | null) {
  if (seconds === null || seconds < 0) {
    return '';
  }

  if (seconds < 10) {
    return `${Number(seconds.toFixed(1))} seconds`;
  }

  if (seconds < 60) {
    return count(Math.round(seconds), 'second');
  }

  const minutes = Math.round(seconds / 60);

  if (minutes < 60) {
    return count(minutes, 'minute');
  }

  const rest = minutes % 60;

  return rest ? `${count(Math.floor(minutes / 60), 'hour')} ${count(rest, 'minute')}` : count(minutes / 60, 'hour');
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
