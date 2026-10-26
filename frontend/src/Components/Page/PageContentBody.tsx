import React from 'react';
import styles from './PageContent.module.css';

function PageContentBody({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.body}>
      <div className={styles.innerBody}>{children}</div>
    </div>
  );
}

export default PageContentBody;
