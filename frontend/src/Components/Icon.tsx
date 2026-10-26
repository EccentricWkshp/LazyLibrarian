import classNames from 'classnames';
import { LoaderCircle, LucideIcon } from 'lucide-react';
import styles from './Icon.module.css';

export type IconKind = 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'purple' | 'disabled';

interface IconProps {
  name: LucideIcon;
  kind?: IconKind;
  size?: number;
  isSpinning?: boolean;
  className?: string;
  title?: string;
}

function Icon({ name: Name, kind = 'default', size = 16, isSpinning = false, className, title }: IconProps) {
  const Shown = isSpinning ? LoaderCircle : Name;

  return (
    <span className={classNames(styles.icon, styles[kind], className)} title={title}>
      <Shown size={size} strokeWidth={2} className={isSpinning ? styles.spinning : undefined} aria-hidden={true} />
    </span>
  );
}

export default Icon;
