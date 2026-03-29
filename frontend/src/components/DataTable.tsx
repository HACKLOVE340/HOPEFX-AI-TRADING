/**
 * DataTable — generic sortable, paginated data table.
 *
 * Features:
 * - Column-level sort (click header to toggle asc/desc)
 * - Client-side pagination
 * - Loading skeleton rows
 * - Empty state slot
 * - Custom cell renderers via Column.render()
 * - Sticky header
 */

import React, { useMemo, useState } from 'react';
import { Spinner } from './Spinner';

export interface Column<T> {
  key: string;
  header: string;
  /** Width hint (CSS value, e.g. "120px" or "1fr") */
  width?: string;
  /** Align cell content */
  align?: 'left' | 'center' | 'right';
  /** Custom renderer — receives the row object */
  render?: (row: T) => React.ReactNode;
  /** Field path for default sort (dot-notation not supported — use render for complex fields) */
  sortKey?: keyof T;
  sortable?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  pageSize?: number;
  emptyMessage?: string;
  /** Called when a row is clicked */
  onRowClick?: (row: T) => void;
  style?: React.CSSProperties;
}

type SortDir = 'asc' | 'desc';

export function DataTable<T>({
  columns,
  data,
  rowKey,
  loading = false,
  pageSize = 20,
  emptyMessage = 'No data',
  onRowClick,
  style,
}: DataTableProps<T>): React.ReactElement {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [page, setPage]       = useState(0);

  const handleSort = (col: Column<T>) => {
    if (!col.sortable && !col.sortKey) return;
    const key = col.key;
    if (sortCol === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortCol(key);
      setSortDir('asc');
    }
    setPage(0);
  };

  const sorted = useMemo(() => {
    if (!sortCol) return data;
    const col = columns.find((c) => c.key === sortCol);
    if (!col?.sortKey) return data;
    const sk = col.sortKey;
    return [...data].sort((a, b) => {
      const av = a[sk];
      const bv = b[sk];
      if (av === bv) return 0;
      const cmp = av! < bv! ? -1 : 1;
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortCol, sortDir, columns]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const pageData   = sorted.slice(page * pageSize, (page + 1) * pageSize);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, ...style }}>
      <div style={s.wrapper}>
        <table style={s.table}>
          <thead>
            <tr>
              {columns.map((col) => {
                const isSorted = sortCol === col.key;
                const canSort  = col.sortable || !!col.sortKey;
                return (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col)}
                    style={{
                      ...s.th,
                      width: col.width,
                      textAlign: col.align ?? 'left',
                      cursor: canSort ? 'pointer' : 'default',
                      userSelect: 'none',
                    }}
                  >
                    {col.header}
                    {canSort && (
                      <span style={{ marginLeft: 4, opacity: isSorted ? 1 : 0.3 }}>
                        {isSorted ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: Math.min(pageSize, 5) }).map((_, i) => (
                <tr key={i}>
                  {columns.map((col) => (
                    <td key={col.key} style={s.td}>
                      <div style={s.skeleton} />
                    </td>
                  ))}
                </tr>
              ))
            ) : pageData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} style={{ ...s.td, textAlign: 'center', padding: 32, color: '#64748b' }}>
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              pageData.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={() => onRowClick?.(row)}
                  style={{
                    ...s.tr,
                    cursor: onRowClick ? 'pointer' : 'default',
                  }}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      style={{ ...s.td, textAlign: col.align ?? 'left' }}
                    >
                      {col.render
                        ? col.render(row)
                        : String((row as Record<string, unknown>)[col.key] ?? '')}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={s.pagination}>
          <span style={{ color: '#64748b', fontSize: 12 }}>
            {page * pageSize + 1}–{Math.min((page + 1) * pageSize, sorted.length)} of {sorted.length}
          </span>
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              style={s.pageBtn}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(totalPages, 7) }).map((_, i) => {
              const pg = totalPages <= 7 ? i : Math.max(0, Math.min(page - 3, totalPages - 7)) + i;
              return (
                <button
                  key={pg}
                  onClick={() => setPage(pg)}
                  style={{
                    ...s.pageBtn,
                    background: pg === page ? '#3b82f6' : 'transparent',
                    color: pg === page ? '#fff' : '#94a3b8',
                  }}
                >
                  {pg + 1}
                </button>
              );
            })}
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              style={s.pageBtn}
            >
              ›
            </button>
          </div>
        </div>
      )}

      {loading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 8 }}>
          <Spinner size="sm" />
        </div>
      )}
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  wrapper: {
    overflowX: 'auto',
    borderRadius: 8,
    border: '1px solid var(--border, #334155)',
  },
  table: {
    borderCollapse: 'collapse',
    fontSize: 13,
    minWidth: '100%',
    tableLayout: 'auto',
  },
  th: {
    background: 'var(--surface-raised, #1e293b)',
    borderBottom: '1px solid var(--border, #334155)',
    color: 'var(--text-muted, #94a3b8)',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: 0.5,
    padding: '10px 14px',
    position: 'sticky',
    textTransform: 'uppercase',
    top: 0,
    whiteSpace: 'nowrap',
  },
  tr: {
    borderBottom: '1px solid var(--border-subtle, #1e293b)',
    transition: 'background 0.1s',
  },
  td: {
    color: 'var(--text, #f1f5f9)',
    padding: '10px 14px',
    verticalAlign: 'middle',
    whiteSpace: 'nowrap',
  },
  skeleton: {
    background: 'linear-gradient(90deg, #1e293b 25%, #334155 50%, #1e293b 75%)',
    backgroundSize: '200% 100%',
    borderRadius: 4,
    height: 14,
    width: '80%',
    animation: 'shimmer 1.5s infinite',
  },
  pagination: {
    alignItems: 'center',
    borderTop: '1px solid var(--border, #334155)',
    display: 'flex',
    gap: 8,
    justifyContent: 'space-between',
    padding: '8px 12px',
  },
  pageBtn: {
    background: 'transparent',
    border: '1px solid var(--border, #334155)',
    borderRadius: 4,
    color: '#94a3b8',
    cursor: 'pointer',
    fontSize: 12,
    minWidth: 28,
    padding: '3px 6px',
  },
};
