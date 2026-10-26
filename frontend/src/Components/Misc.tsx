// The small pieces: progress bar, label, alert, loading indicator and popover
import { autoUpdate, flip, offset, shift, useFloating, useHover, useInteractions } from '@floating-ui/react';
import classNames from 'classnames';
import { LoaderCircle } from 'lucide-react';
import React, { useState } from 'react';
import Icon from './Icon';
import styles from './Misc.module.css';

type Kind = 'default' | 'primary' | 'info' | 'success' | 'warning' | 'danger' | 'purple';

export function ProgressBar({ progress, kind = 'primary', title }: { progress: number; kind?: Kind; title?: string }) {
  return (
    <div className={styles.progressBar} title={title} role="progressbar" aria-valuenow={progress}>
      <div className={classNames(styles.progress, styles[`progress-${kind}`])} style={{ width: `${progress}%` }} />
    </div>
  );
}

export function Label({ kind = 'default', title, children }: { kind?: Kind; title?: string; children: React.ReactNode }) {
  return (
    <span className={classNames(styles.label, styles[`label-${kind}`])} title={title}>
      {children}
    </span>
  );
}

export function Alert({ kind = 'info', children }: { kind?: Kind; children: React.ReactNode }) {
  return <div className={classNames(styles.alert, styles[`alert-${kind}`])}>{children}</div>;
}

export function LoadingIndicator() {
  return (
    <div className={styles.loading}>
      <Icon name={LoaderCircle} isSpinning={true} size={28} />
    </div>
  );
}

// Sonarr's Popover: a title and body shown while the anchor is hovered or focused
export function Popover({ anchor, title, body }: { anchor: React.ReactNode; title: string; body: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: setIsOpen,
    placement: 'right',
    middleware: [offset(8), flip(), shift({ padding: 8 })],
    whileElementsMounted: autoUpdate,
  });
  const hover = useHover(context, { delay: { open: 100, close: 100 } });
  const { getReferenceProps, getFloatingProps } = useInteractions([hover]);

  return (
    <>
      <span
        ref={refs.setReference}
        className={styles.anchor}
        tabIndex={0}
        aria-label={title}
        onFocus={() => setIsOpen(true)}
        onBlur={() => setIsOpen(false)}
        {...getReferenceProps()}
      >
        {anchor}
      </span>
      {isOpen ? (
        <div ref={refs.setFloating} className={styles.popover} style={floatingStyles} {...getFloatingProps()}>
          <div className={styles.popoverTitle}>{title}</div>
          <div className={styles.popoverBody}>{body}</div>
        </div>
      ) : null}
    </>
  );
}
