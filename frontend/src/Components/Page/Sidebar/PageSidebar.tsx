import classNames from 'classnames';
import {
  Ban,
  BookOpen,
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
import Messages from './Messages/Messages';
import PageSidebarItem from './PageSidebarItem';
import styles from './PageSidebar.module.css';

interface SidebarItem {
  iconName: LucideIcon;
  title: string;
  to: string;
  isHidden?: boolean;
  statusComponent?: React.ElementType;
  children?: { title: string; to: string }[];
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
        { iconName: Users, title: 'Authors', to: '/home' },
        { iconName: BookOpen, title: 'eBooks', to: '/books', isHidden: !tabs.ebook },
        { iconName: Headphones, title: 'Audiobooks', to: '/audio', isHidden: !tabs.audio },
        { iconName: Library, title: 'Series', to: '/series', isHidden: !tabs.series },
        { iconName: Newspaper, title: 'Magazines', to: '/magazines', isHidden: !tabs.mag },
        { iconName: Layers, title: 'Comics', to: '/comics', isHidden: !tabs.comic },
        { iconName: ListChecks, title: 'Manage', to: '/manage' },
        {
          iconName: TriangleAlert,
          title: 'Wanted',
          to: '/wanted/missing',
          children: [{ title: 'Missing', to: '/wanted/missing' }],
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
        { iconName: Settings, title: 'Settings', to: '/config' },
        { iconName: Monitor, title: 'System', to: '/logs', children: [{ title: 'Logs', to: '/logs' }] },
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
                const isActiveParent = !!item.children?.some((child) => child.to === pathname);
                // like Sonarr, a section's pages show while you're in it

                return (
                  <PageSidebarItem
                    key={item.to}
                    iconName={item.iconName}
                    title={item.title}
                    to={item.to}
                    isActive={pathname === item.to && !item.children}
                    isActiveParent={isActiveParent}
                    statusComponent={item.statusComponent}
                  >
                    {(isActiveParent ? item.children : [])?.map((child) => (
                      <PageSidebarItem
                        key={child.to}
                        title={child.title}
                        to={child.to}
                        isActive={pathname === child.to}
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
