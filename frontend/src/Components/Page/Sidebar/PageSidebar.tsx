import classNames from 'classnames';
import {
  Ban,
  BookOpen,
  CalendarDays,
  Download,
  Headphones,
  History,
  Layers,
  Library,
  ListChecks,
  LucideIcon,
  Monitor,
  Newspaper,
  Settings,
  TriangleAlert,
  Users,
} from 'lucide-react';
import React, { useEffect } from 'react';
import { useLocation } from 'react-router';
import QueueStatus from 'Activity/Queue/Status/QueueStatus';
import { setIsSidebarVisible, useAppValue } from 'App/appStore';
import { SECTIONS } from 'Settings/Settings';
import HealthStatus from 'System/Status/HealthStatus';
import Messages from './Messages/Messages';
import PageSidebarItem from './PageSidebarItem';
import styles from './PageSidebar.module.css';

interface SidebarItem {
  iconName: LucideIcon;
  title: string;
  to: string;
  isHidden?: boolean;
  statusComponent?: React.ElementType;
  // other pages it's the one for, by how their path starts
  under?: string;
  children?: SidebarChild[];
}

interface SidebarChild {
  title: string;
  to: string;
  // other pages it's the one for, by how their path starts, like an author's for Authors
  under?: string;
}

// under is a page, or the pages below a path that ends in /
function isChildActive(child: SidebarChild, pathname: string) {
  const under = child.under ?? '';
  return (
    pathname === child.to ||
    (!!under && (pathname === under || pathname.startsWith(under.endsWith('/') ? under : `${under}/`)))
  );
}

interface SidebarGroup {
  label?: string;
  items: SidebarItem[];
}

function groups(): SidebarGroup[] {
  const tabs = window.LazyLibrarian?.tabs ?? { ebook: true, audio: true, series: true, mag: true, comic: false };

  return [
    {
      label: 'Library',
      items: [
        {
          iconName: Users,
          title: 'Authors',
          to: '/authors',
          children: [
            { title: 'Authors', to: '/authors', under: '/author/' },
            { title: 'Add New', to: '/add/new' },
          ],
        },
        { iconName: BookOpen, title: 'eBooks', to: '/books', isHidden: !tabs.ebook },
        { iconName: Headphones, title: 'Audiobooks', to: '/audio', isHidden: !tabs.audio },
        { iconName: Library, title: 'Series', to: '/series', under: '/series/', isHidden: !tabs.series },
        {
          iconName: Newspaper,
          title: 'Magazines',
          to: '/magazines',
          isHidden: !tabs.mag,
          children: [
            { title: 'Magazines', to: '/magazines', under: '/magazine' },
            { title: 'Add New', to: '/magazines/add' },
            { title: 'Recent Issues', to: '/magazines/recent' },
            { title: 'Past Issues', to: '/magazines/pastissues' },
            { title: 'Search Issues', to: '/magazines/search' },
          ],
        },
        {
          iconName: Layers,
          title: 'Comics',
          to: '/comics',
          isHidden: !tabs.comic,
          children: [
            { title: 'Comics', to: '/comics', under: '/comic/' },
            { title: 'Add New', to: '/comics/add' },
            { title: 'Recent Issues', to: '/comics/recent' },
          ],
        },
        { iconName: ListChecks, title: 'Manage', to: '/manage' },
        { iconName: CalendarDays, title: 'Calendar', to: '/calendar' },
        {
          iconName: TriangleAlert,
          title: 'Wanted',
          to: '/wanted/missing',
          children: [
            { title: 'Missing', to: '/wanted/missing' },
            { title: 'Cutoff Unmet', to: '/wanted/cutoffunmet' },
          ],
        },
      ],
    },
    {
      label: 'Activity',
      items: [
        { iconName: Download, title: 'Queue', to: '/activity/queue', statusComponent: QueueStatus },
        { iconName: History, title: 'History', to: '/activity/history' },
        { iconName: Ban, title: 'Blocklist', to: '/activity/blocklist' },
      ],
    },
    {
      items: [
        {
          iconName: Settings,
          title: 'Settings',
          to: '/settings',
          children: [
            ...SECTIONS.map((section) => ({ title: section.title, to: section.to })),
            // the old page, with every setting on one page
            { title: 'All Settings', to: '/config' },
          ],
        },
        {
          iconName: Monitor,
          title: 'System',
          to: '/system/status',
          statusComponent: HealthStatus,
          children: [
            { title: 'Status', to: '/system/status' },
            { title: 'Tasks', to: '/system/tasks' },
            { title: 'Backup', to: '/system/backup' },
            { title: 'Updates', to: '/system/updates' },
            { title: 'Events', to: '/system/events' },
            { title: 'Log Files', to: '/system/logs/files' },
          ],
        },
      ],
    },
  ];
}

function PageSidebar() {
  const { pathname } = useLocation();
  const isSidebarVisible = useAppValue('isSidebarVisible');

  // a page chosen on a small screen closes the sidebar over it
  useEffect(() => {
    setIsSidebarVisible(false);
  }, [pathname]);

  return (
    <div className={classNames(styles.sidebarContainer, !isSidebarVisible && styles.isHiddenOnSmallScreens)}>
      <nav className={styles.sidebar} aria-label="Main">
        {groups().map((group, index) => (
          <React.Fragment key={group.label ?? index}>
            {index > 0 && !group.label ? <div className={styles.divider} /> : null}
            {group.label ? <span className={styles.groupLabel}>{group.label}</span> : null}

            {group.items
              .filter((item) => !item.isHidden)
              .map((item) => {
                const isActiveParent =
                  !!item.children &&
                  (pathname === item.to || item.children.some((child) => isChildActive(child, pathname)));
                // like Sonarr, a section's pages show while you're in it

                return (
                  <PageSidebarItem
                    key={item.to}
                    iconName={item.iconName}
                    title={item.title}
                    to={item.to}
                    isActive={!item.children && isChildActive(item, pathname)}
                    isActiveParent={isActiveParent}
                    statusComponent={item.statusComponent}
                  >
                    {(isActiveParent ? item.children : [])?.map((child) => (
                      <PageSidebarItem
                        key={child.to}
                        title={child.title}
                        to={child.to}
                        isActive={isChildActive(child, pathname)}
                        isChildItem={true}
                      />
                    ))}
                  </PageSidebarItem>
                );
              })}
          </React.Fragment>
        ))}
      </nav>

      <Messages />
    </div>
  );
}

export default PageSidebar;
