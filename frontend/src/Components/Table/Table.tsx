import classNames from 'classnames';
import React from 'react';
import styles from './Table.module.css';

export interface Column {
  name: string;
  label: string;
  className?: string;
  // a column with no label, a select box or the actions
  isVisuallyHidden?: boolean;
}

interface TableProps {
  columns: Column[];
  selectAll?: React.ReactNode;
  children: React.ReactNode;
}

export function Table({ columns, selectAll, children }: TableProps) {
  return (
    <div className={styles.tableContainer}>
      <table className={styles.table}>
        <thead>
          <tr>
            {selectAll === undefined ? null : <th className={classNames(styles.headerCell, styles.select)}>{selectAll}</th>}
            {columns.map((column) => (
              <th key={column.name} className={classNames(styles.headerCell, column.className)}>
                {column.isVisuallyHidden ? <span className={styles.visuallyHidden}>{column.label}</span> : column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
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
