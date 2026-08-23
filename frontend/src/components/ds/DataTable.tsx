/**
 * ds/DataTable.tsx — the semantic, sortable data table.
 *
 * Why this exists: measured across all 82 routes, only 7 render a <table>
 * (audit F174/F190/F193). Trade history, allocations and backtest results were
 * div grids — so there is nothing to sort, nothing to read as a table in a
 * screen reader, and no structure to export. The ui-ux-pro-max rubric lists
 * `data-table` ("provide table alternative for accessibility") and puts
 * category comparisons at interactivity level "Hover + Sort".
 *
 * Contract:
 *   - real <table>/<thead>/<tbody>, with <caption> for assistive tech
 *   - click a header to sort; aria-sort announced; keyboard operable
 *   - a row may drill down (onRowClick / rowHref) — the whole row, not a
 *     10px chevron, so the target clears 44px
 *   - overflow-x lives on the wrapper, so a wide table scrolls inside its own
 *     box and never makes the page scroll sideways
 */

import React, { useMemo, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';

export interface Column<T> {
  key: string;
  header: string;
  /** Cell renderer. Return a string/number for the default right-aligned mono cell. */
  render: (row: T) => React.ReactNode;
  /** Value used for sorting. Omit to make the column unsortable. */
  sortValue?: (row: T) => string | number;
  align?: 'left' | 'right';
  /** Hide below this breakpoint so narrow viewports stay readable. */
  hideBelow?: 'sm' | 'md' | 'lg';
  width?: string;
}

export interface DataTableProps<T> {
  /** Describes the table for screen readers. Required — it is the caption. */
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Route to open when a row is activated. Makes rows keyboard-operable links. */
  rowHref?: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Shown in place of the body when there are no rows. Use ds/EmptyState. */
  empty?: React.ReactNode;
  initialSort?: { key: string; dir: 'asc' | 'desc' };
  /** Cap the body height and scroll inside it. */
  maxHeight?: number;
}

const HIDE: Record<string, string> = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
};

export function DataTable<T>({
  caption, columns, rows, rowKey, rowHref, onRowClick, empty,
  initialSort, maxHeight,
}: DataTableProps<T>) {
  const navigate = useNavigate();
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(
    initialSort ?? null,
  );

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const get = col.sortValue;
    // Copy first — sorting the prop array in place mutates caller state.
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      const cmp = typeof va === 'number' && typeof vb === 'number'
        ? va - vb
        : String(va).localeCompare(String(vb), undefined, { numeric: true });
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }, [rows, sort, columns]);

  const toggle = useCallback((key: string) => {
    setSort((s) =>
      s?.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'desc' },
    );
  }, []);

  const activate = useCallback((row: T) => {
    if (onRowClick) return onRowClick(row);
    if (rowHref) navigate(rowHref(row));
  }, [onRowClick, rowHref, navigate]);

  const interactive = Boolean(onRowClick || rowHref);

  if (rows.length === 0 && empty) return <>{empty}</>;

  return (
    // The wrapper owns the horizontal scroll: a wide table must never push the
    // page itself sideways (rubric: horizontal-scroll, HIGH).
    <div
      className="overflow-x-auto overscroll-x-contain rounded-lg border border-[#1e2d3d]"
      style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}
    >
      <table className="w-full border-collapse text-[12.5px]">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-10 bg-[#111827]">
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const sortable = Boolean(c.sortValue);
              return (
                <th
                  key={c.key}
                  scope="col"
                  style={c.width ? { width: c.width } : undefined}
                  aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={`${c.hideBelow ? HIDE[c.hideBelow] : ''} border-b border-[#1e2d3d]
                    px-3 py-0 text-[10px] font-semibold uppercase tracking-wider text-slate-500
                    ${c.align === 'right' ? 'text-right' : 'text-left'}`}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => toggle(c.key)}
                      className={`group inline-flex min-h-[44px] w-full items-center gap-1 py-2
                        ${c.align === 'right' ? 'justify-end' : 'justify-start'}
                        cursor-pointer transition-colors duration-150 hover:text-slate-200
                        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500
                        focus-visible:ring-inset`}
                    >
                      {c.header}
                      {active
                        ? (sort!.dir === 'asc'
                            ? <ChevronUp size={12} strokeWidth={2.5} aria-hidden />
                            : <ChevronDown size={12} strokeWidth={2.5} aria-hidden />)
                        : <ChevronsUpDown size={12} strokeWidth={2}
                            className="text-slate-700 transition-colors group-hover:text-slate-500" aria-hidden />}
                    </button>
                  ) : (
                    <span className="inline-flex min-h-[44px] items-center py-2">{c.header}</span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={rowKey(row)}
              {...(interactive
                ? {
                    tabIndex: 0,
                    role: 'link',
                    onClick: () => activate(row),
                    onKeyDown: (e: React.KeyboardEvent) => {
                      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(row); }
                    },
                  }
                : {})}
              className={`border-b border-[#141d2b] last:border-0
                ${interactive
                  ? `cursor-pointer transition-colors duration-150 hover:bg-[#141c2b]
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset
                     focus-visible:ring-sky-500`
                  : ''}`}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`${c.hideBelow ? HIDE[c.hideBelow] : ''} px-3 py-2.5 align-middle
                    ${c.align === 'right'
                      ? 'text-right font-mono tabular-nums text-slate-200'
                      : 'text-left text-slate-300'}`}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
