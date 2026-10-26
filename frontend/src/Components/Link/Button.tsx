import classNames from 'classnames';
import { LoaderCircle } from 'lucide-react';
import Icon from 'Components/Icon';
import Link, { LinkProps } from './Link';
import styles from './Button.module.css';

export type ButtonKind = 'default' | 'primary' | 'success' | 'warning' | 'danger';

interface ButtonProps extends LinkProps {
  kind?: ButtonKind;
  isSpinning?: boolean;
}

// Sonarr's Button and SpinnerButton in one
function Button({ kind = 'default', isSpinning = false, isDisabled, className, children, ...otherProps }: ButtonProps) {
  return (
    <Link
      className={classNames(styles.button, styles[kind], className, isDisabled && styles.isDisabled)}
      isDisabled={isDisabled || isSpinning}
      {...otherProps}
    >
      <span className={isSpinning ? styles.hidden : undefined}>{children}</span>
      {isSpinning ? (
        <span className={styles.spinner}>
          <Icon name={LoaderCircle} isSpinning={true} />
        </span>
      ) : null}
    </Link>
  );
}

export default Button;
