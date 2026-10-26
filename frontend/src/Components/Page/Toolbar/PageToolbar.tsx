import classNames from 'classnames';
import { LucideIcon } from 'lucide-react';
import React from 'react';
import Icon from 'Components/Icon';
import Link, { LinkProps } from 'Components/Link/Link';
import styles from './PageToolbar.module.css';

export function PageToolbar({ children }: { children: React.ReactNode }) {
  return <div className={styles.toolbar}>{children}</div>;
}

export function PageToolbarSection({
  alignContent = 'left',
  children,
}: {
  alignContent?: 'left' | 'right';
  children: React.ReactNode;
}) {
  return <div className={classNames(styles.section, styles[alignContent])}>{children}</div>;
}

export function PageToolbarSeparator() {
  return <div className={styles.separator} />;
}

interface PageToolbarButtonProps extends LinkProps {
  label: string;
  iconName: LucideIcon;
  isSpinning?: boolean;
}

export function PageToolbarButton({ label, iconName, isSpinning, isDisabled, ...otherProps }: PageToolbarButtonProps) {
  return (
    <Link
      className={classNames(styles.toolbarButton, isDisabled && styles.isDisabled)}
      isDisabled={isDisabled || isSpinning}
      title={label}
      {...otherProps}
    >
      <Icon name={iconName} isSpinning={isSpinning} size={16} />
      <span className={styles.label}>{label}</span>
    </Link>
  );
}
