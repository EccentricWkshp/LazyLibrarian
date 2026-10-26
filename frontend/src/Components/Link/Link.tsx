import classNames from 'classnames';
import React from 'react';
import { Link as RouterLink } from 'react-router';
import { urlBase } from 'Utilities/api';
import styles from './Link.module.css';

// the paths the front end has, anything else is one of the old pages
const UI_PATHS = ['/activity'];

export function isUiPath(to: string) {
  return UI_PATHS.some((path) => to === path || to.startsWith(`${path}/`));
}

export interface LinkProps extends Omit<React.HTMLAttributes<HTMLElement>, 'onClick'> {
  to?: string;
  isDisabled?: boolean;
  noRouter?: boolean;
  onPress?: (event: React.MouseEvent<HTMLElement>) => void;
}

// A link to a front end page, an old page, another site, or a button when there's onPress
function Link({ to, isDisabled, noRouter, onPress, className, children, ...otherProps }: LinkProps) {
  const linkClassName = classNames(styles.link, className, isDisabled && styles.isDisabled);

  if (to && !onPress) {
    if (/^https?:\/\//.test(to)) {
      return (
        <a className={linkClassName} href={to} target="_blank" rel="noreferrer" {...otherProps}>
          {children}
        </a>
      );
    }

    if (isUiPath(to) && !noRouter) {
      return (
        <RouterLink className={linkClassName} to={to} {...otherProps}>
          {children}
        </RouterLink>
      );
    }

    return (
      <a className={linkClassName} href={`${urlBase()}${to}`} {...otherProps}>
        {children}
      </a>
    );
  }

  return (
    <button
      type="button"
      className={classNames(linkClassName, styles.button)}
      disabled={isDisabled}
      onClick={onPress}
      {...otherProps}
    >
      {children}
    </button>
  );
}

export default Link;
