import { LogOut, Menu, Settings } from 'lucide-react';
import { toggleIsSidebarVisible } from 'App/appStore';
import IconButton from 'Components/Link/IconButton';
import Link from 'Components/Link/Link';
import { urlBase } from 'Utilities/api';
import styles from './PageHeader.module.css';

function PageHeader() {
  return (
    <div className={styles.header}>
      <div className={styles.logoContainer}>
        <Link className={styles.logoLink} to="/home" aria-label="Home">
          <img className={styles.logo} src={`${urlBase()}/images/ll64.png`} alt="" />
          <span className={styles.brandName}>LazyLibrarian</span>
        </Link>
      </div>

      <div className={styles.sidebarToggleContainer}>
        <IconButton
          className={styles.headerButton}
          name={Menu}
          size={20}
          aria-label="Menu"
          onPress={toggleIsSidebarVisible}
        />
      </div>

      <div className={styles.right}>
        <IconButton className={styles.headerButton} name={Settings} size={18} to="/config" title="Settings" />
        <IconButton className={styles.headerButton} name={LogOut} size={18} to="/logout" title="Log out" />
      </div>
    </div>
  );
}

export default PageHeader;
