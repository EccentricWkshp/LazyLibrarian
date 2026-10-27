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
}

export interface Field {
  key: string;
  label: string;
  help?: string;
  // how it's shown when the kind isn't enough: a choice, a password, an API key with a new one button
  input?: 'select' | 'password' | 'apikey' | 'textarea';
  // the choices of a select, given or by name from /config/choices
  options?: { key: string; value: string }[];
  choices?: 'themes' | 'uiLanguages' | 'authorDateFormats' | 'dateFormats' | 'issueDateFormats' | 'bookStatuses';
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
}

export const INTERVAL_UNITS: Record<string, string> = { min: 'minutes', hour: 'hours', day: 'days' };
