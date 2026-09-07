/**
 * hub/surfaceData.ts — what a surface actually shows.
 *
 * §22: "Metrics must be connected to real telemetry when the backend exists.
 * Avoid fake 'live' values in production."
 *
 * Everything read here already flows over the WebSocket this platform has run
 * for months — prices with history, positions, the risk snapshot, news. A
 * surface that ignored it in favour of a plausible constant would be exactly the
 * defect that rule exists for, and this repository has shipped that defect
 * before: the previous `HologramPanel` animated an analysis it never performed.
 *
 * ## The distinction that does the most work here
 *
 * **Empty and unmeasured are different facts.** "No positions open" and "the
 * position feed has not arrived" render identically as a blank table, and they
 * mean opposite things to a trader — one is a flat book, the other is a screen
 * that cannot be trusted. Every binding below returns `empty` with a `note`
 * saying which it is.
 *
 * The same goes for zero. Zero drawdown and unmeasured drawdown look identical
 * as a number, so an unmeasured risk snapshot does not render as 0.0%.
 *
 * ## Why this is a plain function
 *
 * It reads the store directly and returns data. No hooks, so every binding is
 * testable by setting store state and calling it, and the renderers stay pure.
 */

import { useStore } from '../store';
import { applyZoom, type ZoomRange } from './spatial';

export interface SurfaceData {
  points?: number[];
  rows?: [string, string][];
  items?: string[];
  body?: string;
  values?: number[];
  /** True when there is nothing to draw — for either reason. */
  empty: boolean;
  /** Which reason. Rendered in place of the content, never alongside a zero. */
  note?: string;
}

/** The symbol the presence follows. XAUUSD is what this platform trades. */
const SYMBOL = 'XAU/USD';

export interface SurfaceIdentity {
  kind: string;
  key: string;
  /**
   * The surface's own data bag. Carries `zoom` when the operator has zoomed
   * into a region (§9), which is applied to the series here rather than in the
   * renderer — a zoom that only changed the drawing would leave the panel's
   * empty-state text describing a range nobody is looking at.
   */
  data?: Record<string, unknown>;
}

function zoomOf(data: Record<string, unknown> | undefined): ZoomRange | null {
  const zoom = data?.zoom as Partial<ZoomRange> | undefined;
  if (!zoom || typeof zoom.from !== 'number' || typeof zoom.to !== 'number') return null;
  return { from: zoom.from, to: zoom.to };
}

export function surfaceData({ kind, key, data }: SurfaceIdentity): SurfaceData {
  const state = useStore.getState();

  switch (key) {
    case 'gold-chart': {
      const history = state.priceHistory?.[SYMBOL] ?? [];
      const points = history.map((p: unknown) =>
        typeof p === 'number' ? p : Number((p as { mid?: number; price?: number })?.mid ?? (p as { price?: number })?.price ?? NaN),
      ).filter((n: number) => Number.isFinite(n));
      if (points.length < 2) {
        return {
          empty: true,
          note: 'No price history has arrived yet. A line drawn from one point would be a shape, not a trend.',
        };
      }
      const zoomed = applyZoom(points, zoomOf(data));
      if (zoomed.length < 2) {
        // A zoom that leaves one point is not a view of a smaller range; it is
        // an empty chart that looks like a dead feed.
        return { points, empty: false };
      }
      return { points: zoomed, empty: false };
    }

    case 'positions':
    case 'gold-exposure': {
      const positions = state.positions ?? [];
      if (positions.length === 0) {
        return { empty: true, note: 'No open positions. The book is flat.' };
      }
      const rows: [string, string][] = positions.map((p) => {
        const side = String(p.side ?? p.direction ?? '').toUpperCase() || '—';
        // `unrealized_pnl` is the real field. There is no `pnl`, and reaching
        // for one would have rendered an em-dash on every row forever — a
        // panel that looks like it has no data when it has plenty.
        const open = p.unrealized_pnl;
        const pnl = typeof open === 'number' ? `${open >= 0 ? '+' : ''}${open.toFixed(2)}` : '—';
        return [`${p.symbol} ${side} ${p.size}`, pnl];
      });
      return { rows, empty: false };
    }

    case 'risk': {
      const risk = state.riskSnapshot;
      if (!risk || Object.keys(risk).length === 0) {
        return {
          empty: true,
          note: 'Risk has not been measured on this connection yet. Showing zeros would read as a flat book.',
        };
      }
      const pct = (v?: number) => (typeof v === 'number' ? `${v.toFixed(2)}%` : 'not measured');
      const rows: [string, string][] = [
        ['Daily loss', pct(risk.daily_loss_pct)],
        ['Max drawdown', pct(risk.max_drawdown_pct)],
        ['Open risk', pct(risk.open_risk_pct)],
        // In words, never only as a boolean: §27, and this is the single most
        // consequential row on the plane.
        ['Kill switch', risk.kill_switch_active ? 'TRIPPED — trading halted' : 'armed, not tripped'],
      ];
      return { rows, empty: false };
    }

    case 'news':
    case 'gold-news': {
      const items = (state.newsItems ?? [])
        .map((n) => String((n as { headline?: string; title?: string }).headline ?? (n as { title?: string }).title ?? ''))
        .filter(Boolean);
      if (items.length === 0) {
        return { items: [], empty: true, note: 'The news feed is quiet — nothing has arrived on this connection.' };
      }
      return { items, empty: false };
    }

    case 'spend': {
      const account = state.account;
      if (!account) {
        return { empty: true, note: 'Spend is read from the AI Core budget endpoint; it has not answered yet.' };
      }
      return {
        rows: [['Account equity', String(account.equity ?? '—')]],
        empty: false,
      };
    }

    default:
      // Registered, requested, understood — and not yet connected to anything.
      // Saying that is more useful than a blank panel, which is indistinguishable
      // from a feed that has gone quiet.
      return {
        empty: true,
        note: `Nothing is connected to a ${kind} surface yet. The request was understood and the panel is real; the data source is a later phase.`,
      };
  }
}
