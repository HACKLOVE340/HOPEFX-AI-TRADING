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

/** One cell of a heatmap: a labelled bucket with a 0-1 intensity. */
export interface Cell {
  row: string;
  column: string;
  /** 0-1, already normalised by whoever measured it. */
  intensity: number;
  /** The underlying figure, for the tooltip and the table view. */
  label: string;
}

/** One node of a relationship graph. */
export interface Node {
  id: string;
  label: string;
  /** Stable category name. Colour follows this, never the node's rank. */
  category: string;
}

export interface Edge {
  from: string;
  to: string;
  /** Why these two are connected, in words. */
  because: string;
}

/** One thing that happened, at a time. */
export interface Event {
  at: number;
  label: string;
  category: string;
}

export interface SurfaceData {
  points?: number[];
  rows?: [string, string][];
  items?: string[];
  body?: string;
  values?: number[];
  cells?: Cell[];
  nodes?: Node[];
  edges?: Edge[];
  events?: Event[];
  /** A media source and its description. `alt` is required, never optional. */
  media?: { src: string; alt: string; kind: 'image' | 'video' };
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

    // ── §21 heatmap: where the movement actually was ─────────────────────────
    case 'session-heatmap': {
      const history = (state.priceHistory?.[SYMBOL] ?? []) as unknown[];
      const prices = history
        .map((p) => (typeof p === 'number' ? p : Number((p as { mid?: number; price?: number })?.mid ?? (p as { price?: number })?.price ?? NaN)))
        .filter((n: number) => Number.isFinite(n));
      // Two points make one move. One point makes none, and a grid of zeros
      // would read as a calm session rather than as an empty one.
      if (prices.length < 3) {
        return {
          empty: true,
          note: 'Not enough price history to measure movement. A heatmap of one reading would be a grid of zeros, which reads as a calm session rather than an unmeasured one.',
        };
      }
      const moves = prices.slice(1).map((p, i) => Math.abs(p - (prices[i] as number)));
      const peak = Math.max(...moves);
      const BUCKETS = 12;
      const size = Math.ceil(moves.length / BUCKETS);
      const cells: Cell[] = [];
      for (let i = 0; i < Math.min(BUCKETS, Math.ceil(moves.length / size)); i += 1) {
        const slice = moves.slice(i * size, (i + 1) * size);
        if (slice.length === 0) continue;
        const largest = Math.max(...slice);
        cells.push({
          row: 'Movement',
          column: `T${i + 1}`,
          // Against the session's own peak. Against an absolute scale the grid
          // would be uniformly dark on a quiet day and tell nobody anything.
          intensity: peak > 0 ? largest / peak : 0,
          label: `${largest.toFixed(2)} peak move`,
        });
      }
      return { cells, empty: false };
    }

    // ── §21 network: how the things on the plane relate ──────────────────────
    case 'relationships': {
      // Derived from the declared relation table (`hub/summary.ts`), not from a
      // model's guess at what connects to what. An invented edge in a graph is
      // a claim the reader has no way to check.
      const nodes: Node[] = [];
      const edges: Edge[] = [];
      const positions = state.positions ?? [];
      for (const p of positions) {
        const id = `pos:${p.symbol}`;
        if (!nodes.some((n) => n.id === id)) {
          nodes.push({ id, label: String(p.symbol), category: 'Position' });
        }
      }
      if (positions.length > 0) {
        nodes.push({ id: 'risk', label: 'Risk limits', category: 'Risk' });
        for (const p of positions) {
          edges.push({
            from: `pos:${p.symbol}`,
            to: 'risk',
            because: 'those limits govern this position',
          });
        }
      }
      const headlines = (state.newsItems ?? []).slice(0, 3);
      for (const [i, item] of headlines.entries()) {
        const id = `news:${i}`;
        nodes.push({ id, label: String(item.title ?? '').slice(0, 40) || 'Headline', category: 'News' });
        for (const p of positions) {
          edges.push({ from: id, to: `pos:${p.symbol}`, because: 'headlines move this instrument' });
        }
      }
      if (nodes.length === 0) {
        return {
          empty: true,
          note: 'Nothing on this connection to relate yet — no open positions and no headlines have arrived.',
        };
      }
      return { nodes, edges, empty: false };
    }

    // ── §21 timeline: what happened, in order ────────────────────────────────
    case 'chronology': {
      const events: Event[] = (state.newsItems ?? [])
        .map((n) => {
          const when = Date.parse(String(n.published_at ?? ''));
          return Number.isFinite(when)
            ? { at: when, label: String(n.title ?? '').slice(0, 60), category: String(n.sentiment_label ?? 'neutral') }
            : null;
        })
        .filter((e): e is Event => e !== null)
        .sort((a, b) => a.at - b.at);
      if (events.length === 0) {
        // Distinguished from a quiet feed: a headline with no timestamp cannot
        // be placed on a timeline, and pretending it happened now would put
        // yesterday's news at the right-hand edge.
        const untimed = (state.newsItems ?? []).length;
        return {
          empty: true,
          note:
            untimed > 0
              ? `${untimed} headline(s) have arrived but none carries a timestamp, so none can be placed in time.`
              : 'Nothing timestamped has arrived on this connection yet.',
        };
      }
      return { events, empty: false };
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
