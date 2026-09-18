/**
 * components/ui/MetricTile.tsx
 * Single KPI tile used in the account bar, risk dashboard, ML panel and
 * equity chart header.
 *
 * A tile may be a destination. Pass `to` and the tile becomes a link to the
 * page that explains the number — the trades behind a win rate, the equity
 * curve behind a drawdown. Without `to` it stays an inert `<div>`, so tiles
 * that genuinely lead nowhere do not become empty tab stops for keyboard
 * users. See audit F187.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { cn } from '../../lib/utils';

interface MetricTileProps {
  label:      string;
  value:      string | React.ReactNode;
  sub?:       string | React.ReactNode;
  valueColor?: string;
  icon?:      React.ReactNode;
  className?: string;
  compact?:   boolean;
  /** Route this metric drills into. Omit for a non-interactive tile. */
  to?:        string;
  /** What the destination shows, e.g. "the trades behind it". Used to build
   *  the accessible name and the hover tooltip so the link says what it does
   *  rather than just where it goes. */
  toHint?:    string;
}

export function MetricTile({
  label,
  value,
  sub,
  valueColor,
  icon,
  className,
  compact = false,
  to,
  toHint,
}: MetricTileProps) {
  const valueText =
    typeof value === 'string' || typeof value === 'number' ? String(value) : undefined;

  const body = (
    <>
      <div className="flex items-center gap-1">
        {icon && <span className="text-slate-500">{icon}</span>}
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-500 truncate">
          {label}
        </span>
        {to && (
          // Persistent-but-quiet affordance: without it there is no indication
          // the tile is interactive at all. It brightens on hover/focus rather
          // than appearing, so nothing shifts.
          <ChevronRight
            size={11}
            strokeWidth={2.5}
            aria-hidden
            className="ml-auto shrink-0 text-slate-700 transition-colors duration-150 group-hover:text-slate-300 group-focus-visible:text-slate-300"
          />
        )}
      </div>
      <span
        className={cn(
          'font-mono tabular-nums font-semibold leading-tight truncate',
          // `compact` tiles live in narrow panel grids, so the value font is
          // sized for the CELL, not the viewport — a `sm:` prefix would
          // re-inflate it on every desktop and re-clip the number.
          compact ? 'text-xs' : 'text-base',
        )}
        style={valueColor ? { color: valueColor } : undefined}
        // A monetary value that cannot fit must fail VISIBLY. `truncate` gives
        // an ellipsis ("$100,0…") instead of a mid-glyph cut, and the title
        // carries the full figure for hover and screen readers.
        title={to ? undefined : valueText}
      >
        {value}
      </span>
      {sub && (
        <span className="text-[10px] text-slate-600 font-mono tabular-nums">{sub}</span>
      )}
    </>
  );

  const shared = cn(
    'flex flex-col gap-0.5',
    // `min-w-0` lets the tile shrink inside a narrow grid/flex parent.
    // `min-w-[80px]` alone is a FLOOR: the tile refused to go below it,
    // overflowed the panel, and the panel's `overflow-hidden` cut the value
    // mid-glyph — equity rendered as "$100,000.(" on the dashboard, which
    // reads as a complete number and is not one. See audit F166.
    'min-w-0',
    compact ? 'sm:min-w-[80px]' : 'sm:min-w-[100px]',
    className,
  );

  if (!to) {
    return <div className={shared}>{body}</div>;
  }

  return (
    <Link
      to={to}
      // The name a screen reader announces has to carry the number and the
      // outcome, not just the label — "Win Rate" alone tells a non-sighted
      // user nothing about what activating this does.
      aria-label={
        `${label}${valueText ? `: ${valueText}` : ''}` +
        (toHint ? ` — open ${toHint}` : '')
      }
      title={
        `${valueText ?? label}${toHint ? ` — open ${toHint}` : ''}`
      }
      className={cn(
        shared,
        'group cursor-pointer rounded-md -mx-1.5 px-1.5 py-1',
        // 44px minimum touch target (the tile is otherwise ~34px tall).
        'min-h-[44px] justify-center',
        // Colour-only hover: a transform here would nudge every neighbouring
        // tile in the flex row on each mouse-over.
        'transition-colors duration-150 hover:bg-slate-800/60',
        // Keyboard users get the same affordance as mouse users.
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950',
      )}
    >
      {body}
    </Link>
  );
}
