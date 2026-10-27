// Sonarr's Settings, General: where LazyLibrarian listens, who can log in, the API, the proxy,
// logging, updates, backups, and the RSS and OPDS servers
import { Group } from './fields';
import SettingsSection from './SettingsSection';

const GROUPS: Group[] = [
  {
    legend: 'Host',
    fields: [
      { key: 'HTTP_HOST', label: 'Bind Address', help: '0.0.0.0 for every address, a restart is needed' },
      { key: 'HTTP_PORT', label: 'Port Number', help: 'A restart is needed' },
      { key: 'HTTP_ROOT', label: 'URL Base', help: 'For a reverse proxy, like /lazylibrarian. A restart is needed' },
      {
        key: 'HTTP_PROXY',
        label: 'Behind a reverse proxy',
        help: 'Trust the proxy headers for the address a request came from',
        advanced: true,
      },
      { key: 'HTTPS_ENABLED', label: 'Enable SSL', help: 'A restart is needed' },
      { key: 'HTTPS_CERT', label: 'SSL Cert Path', showIf: (v) => !!v.HTTPS_ENABLED },
      { key: 'HTTPS_KEY', label: 'SSL Key Path', showIf: (v) => !!v.HTTPS_ENABLED },
      { key: 'LAUNCH_BROWSER', label: 'Open the browser on start', advanced: true },
    ],
  },
  {
    legend: 'Security',
    fields: [
      {
        key: 'AUTH_TYPE',
        label: 'Authentication',
        input: 'select',
        options: [
          { key: 'FORM', value: 'Forms (Login Page)' },
          { key: 'BASIC', value: 'Basic (Browser Popup)' },
          { key: 'EXTERNAL', value: 'External (Reverse Proxy)' },
        ],
      },
      {
        key: 'PROXY_AUTH_USER',
        label: 'Proxy Auth User Header',
        placeholder: 'Remote-User',
        help: 'Your reverse proxy logs you in and sends your username in this header. Only use this if LazyLibrarian cannot be reached without going through the proxy',
        showIf: (v) => v.AUTH_TYPE === 'EXTERNAL',
      },
      {
        key: 'AUTH_REQUIRED',
        label: 'Authentication Required',
        input: 'select',
        options: [
          { key: 'ENABLED', value: 'Enabled' },
          { key: 'DISABLED_LOCAL', value: 'Disabled for Local Addresses' },
        ],
        help: 'Behind a reverse proxy, set it to send the address the request came from, or every request looks local',
      },
      { key: 'OWNER_USERNAME', label: 'Username' },
      { key: 'OWNER_PASSWORD', label: 'Password', input: 'password', help: 'Leave it empty to keep the password' },
      { key: 'OWNER_PASSWORD2', label: 'Password Confirmation', input: 'password' },
      {
        key: 'WHITELIST',
        label: 'Admin addresses',
        help: 'Addresses that are always let in, separated by commas',
        advanced: true,
      },
      { key: 'ADMIN_EMAIL', label: 'Contact Email', help: 'Sent to the info sources with requests, as some ask' },
    ],
  },
  {
    legend: 'API',
    fields: [
      { key: 'API_ENABLED', label: 'Enable the API' },
      {
        key: 'API_KEY',
        label: 'API Key',
        input: 'apikey',
        help: 'Applications send the key in an X-Api-Key header, or as an apikey parameter in the url',
        showIf: (v) => !!v.API_ENABLED,
      },
      {
        key: 'API_RO_KEY',
        label: 'Read-Only API Key',
        input: 'apikey',
        help: 'Can only look, nothing is changed with it',
        showIf: (v) => !!v.API_ENABLED,
      },
    ],
  },
  {
    legend: 'Proxy',
    fields: [
      { key: 'PROXY_HOST', label: 'Proxy', placeholder: 'http://proxy:8080' },
      { key: 'PROXY_TYPE', label: 'Use it for', help: 'Separated by commas: http, https', showIf: (v) => !!v.PROXY_HOST },
      {
        key: 'FALLBACK_PROXY',
        label: 'Fallback Proxy',
        help: 'Tried when a site answers with a challenge (403, 429, 503): a Tor socks5 proxy, Byparr or FlareSolverr',
        advanced: true,
      },
      { key: 'SSL_VERIFY', label: 'Check SSL certificates', advanced: true },
      { key: 'SSL_CERTS', label: 'Certificate Bundle', help: 'A file of certificates to trust, empty for the usual ones', advanced: true },
    ],
  },
  {
    legend: 'Logging',
    fields: [
      {
        key: 'LOGLEVEL',
        label: 'Log Level',
        input: 'select',
        options: [
          { key: '50', value: 'Quiet' },
          { key: '20', value: 'Normal' },
          { key: '10', value: 'Debug' },
        ],
      },
      { key: 'LOGDIR', label: 'Log Folder', advanced: true },
      { key: 'LOGLIMIT', label: 'Lines on screen', advanced: true },
      { key: 'LOGFILES', label: 'Log files kept', advanced: true },
      { key: 'LOGSIZE', label: 'Log file size', unit: 'bytes', advanced: true },
      { key: 'LOGREDACT', label: 'Redact the on-screen log' },
      { key: 'HOSTREDACT', label: 'Redact host names too', showIf: (v) => !!v.LOGREDACT },
      { key: 'LOGFILEREDACT', label: 'Redact the log files' },
      {
        key: 'LOGSPECIALDEBUG',
        label: 'Debug logs of',
        input: 'flags',
        choices: 'specialLogs',
        help: 'More detail on these, with the Debug log level',
        advanced: true,
      },
    ],
  },
  {
    legend: 'Updates',
    fields: [
      { key: 'VERSIONCHECK_INTERVAL', label: 'Check for updates every', help: '0 never checks' },
      { key: 'AUTO_UPDATE', label: 'Install updates automatically', help: 'When the scheduled check finds one' },
      { key: 'GIT_PROGRAM', label: 'git Program', help: 'Only if git is not on the path', advanced: true },
    ],
  },
  {
    legend: 'Backups',
    fields: [
      { key: 'BACKUP_DB', label: 'Back up every', unit: 'days', help: 'See System, Backup. 0 never backs up' },
      { key: 'BACKUP_RETENTION', label: 'Keep scheduled backups for', unit: 'days' },
    ],
  },
  {
    legend: 'Cache',
    advanced: true,
    fields: [
      {
        key: 'CACHE_AGE',
        label: 'Keep what is looked up for',
        unit: 'days',
        help: 'And refresh authors and series this often',
      },
    ],
  },
  {
    legend: 'RSS',
    help: 'Feeds of the latest downloads, for a reader',
    advanced: true,
    fields: [
      { key: 'RSS_ENABLED', label: 'Enable RSS' },
      { key: 'RSS_HOST', label: 'Feed address', help: 'Only to change the address the feeds link to', showIf: (v) => !!v.RSS_ENABLED },
      { key: 'RSS_PODCAST', label: 'Audiobooks as podcasts', showIf: (v) => !!v.RSS_ENABLED },
    ],
  },
  {
    legend: 'OPDS',
    help: 'The library as an OPDS catalog, for e-readers and reading apps',
    fields: [
      { key: 'OPDS_ENABLED', label: 'Enable OPDS' },
      { key: 'OPDS_AUTHENTICATION', label: 'Requires a login', showIf: (v) => !!v.OPDS_ENABLED },
      { key: 'OPDS_USERNAME', label: 'Username', showIf: (v) => !!v.OPDS_ENABLED && !!v.OPDS_AUTHENTICATION },
      {
        key: 'OPDS_PASSWORD',
        label: 'Password',
        input: 'password',
        showIf: (v) => !!v.OPDS_ENABLED && !!v.OPDS_AUTHENTICATION,
      },
      { key: 'OPDS_METAINFO', label: 'Include book details', showIf: (v) => !!v.OPDS_ENABLED, advanced: true },
      { key: 'OPDS_PAGE', label: 'Page size', showIf: (v) => !!v.OPDS_ENABLED, advanced: true },
    ],
  },
];

function General() {
  return <SettingsSection title="General" groups={GROUPS} />;
}

export default General;
