/**
 * DataTable — generic sortable, paginated data table.
 *
 * Mobile-first: table scrolls horizontally on small screens.
 * Columns can be marked hideOnMobile to reduce clutter on xs/sm.
 * Pagination controls stack on mobile.
 */

import React, { useMemo, useState } from 'react';
import { Spinner } from './Spinner';

export interface Column<T> {
  key: string;
  header: string;
  /** Width hint (CSS value, e.g. "120px") */
  width?: string;
  align?: 'left' | 'center' | 'right';
  render?: (row: T) => React.ReactNode;
  sortKey?: keyof T;
  sortable?: boolean;
  /** Hide this column on screens narrower than sm (640px) */
  hideOnMobile?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  pageSize?: number;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  className?: string;
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
  className = '',
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

  // Visible page numbers (max 5 on mobile, 7 on desktop)
  const visiblePages = useMemo(() => {
    const maxPages = 7;
    if (totalPages <= maxPages) return Array.from({ length: totalPages }, (_, i) => i);
    const start = Math.max(0, Math.min(page - 3, totalPages - maxPages));
    return Array.from({ length: maxPages }, (_, i) => start + i);
  }, [totalPages, page]);

  return (
    <div className={`flex flex-col gap-0 ${className}`} style={style}>
      {/* Scrollable table wrapper */}
      <div className="overflow-x-auto rounded-lg border border-terminal-border" style={{ WebkitOverflowScrolling: 'touch' } as React.CSSProperties}>
        <table className="w-full border-collapse text-sm" style={{ minWidth: '100%', tableLayout: 'auto' }}>
          <thead>
            <tr>
              {columns.map((col) => {
                const isSorted = sortCol === col.key;
                const canSort  = col.sortable || !!col.sortKey;
                return (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col)}
                    className={`bg-terminal-raised border-b border-terminal-border text-slate-500 text-2xs font-semibold uppercase tracking-wider px-3 sm:px-4 py-2.5 sticky top-0 whitespace-nowrap select-none ${
                      canSort ? 'cursor-pointer hover:text-slate-300' : ''
                    } ${col.hideOnMobile ? 'hidden sm:table-cell' : ''}`}
                    style={{ textAlign: col.align ?? 'left', width: col.width }}
                  >
                    {col.header}
                    {canSort && (
                      <span className={`ml-1 ${isSorted ? 'opacity-100' : 'opacity-30'}`}>
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
                    <td
                      key={col.key}
                      className={`px-3 sm:px-4 py-2.5 ${col.hideOnMobile ? 'hidden sm:table-cell' : ''}`}
                    >
                      <div className="h-3.5 rounded bg-terminal-raised animate-pulse w-4/5" />
                    </td>
                  ))}
                </tr>
              ))
            ) : pageData.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-8 text-center text-slate-500 text-sm"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              pageData.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={() => onRowClick?.(row)}
                  className={`border-b border-terminal-border/60 transition-colors ${
                    onRowClick ? 'cursor-pointer hover:bg-terminal-raised/50' : ''
                  }`}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`text-slate-200 px-3 sm:px-4 py-2.5 align-middle whitespace-nowrap ${
                        col.hideOnMobile ? 'hidden sm:table-cell' : ''
                      }`}
                      style={{ textAlign: col.align ?? 'left' }}
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
        <div className="flex items-center justify-between gap-2 border-t border-terminal-border px-3 py-2 flex-wrap">
          <span className="text-slate-500 text-xs tabular-nums">
            {page * pageSize + 1}–{Math.min((page + 1) * pageSize, sorted.length)} of {sorted.length}
          </span>
          <div className="flex gap-1 flex-wrap">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="min-w-[28px] h-7 px-1.5 bg-transparent border border-terminal-border rounded text-slate-400 text-xs cursor-pointer disabled:opacity-40 hover:border-slate-500 transition-colors"
            >
              ‹
            </button>
            {visiblePages.map((pg) => (
              <button
                key={pg}
                onClick={() => setPage(pg)}
                className={`min-w-[28px] h-7 px-1.5 border rounded text-xs cursor-pointer transition-colors ${
                  pg === page
                    ? 'bg-blue-600 border-blue-600 text-white'
                    : 'bg-transparent border-terminal-border text-slate-400 hover:border-slate-500'
                }`}
              >
                {pg + 1}
              </button>
            ))}
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="min-w-[28px] h-7 px-1.5 bg-transparent border border-terminal-border rounded text-slate-400 text-xs cursor-pointer disabled:opacity-40 hover:border-slate-500 transition-colors"
            >
              ›
            </button>
          </div>
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-2">
          <Spinner size="sm" />
        </div>
      )}
    </div>
  );
}
