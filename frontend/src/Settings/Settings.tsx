// Sonarr's Settings page: each section of the settings, with what's in it
import Link from 'Components/Link/Link';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import styles from './Settings.module.css';

export const SECTIONS = [
  {
    title: 'Media Management',
    to: '/settings/mediamanagement',
    summary: 'Library folders, naming, importing, the statuses new books get, and how often tasks run',
  },
  { title: 'Profiles', to: '/settings/profiles', summary: 'The formats wanted for each library, best first' },
  {
    title: 'Indexers',
    to: '/settings/indexers',
    summary: 'Usenet and torrent indexers, wishlists, IRC and direct download sites',
  },
  {
    title: 'Download Clients',
    to: '/settings/downloadclients',
    summary: 'The download clients, finished and failed downloads, and remote path mappings',
  },
  { title: 'Connect', to: '/settings/connect', summary: 'Webhooks, Apprise, email and the other notifications' },
  {
    title: 'Metadata',
    to: '/settings/metadata',
    summary: 'Where books are looked up, reading list sync, the books added, genres and opf files',
  },
  { title: 'Filters', to: '/settings/filters', summary: 'Words and sizes search results are turned down for' },
  { title: 'Languages', to: '/settings/languages', summary: 'The preferred languages, month names and name rules' },
  { title: 'Tools', to: '/settings/tools', summary: 'ffmpeg, ebook-convert, Calibre and conversions' },
  {
    title: 'General',
    to: '/settings/general',
    summary: 'Host, security, the API, proxy, logging, updates, backups, RSS and OPDS',
  },
  { title: 'UI', to: '/settings/ui', summary: 'The libraries shown, lists, dates and the language' },
];

function Settings() {
  return (
    <PageContent title="Settings">
      <PageContentBody>
        {SECTIONS.map((section) => (
          <div key={section.to} className={styles.section}>
            <Link className={styles.link} to={section.to}>
              {section.title}
            </Link>
            <div className={styles.summary}>{section.summary}</div>
          </div>
        ))}
        <div className={styles.section}>
          <Link className={styles.link} to="/config">
            All Settings
          </Link>
          <div className={styles.summary}>The old settings page, with every setting on one page</div>
        </div>
      </PageContentBody>
    </PageContent>
  );
}

export default Settings;
