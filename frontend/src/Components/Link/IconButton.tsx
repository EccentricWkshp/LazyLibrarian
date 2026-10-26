import classNames from 'classnames';
import { LucideIcon } from 'lucide-react';
import Icon, { IconKind } from 'Components/Icon';
import Link, { LinkProps } from './Link';
import styles from './IconButton.module.css';

interface IconButtonProps extends LinkProps {
  name: LucideIcon;
  kind?: IconKind;
  size?: number;
  isSpinning?: boolean;
  iconClassName?: string;
}

function IconButton({
  name,
  kind,
  size = 16,
  isSpinning,
  isDisabled,
  className,
  iconClassName,
  ...otherProps
}: IconButtonProps) {
  return (
    <Link
      className={classNames(styles.button, className, isDisabled && styles.isDisabled)}
      isDisabled={isDisabled || isSpinning}
      {...otherProps}
    >
      <Icon className={iconClassName} name={name} kind={kind} size={size} isSpinning={isSpinning} />
    </Link>
  );
}

export default IconButton;
