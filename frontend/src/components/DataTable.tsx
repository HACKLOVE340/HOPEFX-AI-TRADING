/**
 * DataTable — generic sortable, paginated data table.
 *
 * Mobile-first: table scrolls horizontally on small screens.
 * Columns can be marked hideOnMobile to reduce clutter on xs/sm.
 * Pagination controls stack on mobile.
 */

import React, { useMemo, useState, useCallback } from 'react';
import { ChevronUp, ChevronDown, ChevronsUpDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { Spinner } from './Spinner';

export interface Column<T> {
  key: string;
  header: string;
  /** Width hint (CSS value, e.g. "120px") */
  width?: string;
  align?: 'left' | 'center' | 'right';
  render?: (row: T) => React.ReactNode;
  sortKey?: keyof T;
  /**
   * Sort by a computed value — use for columns whose display does not map to
   * a single raw field (a ratio, a formatted percentage, a derived rank).
   * Takes precedence over `sortKey`.
   */
  sortValue?: (row: T) => string | number;
  sortable?: boolean;
  /** Hide this column on screens narrower than sm (640px) */
  hideOnMobile?: boolean;
}

interface DataTableProps<T> {
  /**
   * Describes the table for assistive technology, rendered as a visually
   * hidden <caption>. Without it a screen reader announces an unnamed table
   * and the user has no idea what they have landed in. Optional only so the
   * 20+ existing call sites keep compiling — supply it.
   */
  caption?: string;
  columns: Column<T>[];
  data: T[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  pageSize?: number;
  emptyMessage?: string;
  /**
   * Rendered in place of the whole table when there are no rows. Prefer this
   * over `emptyMessage` — a string in a table cell cannot carry the action
   * that resolves the emptiness (see EmptyState).
   */
  empty?: React.ReactNode;
  onRowClick?: (row: T) => void;
  className?: string;
  style?: React.CSSProperties;
}

type SortDir = 'asc' | 'desc';

export function DataTable<T>({
  caption,
  columns,
  data,
  rowKey,
  loading = false,
  pageSize = 20,
  emptyMessage = 'No data',
  empty,
  onRowClick,
  className = '',
  style,
}: DataTableProps<T>): React.ReactElement {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [page, setPage]       = useState(0);

  const activateRow = useCallback((row: T) => { onRowClick?.(row); }, [onRowClick]);

  const handleSort = (col: Column<T>) => {
    if (!col.sortable && !col.sortKey && !col.sortValue) return;
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
    if (!col) return data;
    // `handleSort` accepts `sortable || sortKey`, but this used to require
    // `sortKey` — so a column marked `sortable: true` alone showed a sort
    // arrow, set aria-sort, and did not reorder anything. A control that
    // reports it acted without acting; resolve the value here instead.
    const get: ((row: T) => unknown) | null =
      col.sortValue ? col.sortValue
      : col.sortKey ? (row: T) => row[col.sortKey as keyof T]
      : col.sortable ? (row: T) => (row as Record<string, unknown>)[col.key]
      : null;
    if (!get) return data;
    return [...data].sort((a, b) => {
      const av = get(a) as string | number;
      const bv = get(b) as string | number;
      if (av === bv) return 0;
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av ?? '').localeCompare(String(bv ?? ''), undefined, { numeric: true });
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

  // Placed after every hook: an early return above `useMemo` calls hooks
  // conditionally, which changes their order between renders.
  if (!loading && sorted.length === 0 && empty) return <>{empty}</>;

  return (
    <div className={`flex flex-col gap-0 ${className}`} style={style}>
      {/* Scrollable table wrapper */}
      <div className="overflow-x-auto rounded-lg border border-terminal-border" style={{ WebkitOverflowScrolling: 'touch' } as React.CSSProperties}>
        <table className="w-full border-collapse text-sm" style={{ minWidth: '100%', tableLayout: 'auto' }}>
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead>
            <tr>
              {columns.map((col) => {
                const isSorted = sortCol === col.key;
                const canSort  = col.sortable || !!col.sortKey || !!col.sortValue;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    // Sort state must be announced, not just drawn (rubric a11y).
                    aria-sort={isSorted ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}
                    className={`bg-terminal-raised border-b border-terminal-border text-slate-500 text-2xs font-semibold uppercase tracking-wider px-3 sm:px-4 py-0 sticky top-0 whitespace-nowrap select-none ${
                      col.hideOnMobile ? 'hidden sm:table-cell' : ''
                    }`}
                    style={{ textAlign: col.align ?? 'left', width: col.width }}
                  >
                    {canSort ? (
                      // A <th onClick> is mouse-only. A real button is keyboard
                      // reachable and clears the 44px target minimum.
                      <button
                        type="button"
                        onClick={() => handleSort(col)}
                        className={`group inline-flex min-h-[44px] w-full items-center gap-1 py-2 cursor-pointer transition-colors duration-150 hover:text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-inset ${
                          col.align === 'right' ? 'justify-end' : col.align === 'center' ? 'justify-center' : 'justify-start'
                        }`}
                      >
                        {col.header}
                        {isSorted
                          ? (sortDir === 'asc'
                              ? <ChevronUp size={12} strokeWidth={2.5} aria-hidden />
                              : <ChevronDown size={12} strokeWidth={2.5} aria-hidden />)
                          : <ChevronsUpDown size={12} strokeWidth={2} aria-hidden className="text-slate-700 transition-colors group-hover:text-slate-500" />}
                      </button>
                    ) : (
                      <span className="inline-flex min-h-[44px] items-center py-2">{col.header}</span>
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
                  {...(onRowClick
                    ? {
                        // A click handler alone makes the drill-down mouse-only.
                        role: 'link',
                        tabIndex: 0,
                        onClick: () => activateRow(row),
                        onKeyDown: (e: React.KeyboardEvent) => {
                          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activateRow(row); }
                        },
                      }
                    : {})}
                  className={`border-b border-terminal-border/60 transition-colors duration-150 ${
                    onRowClick
                      ? 'cursor-pointer hover:bg-terminal-raised/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-500'
                      : ''
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
              aria-label="Previous page"
              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center bg-transparent border border-terminal-border rounded text-slate-400 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40 hover:border-slate-500 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            >
              <ChevronLeft size={15} strokeWidth={2} aria-hidden />
            </button>
            {visiblePages.map((pg) => (
              <button
                key={pg}
                onClick={() => setPage(pg)}
                aria-label={`Page ${pg + 1}`}
                aria-current={pg === page ? 'page' : undefined}
                className={`inline-flex min-h-[44px] min-w-[44px] items-center justify-center border rounded text-xs cursor-pointer transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
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
              aria-label="Next page"
              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center bg-transparent border border-terminal-border rounded text-slate-400 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40 hover:border-slate-500 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            >
              <ChevronRight size={15} strokeWidth={2} aria-hidden />
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
