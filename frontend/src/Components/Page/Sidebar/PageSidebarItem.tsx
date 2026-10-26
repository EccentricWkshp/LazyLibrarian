import classNames from 'classnames';
import { LucideIcon } from 'lucide-react';
import React from 'react';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import styles from './PageSidebarItem.module.css';

interface PageSidebarItemProps {
  iconName?: LucideIcon;
  title: string;
  to: string;
  isActive?: boolean;
  isActiveParent?: boolean;
  isChildItem?: boolean;
  statusComponent?: React.ElementType;
  children?: React.ReactNode;
}

function PageSidebarItem({
  iconName,
  title,
  to,
  isActive,
  isActiveParent,
  isChildItem = false,
  statusComponent: StatusComponent,
  children,
}: PageSidebarItemProps) {
  return (
    <div className={styles.item}>
      <Link
        className={classNames(
          isChildItem ? styles.childLink : styles.link,
          isActiveParent && styles.isActiveParentLink,
          isActive && styles.isActiveLink
        )}
        to={to}
        aria-current={isActive ? 'page' : undefined}
      >
        {iconName ? (
          <span className={styles.iconContainer}>
            <Icon name={iconName} />
          </span>
        ) : null}

        {title}

        {StatusComponent ? (
          <span className={styles.status}>
            <StatusComponent />
          </span>
        ) : null}
      </Link>

      {children}
    </div>
  );
}

export default PageSidebarItem;
