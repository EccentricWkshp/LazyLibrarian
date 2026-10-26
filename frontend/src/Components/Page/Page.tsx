import React from 'react';
import PageHeader from './Header/PageHeader';
import PageSidebar from './Sidebar/PageSidebar';
import styles from './Page.module.css';

interface PageProps {
  children: React.ReactNode;
}

// Sonarr's page: the header across the top, the sidebar down the left and the page beside it
function Page({ children }: PageProps) {
  return (
    <div className={styles.page}>
      <PageHeader />
      <div className={styles.main}>
        <PageSidebar />
        {children}
      </div>
    </div>
  );
}

export default Page;
