// The download clients, indexers and notifiers the card pages show, Sonarr's implementations: each
// one's settings, the switch that turns it on, and its test. Most are settings of their own, the
// newznab, torznab, RSS, IRC, direct and Apprise ones are lists, set up as many times as wanted
import { DOWNLOAD_TYPES, Field, Values } from 'Settings/Sections/fields';

export interface Kind {
  // the settings' prefix, or a list's name: NEWZNAB
  id: string;
  name: string;
  description: string;
  // what it's grouped under when adding one
  protocol: string;
  // its settings are a list's items
  list?: boolean;
  // the switch that turns it on, a list's item has ENABLED
  enable?: string;
  // shown as set up when this is set, even switched off
  address?: string;
  // the test that checks it works, a list's items are tested by their index
  test?: string;
  fields: Field[];
  // the events a notifier is sent
  triggers?: { key: string; label: string }[];
}

const LIBRARY_CATEGORY: [string, string][] = [
  ['', 'eBook'],
  ['_AUDIO', 'Audiobook'],
  ['_MAG', 'Magazine'],
  ['_COMIC', 'Comic'],
];

function categories(setting: string, noun: string): Field[] {
  return LIBRARY_CATEGORY.map(([suffix, library], index) => ({
    key: `${setting}${suffix}`,
    label: `${library} ${noun}`,
    help: index ? undefined : `A ${noun} for each library lets the client keep them apart, and tells our downloads from others`,
    advanced: index > 0,
  }));
}

function client(
  id: string,
  name: string,
  protocol: string,
  enable: string,
  prefix: string,
  fields: Field[],
  description: string
): Kind {
  return { id, name, protocol, enable, address: `${prefix}_HOST`, test: id, fields, description };
}

const HOST = (prefix: string, help = 'With http:// or https:// for a web address'): Field => ({
  key: `${prefix}_HOST`,
  label: 'Host',
  placeholder: 'localhost',
  help,
});
const LOGIN = (prefix: string): Field[] => [
  { key: `${prefix}_USER`, label: 'Username' },
  { key: `${prefix}_PASS`, label: 'Password', input: 'password' },
];

export const DOWNLOAD_CLIENTS: Kind[] = [
  client(
    'SABNZBD',
    'SABnzbd',
    'Usenet',
    'NZB_DOWNLOADER_SABNZBD',
    'SAB',
    [
      HOST('SAB'),
      { key: 'SAB_PORT', label: 'Port' },
      { key: 'SAB_SUBDIR', label: 'URL Base', advanced: true },
      { key: 'SAB_API', label: 'API Key', input: 'password' },
      ...LOGIN('SAB'),
      ...categories('SAB_CAT', 'category'),
      { key: 'SAB_DELETE', label: "Remove from SABnzbd's history", help: 'Once imported, or failed' },
      {
        key: 'SAB_EXTERNAL_HOST',
        label: 'LazyLibrarian for SABnzbd',
        help: 'The address SABnzbd fetches the nzb from LazyLibrarian at, when it reaches us at another one',
        advanced: true,
      },
    ],
    'The usenet client'
  ),
  client(
    'NZBGET',
    'NZBGet',
    'Usenet',
    'NZB_DOWNLOADER_NZBGET',
    'NZBGET',
    [
      HOST('NZBGET'),
      { key: 'NZBGET_PORT', label: 'Port' },
      ...LOGIN('NZBGET'),
      ...categories('NZBGET_CATEGORY', 'category'),
      { key: 'NZBGET_PRIORITY', label: 'Priority', help: '-100 very low to 100 very high, 0 normal', advanced: true },
    ],
    'The usenet client'
  ),
  {
    id: 'NZB_BLACKHOLE',
    name: 'Usenet Blackhole',
    protocol: 'Usenet',
    enable: 'NZB_DOWNLOADER_BLACKHOLE',
    address: 'NZB_BLACKHOLEDIR',
    description: 'The nzb is saved in a folder another program watches',
    fields: [{ key: 'NZB_BLACKHOLEDIR', label: 'Nzb Folder' }],
  },
  client(
    'QBITTORRENT',
    'qBittorrent',
    'Torrents',
    'TOR_DOWNLOADER_QBITTORRENT',
    'QBITTORRENT',
    [
      HOST('QBITTORRENT'),
      { key: 'QBITTORRENT_PORT', label: 'Port' },
      { key: 'QBITTORRENT_BASE', label: 'URL Base', advanced: true },
      ...LOGIN('QBITTORRENT'),
      ...categories('QBITTORRENT_LABEL', 'category'),
      { key: 'QBITTORRENT_DIR', label: 'Download folder', help: "Empty for qBittorrent's own", advanced: true },
      { key: 'QBITTORRENT_IGNORE_SSL', label: "Don't check the SSL certificate", advanced: true },
      { key: 'QBITTORRENT_NOAUTH', label: 'No login, only HTTP basic authentication', advanced: true },
    ],
    'The torrent client'
  ),
  client(
    'TRANSMISSION',
    'Transmission',
    'Torrents',
    'TOR_DOWNLOADER_TRANSMISSION',
    'TRANSMISSION',
    [
      HOST('TRANSMISSION'),
      { key: 'TRANSMISSION_PORT', label: 'Port' },
      { key: 'TRANSMISSION_BASE', label: 'URL Base', placeholder: '/transmission/', advanced: true },
      ...LOGIN('TRANSMISSION'),
      ...categories('TRANSMISSION_LABEL', 'label'),
      { key: 'TRANSMISSION_DIR', label: 'Download folder', help: "Empty for Transmission's own", advanced: true },
    ],
    'The torrent client'
  ),
  client(
    'DELUGE',
    'Deluge',
    'Torrents',
    'TOR_DOWNLOADER_DELUGE',
    'DELUGE',
    [
      HOST('DELUGE', 'With a username, the daemon is used: its host without http://'),
      { key: 'DELUGE_PORT', label: 'Port', help: "The daemon's port with a username, the web UI's without" },
      { key: 'DELUGE_BASE', label: 'URL Base', advanced: true },
      { key: 'DELUGE_CERT', label: 'Certificate', help: 'For the web UI over https', advanced: true },
      ...LOGIN('DELUGE'),
      ...categories('DELUGE_LABEL', 'label'),
      { key: 'DELUGE_DIR', label: 'Download folder', help: "Empty for Deluge's own", advanced: true },
    ],
    'The torrent client, its web UI or its daemon'
  ),
  client(
    'RTORRENT',
    'rTorrent',
    'Torrents',
    'TOR_DOWNLOADER_RTORRENT',
    'RTORRENT',
    [
      HOST('RTORRENT', "Its XMLRPC address, like http://host:8080/RPC2"),
      ...LOGIN('RTORRENT'),
      ...categories('RTORRENT_LABEL', 'label'),
      { key: 'RTORRENT_DIR', label: 'Download folder', advanced: true },
    ],
    'The torrent client'
  ),
  client(
    'UTORRENT',
    'uTorrent',
    'Torrents',
    'TOR_DOWNLOADER_UTORRENT',
    'UTORRENT',
    [
      HOST('UTORRENT'),
      { key: 'UTORRENT_PORT', label: 'Port' },
      { key: 'UTORRENT_BASE', label: 'URL Base', advanced: true },
      ...LOGIN('UTORRENT'),
      ...categories('UTORRENT_LABEL', 'label'),
    ],
    'The torrent client'
  ),
  {
    id: 'TOR_BLACKHOLE',
    name: 'Torrent Blackhole',
    protocol: 'Torrents',
    enable: 'TOR_DOWNLOADER_BLACKHOLE',
    address: 'TORRENT_DIR',
    description: 'The torrent is saved in a folder another program watches',
    fields: [
      { key: 'TORRENT_DIR', label: 'Torrent Folder' },
      { key: 'TOR_CONVERT_MAGNET', label: 'Turn magnet links into torrent files' },
    ],
  },
  client(
    'SYNOLOGY',
    'Download Station',
    'Usenet and Torrents',
    'USE_SYNOLOGY',
    'SYNOLOGY',
    [
      HOST('SYNOLOGY'),
      { key: 'SYNOLOGY_PORT', label: 'Port' },
      ...LOGIN('SYNOLOGY'),
      { key: 'SYNOLOGY_DIR', label: 'Download folder' },
      { key: 'NZB_DOWNLOADER_SYNOLOGY', label: 'Use it for usenet' },
      { key: 'TOR_DOWNLOADER_SYNOLOGY', label: 'Use it for torrents' },
    ],
    "Synology's download manager"
  ),
];

const SEARCH_FOR: Field = {
  key: 'DLTYPES',
  label: 'Search it for',
  input: 'flags',
  options: DOWNLOAD_TYPES,
};
const PRIORITY: Field = {
  key: 'DLPRIORITY',
  label: 'Priority',
  help: 'A higher one is preferred, when the results match as well. See Priority weighting',
};

function newznab(id: string, name: string, protocol: string, extra: Field[], description: string): Kind {
  return {
    id,
    name,
    protocol,
    list: true,
    enable: 'ENABLED',
    address: 'HOST',
    description,
    fields: [
      { key: 'DISPNAME', label: 'Name' },
      { key: 'ENABLED', label: 'Enable' },
      { key: 'HOST', label: 'URL', placeholder: 'https://indexer.example' },
      { key: 'API', label: 'API Key', input: 'password' },
      SEARCH_FOR,
      PRIORITY,
      ...extra,
      { key: 'APILIMIT', label: 'Daily API limit', help: '0 for none', advanced: true },
      { key: 'RATELIMIT', label: 'Time between searches', unit: 'seconds', advanced: true },
      {
        key: 'MANUAL',
        label: 'Keep what it searches as set here',
        help: "Otherwise it's asked what it can search when it's added or tested, and every so often",
        advanced: true,
      },
      { key: 'GENERALSEARCH', label: 'General search', advanced: true },
      { key: 'BOOKSEARCH', label: 'eBook search', advanced: true },
      { key: 'AUDIOSEARCH', label: 'Audiobook search', advanced: true },
      { key: 'MAGSEARCH', label: 'Magazine search', advanced: true },
      { key: 'COMICSEARCH', label: 'Comic search', advanced: true },
      { key: 'BOOKCAT', label: 'eBook categories', help: 'Separated by commas', advanced: true },
      { key: 'AUDIOCAT', label: 'Audiobook categories', advanced: true },
      { key: 'MAGCAT', label: 'Magazine categories', advanced: true },
      { key: 'COMICCAT', label: 'Comic categories', advanced: true },
      { key: 'EXTENDED', label: 'Extended search', help: '1 to ask for extended results', advanced: true },
    ],
  };
}

const SEEDING: Field[] = [
  { key: 'SEED_RATIO', label: 'Seed ratio', help: "The ratio to seed to, 0 for the client's own", advanced: true },
  { key: 'SEED_DURATION', label: 'Seed time', unit: 'minutes', help: "0 for the client's own", advanced: true },
];

function single(
  id: string,
  name: string,
  protocol: string,
  fields: Field[],
  description: string,
  address?: string
): Kind {
  return {
    id,
    name,
    protocol,
    enable: id,
    address,
    test: id,
    description,
    fields: [
      { key: id, label: 'Enable' },
      ...fields,
      { ...SEARCH_FOR, key: `${id}_DLTYPES` },
      { ...PRIORITY, key: `${id}_DLPRIORITY` },
    ],
  };
}

const TORRENT_SITE = (id: string, name: string, description: string) =>
  single(
    id,
    name,
    'Torrents',
    [
      { key: `${id}_HOST`, label: 'Host' },
      { key: `${id}_SEEDERS`, label: 'Minimum seeders' },
    ],
    description
  );

export const INDEXERS: Kind[] = [
  newznab('NEWZNAB', 'Newznab', 'Usenet', [], 'A usenet indexer'),
  newznab(
    'TORZNAB',
    'Torznab',
    'Torrents',
    [{ key: 'SEEDERS', label: 'Minimum seeders' }, ...SEEDING],
    'A torrent indexer, or Prowlarr and Jackett'
  ),
  {
    id: 'RSS',
    name: 'RSS or Wishlist',
    protocol: 'Torrents',
    list: true,
    enable: 'ENABLED',
    address: 'HOST',
    description: "A feed of releases, or a wishlist: Goodreads, Amazon charts, the NY Times, MAM's",
    fields: [
      { key: 'DISPNAME', label: 'Name' },
      { key: 'ENABLED', label: 'Enable' },
      { key: 'HOST', label: 'URL' },
      { key: 'LABEL', label: 'Label', help: "What it is, for a feed the address doesn't tell: like MAM wishlist" },
      SEARCH_FOR,
      PRIORITY,
      ...SEEDING,
    ],
  },
  {
    id: 'IRC',
    name: 'IRC',
    protocol: 'IRC',
    list: true,
    enable: 'ENABLED',
    address: 'SERVER',
    description: 'An IRC channel with a search bot',
    fields: [
      { key: 'DISPNAME', label: 'Name' },
      { key: 'ENABLED', label: 'Enable' },
      { key: 'SERVER', label: 'Server', placeholder: 'irc.irchighway.net' },
      { key: 'CHANNEL', label: 'Channel', placeholder: '#ebooks' },
      { key: 'BOTNICK', label: 'Nickname' },
      { key: 'SEARCH', label: 'Search command', placeholder: '@search' },
      SEARCH_FOR,
      PRIORITY,
    ],
  },
  TORRENT_SITE('TPB', 'The Pirate Bay', 'A public torrent site'),
  TORRENT_SITE('TDL', 'TorrentDownloads', 'A public torrent site'),
  TORRENT_SITE('LIME', 'LimeTorrents', 'A public torrent site'),
  TORRENT_SITE('ABB', 'AudioBookBay', 'A public audiobook torrent site'),
  single(
    'ANNA',
    "Anna's Archive",
    'Direct',
    [
      { key: 'ANNA_HOST', label: 'Host' },
      { key: 'ANNA_KEY', label: 'Member key', input: 'password', help: 'For the API, paid members only' },
      { key: 'ANNA_DLLIMIT', label: 'Downloads a day', help: '0 for no limit' },
      { key: 'ANNA_MAX_SERVERS', label: 'Servers to try', help: 'When a download fails', advanced: true },
      {
        key: 'ANNA_SEARCH_LANG',
        label: 'Search languages',
        help: 'Empty for the preferred languages, see Languages. Or codes separated by commas: EN, DE, or ANY',
        advanced: true,
      },
    ],
    'Downloads books directly'
  ),
  single(
    'BOK',
    'Z-Library',
    'Direct',
    [
      { key: 'BOK_HOST', label: 'Host' },
      { key: 'BOK_EMAIL', label: 'Email', help: 'An account downloads more a day' },
      { key: 'BOK_PASS', label: 'Password', input: 'password' },
      { key: 'BOK_REMIX_USERID', label: 'Remix user ID', advanced: true },
      { key: 'BOK_REMIX_USERKEY', label: 'Remix user key', input: 'password', advanced: true },
      { key: 'BOK_DLLIMIT', label: 'Downloads a day' },
      {
        key: 'BOK_SEARCH_LANG',
        label: 'Search languages',
        help: 'Empty for the preferred languages, see Languages. Or names separated by commas: spanish, german, or ANY',
        advanced: true,
      },
    ],
    'Downloads books directly'
  ),
  single(
    'SLSK',
    'Soulseek',
    'Direct',
    [
      { key: 'SLSK_HOST', label: 'slskd address' },
      { key: 'SLSK_API', label: 'API Key', input: 'password' },
      { key: 'SLSK_URLBASE', label: 'URL Base', advanced: true },
    ],
    'Downloads through an slskd daemon'
  ),
  single(
    'WEBSHARE',
    'Webshare',
    'Direct',
    [
      { key: 'WEBSHARE_USER', label: 'Username', help: 'It searches and downloads without an account too' },
      { key: 'WEBSHARE_PASS', label: 'Password', input: 'password' },
    ],
    'Downloads books directly'
  ),
  {
    id: 'GEN',
    name: 'Direct Download Site',
    protocol: 'Direct',
    list: true,
    enable: 'ENABLED',
    address: 'HOST',
    description: 'A site searched by its address, as a libgen mirror',
    fields: [
      { key: 'DISPNAME', label: 'Name' },
      { key: 'ENABLED', label: 'Enable' },
      { key: 'HOST', label: 'Server' },
      { key: 'SEARCH', label: 'Search page' },
      SEARCH_FOR,
      PRIORITY,
    ],
  },
];

const ON_GRAB = 'On Grab';
const ON_IMPORT = 'On Import';

function notifier(
  id: string,
  name: string,
  snatch: string,
  download: string,
  address: string,
  fields: Field[],
  description: string
): Kind {
  return {
    id,
    name,
    protocol: 'Notifications',
    enable: `USE_${id}`,
    address,
    test: id,
    description,
    triggers: [
      { key: snatch, label: ON_GRAB },
      { key: download, label: ON_IMPORT },
    ],
    fields: [
      { key: `USE_${id}`, label: 'Enable' },
      { key: snatch, label: ON_GRAB, help: 'When a release is sent to a download client' },
      { key: download, label: ON_IMPORT, help: "When it's imported into the library" },
      ...fields,
    ],
  };
}

export const NOTIFIERS: Kind[] = [
  {
    id: 'APPRISE',
    name: 'Apprise',
    protocol: 'Notifications',
    list: true,
    address: 'URL',
    description: 'Any of the services Apprise sends to, by an Apprise URL',
    triggers: [
      { key: 'SNATCH', label: ON_GRAB },
      { key: 'DOWNLOAD', label: ON_IMPORT },
    ],
    fields: [
      { key: 'DISPNAME', label: 'Name' },
      { key: 'SNATCH', label: ON_GRAB, help: 'When a release is sent to a download client' },
      { key: 'DOWNLOAD', label: ON_IMPORT, help: "When it's imported into the library" },
      { key: 'URL', label: 'URL', placeholder: 'tgram://bottoken/ChatID', help: 'See the Apprise wiki for each service' },
    ],
  },
  notifier(
    'EMAIL',
    'Email',
    'EMAIL_NOTIFY_ONSNATCH',
    'EMAIL_NOTIFY_ONDOWNLOAD',
    'EMAIL_TO',
    [
      { key: 'EMAIL_SENDFILE_ONDOWNLOAD', label: 'Attach the book', help: 'To send it to an e-reader' },
      { key: 'EMAIL_FROM', label: 'From' },
      { key: 'EMAIL_TO', label: 'To' },
      { key: 'EMAIL_SMTP_SERVER', label: 'SMTP server' },
      { key: 'EMAIL_SMTP_PORT', label: 'Port' },
      { key: 'EMAIL_SMTP_USER', label: 'Username' },
      { key: 'EMAIL_SMTP_PASSWORD', label: 'Password', input: 'password' },
      { key: 'EMAIL_SSL', label: 'SSL' },
      { key: 'EMAIL_TLS', label: 'TLS' },
      {
        key: 'EMAIL_SEND_TYPE',
        label: 'Send as',
        help: 'A format to send instead, converted with Calibre: like mobi for a Kindle',
        advanced: true,
      },
      { key: 'EMAIL_CONVERT_FROM', label: 'Convert from', help: 'The formats that are converted, separated by commas', advanced: true },
    ],
    'An email, the book attached if wanted'
  ),
  notifier(
    'PUSHOVER',
    'Pushover',
    'PUSHOVER_ONSNATCH',
    'PUSHOVER_ONDOWNLOAD',
    'PUSHOVER_KEYS',
    [
      { key: 'PUSHOVER_APITOKEN', label: 'API Token', input: 'password' },
      { key: 'PUSHOVER_KEYS', label: 'User Key' },
      { key: 'PUSHOVER_DEVICE', label: 'Devices', help: 'Empty for all of them' },
      {
        key: 'PUSHOVER_PRIORITY',
        label: 'Priority',
        input: 'select',
        options: [
          { key: '-2', value: 'Lowest' },
          { key: '-1', value: 'Low' },
          { key: '0', value: 'Normal' },
          { key: '1', value: 'High' },
        ],
      },
    ],
    'Push notifications'
  ),
  notifier(
    'PUSHBULLET',
    'Pushbullet',
    'PUSHBULLET_NOTIFY_ONSNATCH',
    'PUSHBULLET_NOTIFY_ONDOWNLOAD',
    'PUSHBULLET_TOKEN',
    [
      { key: 'PUSHBULLET_TOKEN', label: 'Access Token', input: 'password' },
      { key: 'PUSHBULLET_DEVICEID', label: 'Device ID', help: 'Empty for all of them' },
    ],
    'Push notifications'
  ),
  notifier(
    'TELEGRAM',
    'Telegram',
    'TELEGRAM_ONSNATCH',
    'TELEGRAM_ONDOWNLOAD',
    'TELEGRAM_TOKEN',
    [
      { key: 'TELEGRAM_TOKEN', label: 'Bot Token', input: 'password' },
      { key: 'TELEGRAM_USERID', label: 'Chat ID' },
    ],
    'A message from a Telegram bot'
  ),
  notifier(
    'SLACK',
    'Slack',
    'SLACK_NOTIFY_ONSNATCH',
    'SLACK_NOTIFY_ONDOWNLOAD',
    'SLACK_TOKEN',
    [
      { key: 'SLACK_URL', label: 'Webhook URL' },
      { key: 'SLACK_TOKEN', label: 'Webhook Token', input: 'password', help: 'All of the webhook URL after /services/' },
    ],
    'A message in a Slack channel'
  ),
  notifier(
    'PROWL',
    'Prowl',
    'PROWL_ONSNATCH',
    'PROWL_ONDOWNLOAD',
    'PROWL_APIKEY',
    [
      { key: 'PROWL_APIKEY', label: 'API Keys', input: 'password', help: 'Separated by commas' },
      {
        key: 'PROWL_PRIORITY',
        label: 'Priority',
        input: 'select',
        options: [
          { key: '-2', value: 'Very Low' },
          { key: '-1', value: 'Moderate' },
          { key: '0', value: 'Normal' },
          { key: '1', value: 'High' },
          { key: '2', value: 'Emergency' },
        ],
      },
    ],
    'Push notifications on iOS'
  ),
  notifier(
    'CUSTOM',
    'Custom Script',
    'CUSTOM_NOTIFY_ONSNATCH',
    'CUSTOM_NOTIFY_ONDOWNLOAD',
    'CUSTOM_SCRIPT',
    [{ key: 'CUSTOM_SCRIPT', label: 'Script', help: 'Run with the event and the book' }],
    'Runs a program of yours'
  ),
];

// the settings a kind's switch and fields have, for a kind that isn't a list
export function kindKeys(kind: Kind) {
  return [...(kind.enable ? [kind.enable] : []), ...kind.fields.map((field) => field.key)];
}

export function isOn(kind: Kind, values: Values) {
  return kind.enable ? !!values[kind.enable] : (kind.triggers ?? []).some((trigger) => !!values[trigger.key]);
}
