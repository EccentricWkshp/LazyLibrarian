// A settings section, as the Settings pages declare it: groups of fields, each a setting by its
// name with how it's shown, as Sonarr's settings fieldsets

export type FieldValue = string | number | boolean;
export type Values = Record<string, FieldValue>;

export interface ConfigValue {
  key: string;
  // bool, int, float, str, csv, url, email, folder, perm, interval or password
  kind: string;
  value: FieldValue;
  default: FieldValue;
  // an interval's: min, hour or day
  unit: string;
}

export interface Choice {
  value: string;
  label: string;
  example: string;
}

export interface ConfigChoices {
  themes: string[];
  uiLanguages: Choice[];
  authorDateFormats: Choice[];
  dateFormats: Choice[];
  issueDateFormats: Choice[];
  bookStatuses: string[];
  owner: string;
  // a language's value is its codes
  bookLanguages: Choice[];
  countries: Choice[];
  magazineLanguages: Choice[];
  dateLanguages: string[];
  specialLogs: Choice[];
}

export type Option = { key: string; value: string };

export interface Field {
  key: string;
  label: string;
  help?: string;
  // how it's shown when the kind isn't enough: a choice, a password, an API key with a new one button,
  // several lines, switches for a list of values separated by commas, the preferred languages
  input?: 'select' | 'password' | 'apikey' | 'textarea' | 'flags' | 'languages';
  // the choices of a select or flags, given, by name from /config/choices, or from the other settings
  options?: Option[];
  choices?:
    | 'themes'
    | 'uiLanguages'
    | 'authorDateFormats'
    | 'dateFormats'
    | 'issueDateFormats'
    | 'bookStatuses'
    | 'countries'
    | 'magazineLanguages'
    | 'dateLanguages'
    | 'specialLogs';
  optionsFor?: (values: Values) => Option[];
  // shown after a number
  unit?: string;
  placeholder?: string;
  // only with Show Advanced, as Sonarr's advanced settings
  advanced?: boolean;
  // only when the other settings make it matter
  showIf?: (values: Values) => boolean;
}

export interface Group {
  legend: string;
  help?: string;
  fields: Field[];
  advanced?: boolean;
  showIf?: (values: Values) => boolean;
  // buttons that test with the group's settings as they are on the page: POST /config/test
  tests?: { label: string; test: string }[];
  // buttons that run a command in the background, as System, Tasks does
  commands?: { label: string; command: string; help?: string }[];
}

export interface TestResult {
  ok: boolean;
  message: string;
  index: number | null;
}

export const INTERVAL_UNITS: Record<string, string> = { min: 'minutes', hour: 'hours', day: 'days' };

// the libraries an indexer is searched for, as its DLTYPES letters
export const DOWNLOAD_TYPES: Option[] = [
  { key: 'E', value: 'eBooks' },
  { key: 'A', value: 'Audiobooks' },
  { key: 'M', value: 'Magazines' },
  { key: 'C', value: 'Comics' },
];

export function splitList(value: FieldValue | undefined): string[] {
  return String(value ?? '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}
