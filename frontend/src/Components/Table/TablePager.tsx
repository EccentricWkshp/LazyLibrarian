// Sonarr's TablePager: first, previous, page x of y, next, last, and how many records
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight } from 'lucide-react';
import IconButton from 'Components/Link/IconButton';
import styles from './Table.module.css';

interface TablePagerProps {
  page: number;
  totalPages: number;
  totalRecords: number;
  isFetching?: boolean;
  onPageSelect: (page: number) => void;
}

function TablePager({ page, totalPages, totalRecords, onPageSelect }: TablePagerProps) {
  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <div className={styles.pager}>
      <div className={styles.pagerControls}>
        <IconButton name={ChevronFirst} aria-label="First page" isDisabled={isFirst} onPress={() => onPageSelect(1)} />
        <IconButton
          name={ChevronLeft}
          aria-label="Previous page"
          isDisabled={isFirst}
          onPress={() => onPageSelect(page - 1)}
        />
        <span className={styles.pageNumber}>
          {totalPages ? page : 0} / {totalPages}
        </span>
        <IconButton
          name={ChevronRight}
          aria-label="Next page"
          isDisabled={isLast}
          onPress={() => onPageSelect(page + 1)}
        />
        <IconButton
          name={ChevronLast}
          aria-label="Last page"
          isDisabled={isLast}
          onPress={() => onPageSelect(totalPages)}
        />
      </div>
      <div className={styles.recordsInfo}>Total records: {totalRecords}</div>
    </div>
  );
}

export default TablePager;
