import classNames from 'classnames';
import { ChevronDown, ChevronUp } from 'lucide-react';
import React from 'react';
import Icon from 'Components/Icon';
import styles from './Table.module.css';

export type SortDirection = 'ascending' | 'descending';

export interface Column {
  name: string;
  label: string;
  className?: string;
  // a column with no label, a select box or the actions
  isVisuallyHidden?: boolean;
  // its header sorts the rows by it, as Sonarr's tables do
  isSortable?: boolean;
}

interface TableProps {
  columns: Column[];
  selectAll?: React.ReactNode;
  // the column the rows are sorted by, and which way
  sortKey?: string;
  sortDirection?: SortDirection;
  onSortPress?: (name: string) => void;
  children: React.ReactNode;
}

function HeaderLabel({
  column,
  sortKey,
  sortDirection,
  onSortPress,
}: {
  column: Column;
  sortKey?: string;
  sortDirection?: SortDirection;
  onSortPress?: (name: string) => void;
}) {
  if (column.isVisuallyHidden) {
    return <span className={styles.visuallyHidden}>{column.label}</span>;
  }
  if (!column.isSortable || !onSortPress) {
    return <>{column.label}</>;
  }
  const isSorted = sortKey === column.name;
  return (
    <button
      type="button"
      className={classNames(styles.sortButton, isSorted && styles.sorted)}
      aria-sort={isSorted ? sortDirection : undefined}
      onClick={() => onSortPress(column.name)}
    >
      {column.label}
      {isSorted ? <Icon name={sortDirection === 'descending' ? ChevronDown : ChevronUp} size={12} /> : null}
    </button>
  );
}

export function Table({ columns, selectAll, sortKey, sortDirection, onSortPress, children }: TableProps) {
  return (
    <div className={styles.tableContainer}>
      <table className={styles.table}>
        <thead>
          <tr>
            {selectAll === undefined ? null : <th className={classNames(styles.headerCell, styles.select)}>{selectAll}</th>}
            {columns.map((column) => (
              <th key={column.name} className={classNames(styles.headerCell, column.className)}>
                <HeaderLabel column={column} sortKey={sortKey} sortDirection={sortDirection} onSortPress={onSortPress} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

// a sort's next state when a header is pressed: the same column the other way, another ascending
export function nextSort(current: { key: string; direction: SortDirection }, name: string) {
  return current.key === name
    ? { key: name, direction: current.direction === 'ascending' ? ('descending' as const) : ('ascending' as const) }
    : { key: name, direction: 'ascending' as const };
}

export function TableRow({ className, children }: { className?: string; children: React.ReactNode }) {
  return <tr className={classNames(styles.row, className)}>{children}</tr>;
}

export function TableRowCell({
  className,
  children,
  colSpan,
  title,
}: {
  className?: string;
  children?: React.ReactNode;
  colSpan?: number;
  title?: string;
}) {
  return (
    <td className={classNames(styles.cell, className)} colSpan={colSpan} title={title}>
      {children}
    </td>
  );
}
