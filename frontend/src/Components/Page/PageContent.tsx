import React, { useEffect } from 'react';
import ErrorBoundary from 'Components/ErrorBoundary';
import styles from './PageContent.module.css';

interface PageContentProps {
  title: string;
  children: React.ReactNode;
}

function PageContent({ title, children }: PageContentProps) {
  useEffect(() => {
    document.title = `${title} - LazyLibrarian`;
  }, [title]);

  return (
    <div className={styles.content}>
      <ErrorBoundary>{children}</ErrorBoundary>
    </div>
  );
}

export default PageContent;
