/**
 * hub/SurfaceView.tsx — one surface on the plane.
 *
 * §21 (visualization intelligence) and §23 (a component registry for all
 * renderable surface types). The registry is the `RENDERERS` map below: adding a
 * surface type is adding an entry, and a kind with no entry renders as a stated
 * gap rather than as a blank rectangle.
 *
 * That last part matters more than it looks. A missing renderer that draws
 * nothing is indistinguishable from a panel whose data has not arrived, and an
 * operator cannot tell which they are looking at. Saying "this deployment cannot
 * draw a heatmap yet" is a smaller failure and a much more useful one.
 */

import React from 'react';
import { Pin, Table as TableIcon, X } from 'lucide-react';
import type { Surface } from './workspace';
import { surfaceData, type SurfaceData } from './surfaceData';
import { focusTransition } from './spatial';
import {
  Heatmap, HeatmapTable, Media, NetworkGraph, NetworkTable, Timeline, TimelineTable,
} from './VizMarks';
import { usePrefersReducedMotion } from './usePrefersReducedMotion';
import { VIRTUALIZE_ABOVE, VirtualList } from './VirtualList';

const C = {
  hull: 'linear-gradient(155deg, rgba(16,26,44,.92), rgba(11,19,34,.92))',
  edge: '#1e2d47',
  text: '#e7edf7',
  dim: '#a7b5c9',
  quiet: '#70809a',
  core: '#73a7ff',
  ok: '#42d392',
  /** The AI is describing this one. Distinct from operator focus (`core`). */
  speak: '#42d392',
  warn: '#f5b84b',
  bad: '#f36d78',
} as const;

const label: React.CSSProperties = {
  fontSize: 9,
  fontWeight: 800,
  letterSpacing: '.14em',
  textTransform: 'uppercase',
  color: C.quiet,
};

const iconBtn: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 26,
  height: 26,
  borderRadius: 6,
  border: `1px solid ${C.edge}`,
  background: 'rgba(10,17,30,.8)',
  color: C.quiet,
  cursor: 'pointer',
  padding: 0,
};

/**
 * The component registry (§23).
 *
 * Each renderer receives the surface and draws its content only — the frame,
 * the title and the controls belong to `SurfaceView`, so every surface has the
 * same edges and the same way to close it.
 */
type RendererProps = { surface: Surface; data: SurfaceData; onDrill?: (label: string) => void };

const RENDERERS: Record<string, React.FC<RendererProps>> = {
  chart: ({ data }) => <Sparkline points={data.points ?? []} />,
  table: ({ data }) => <Rows rows={data.rows ?? []} />,
  news: ({ data }) => <Headlines items={data.items ?? []} />,
  text: ({ surface, data }) => (
    <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6, color: C.dim }}>
      {data.body ?? surface.meaning}
    </p>
  ),
  terminal: ({ data }) => (
    <pre
      style={{
        margin: 0,
        fontSize: 11,
        lineHeight: 1.6,
        color: C.dim,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        whiteSpace: 'pre-wrap',
        overflowX: 'auto',
      }}
    >
      {data.body ?? ''}
    </pre>
  ),
  distribution: ({ data }) => <Bars values={data.values ?? []} />,
  agent_activity: ({ data }) => <Rows rows={data.rows ?? []} />,
  heatmap: ({ data, onDrill }) => <Heatmap cells={data.cells ?? []} onDrill={onDrill} />,
  network: ({ data, onDrill }) => (
    <NetworkGraph nodes={data.nodes ?? []} edges={data.edges ?? []} onDrill={onDrill} />
  ),
  timeline: ({ data, onDrill }) => <Timeline events={data.events ?? []} onDrill={onDrill} />,
  image: ({ data }) =>
    data.media ? <Media media={data.media} /> : <Empty>No image source.</Empty>,
  video: ({ data }) =>
    data.media ? <Media media={data.media} /> : <Empty>No video source.</Empty>,
};

/**
 * The table-view twin (§21, and the accessibility rule behind it).
 *
 * A heatmap encodes magnitude in colour and a graph encodes category in colour.
 * Colour is not a channel everybody has, and a tooltip is not the answer because
 * it gates the value behind a gesture nobody can perform on a keyboard-only
 * screen reader. So every mark that encodes in colour has a text equivalent, and
 * the panel carries a switch between them.
 *
 * A kind with no entry here has no colour-only encoding to escape from.
 */
const TABLES: Record<string, React.FC<{ data: SurfaceData }>> = {
  heatmap: ({ data }) => <HeatmapTable cells={data.cells ?? []} />,
  network: ({ data }) => <NetworkTable nodes={data.nodes ?? []} edges={data.edges ?? []} />,
  timeline: ({ data }) => <TimelineTable events={data.events ?? []} />,
};

export interface SurfaceViewProps {
  surface: Surface;
  /**
   * Grid columns out of 12, decided by `hub/layout.ts`.
   *
   * Not read from `surface.span` any more. The surface's own span is its
   * TIER's opinion — a statement about importance — and a layout is a statement
   * about what the operator is doing. The two disagree constantly: two things
   * being compared must be the same size even when one outranks the other.
   * Defaults to the tier so a caller that has no layout still renders sensibly.
   */
  span?: number;
  focused: boolean;
  /** The AI is talking about this surface right now (§9, §10). */
  spokenAbout?: boolean;
  onClose: () => void;
  onPin: () => void;
  /**
   * §21 interactive drill-down: the reader clicked one mark and wants what is
   * behind it. Carries the mark's own description, so the layer this opens is
   * named after what was clicked rather than after the panel.
   */
  onDrill?: (surface: Surface, label: string) => void;
}

export const SurfaceView: React.FC<SurfaceViewProps> = ({
  surface, span, focused, spokenAbout = false, onClose, onPin, onDrill,
}) => {
  const Renderer = RENDERERS[surface.kind];
  const Table = TABLES[surface.kind];
  const [asTable, setAsTable] = React.useState(false);
  // Resolved here rather than inside each renderer, so "there is nothing to
  // show" is decided in ONE place and cannot be answered differently by a
  // sparkline and a table looking at the same absent feed.
  const data = surfaceData({ kind: surface.kind, key: surface.key, data: surface.data });

  // §9 animated focus transitions. Transform and opacity only, 200ms, and
  // removed outright rather than shortened when the viewer asked for less
  // motion — a 1ms transform is still a transform.
  const reducedMotion = usePrefersReducedMotion();
  const motion = focusTransition({ focused, spokenAbout, reducedMotion });

  return (
    <section
      aria-label={surface.meaning}
      // Announced, not only drawn. A highlight that exists solely as a border
      // colour tells a screen-reader user nothing about which panel the AI is
      // describing — §27, and colour is never the only indicator here.
      aria-current={spokenAbout ? 'true' : undefined}
      data-spoken-about={spokenAbout ? 'true' : undefined}
      // Read back by the stage to measure where this panel actually is, so the
      // AI can say "top right" only when that is measured to be true.
      data-surface-id={surface.id}
      // Focus is expressed only as a border colour and a shadow. Colour is not
      // a channel everybody has (§27), and it is not a channel a test has
      // either — this is the same fact, stated once, for both readers.
      data-focused={focused ? 'true' : undefined}
      style={{
        gridColumn: `span ${span ?? surface.span}`,
        display: 'grid',
        gridTemplateRows: 'auto 1fr',
        gap: 9,
        padding: 12,
        borderRadius: 11,
        background: C.hull,
        border: `1px solid ${spokenAbout ? C.speak : focused ? C.core : C.edge}`,
        boxShadow: spokenAbout
          ? `0 0 0 1px ${C.speak}, 0 0 22px rgba(66,211,146,.22)`
          : focused
            ? '0 0 0 1px rgba(115,167,255,.25)'
            : 'none',
        // 150-300ms: fast enough to track a sentence, slow enough not to flicker
        // through a list of short ones.
        transition: motion.transition,
        transform: motion.transform,
        minWidth: 0,
        minHeight: 128,
        boxSizing: 'border-box',
      }}
    >
      <header style={{ display: 'flex', alignItems: 'flex-start', gap: 8, justifyContent: 'space-between' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ ...label, color: spokenAbout ? C.speak : C.quiet }}>
            {spokenAbout ? 'speaking about' : surface.kind.replace('_', ' ')}
          </div>
          <h3
            style={{
              margin: '3px 0 0',
              fontSize: 13.5,
              fontWeight: 600,
              color: C.text,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {surface.meaning}
          </h3>
        </div>
        <div style={{ display: 'flex', gap: 5, flex: '0 0 auto' }}>
          {Table && (
            <button
              type="button"
              onClick={() => setAsTable((v) => !v)}
              aria-label={asTable ? `Show ${surface.meaning} as a chart` : `Show ${surface.meaning} as a table`}
              aria-pressed={asTable}
              style={{ ...iconBtn, color: asTable ? C.core : C.quiet }}
            >
              <TableIcon size={12} aria-hidden />
            </button>
          )}
          <button
            type="button"
            onClick={onPin}
            aria-label={surface.pinned ? `Unpin ${surface.meaning}` : `Pin ${surface.meaning}`}
            aria-pressed={surface.pinned}
            style={{ ...iconBtn, color: surface.pinned ? C.core : C.quiet }}
          >
            <Pin size={12} aria-hidden />
          </button>
          <button type="button" onClick={onClose} aria-label={`Close ${surface.meaning}`} style={iconBtn}>
            <X size={12} aria-hidden />
          </button>
        </div>
      </header>

      <div style={{ minWidth: 0, overflow: 'hidden' }}>
        {!Renderer ? (
          // Stated, not blank. A missing renderer that draws nothing is
          // indistinguishable from data that has not arrived.
          <p style={{ margin: 0, fontSize: 12, color: C.warn, lineHeight: 1.6 }}>
            This deployment cannot draw a <strong>{surface.kind}</strong> yet. The surface is registered and
            the request was understood — only the renderer is missing.
          </p>
        ) : data.empty ? (
          // Why it is empty, which is a different fact from being empty. A flat
          // book and a dead feed both render as nothing unless somebody says
          // which one this is.
          <p style={{ margin: 0, fontSize: 12, color: C.quiet, lineHeight: 1.6 }}>{data.note}</p>
        ) : asTable && Table ? (
          <Table data={data} />
        ) : (
          <Renderer
            surface={surface}
            data={data}
            onDrill={onDrill ? (label) => onDrill(surface, label) : undefined}
          />
        )}
      </div>
    </section>
  );
};

// ── small renderers ──────────────────────────────────────────────────────────

const Sparkline: React.FC<{ points: number[] }> = ({ points }) => {
  if (points.length < 2) return <Empty>Not enough data to draw a line.</Empty>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const d = points
    .map((p, i) => `${(i / (points.length - 1)) * 100},${100 - ((p - min) / range) * 100}`)
    .join(' ');
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height: 76 }} role="img"
      aria-label={`Line from ${min.toFixed(2)} to ${max.toFixed(2)}`}>
      <polyline points={d} fill="none" stroke={C.core} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
};

const Bars: React.FC<{ values: number[] }> = ({ values }) => {
  const max = Math.max(...values, 1);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 76 }} role="img" aria-label="Distribution">
      {values.map((v, i) => (
        <div
          key={i}
          style={{ flex: 1, height: `${(v / max) * 100}%`, background: C.core, opacity: 0.5, borderRadius: 2 }}
        />
      ))}
    </div>
  );
};

/** Row height the virtual window is computed from. Matches the 12px/1.4 line box. */
const ROW_HEIGHT = 22;

/** Scroll-container height for a virtualised list inside a panel. */
const LIST_HEIGHT = 220;

const Row: React.FC<{ pair: [string, string] }> = ({ pair: [k, v] }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, height: ROW_HEIGHT, alignItems: 'center' }}>
    <span style={{ color: C.quiet }}>{k}</span>
    <span style={{ color: C.text, fontVariantNumeric: 'tabular-nums' }}>{v}</span>
  </div>
);

/**
 * §26. Short tables render whole; long ones render a window.
 *
 * Before this, every row went into the document — a surface carrying five
 * thousand rows put five thousand nodes on the plane, and `windowFor` had been
 * sitting in `virtualization.ts` since Phase D1 with nothing calling it.
 *
 * The `<dl>` is dropped in the virtual case rather than half-populated: a
 * definition list whose terms are a scrolled subset is worse markup than a
 * labelled group, because assistive technology reports its length.
 */
const Rows: React.FC<{ rows: [string, string][] }> = ({ rows }) => {
  if (rows.length === 0) return <Empty>Nothing to show.</Empty>;
  if (rows.length <= VIRTUALIZE_ABOVE) {
    return (
      <dl style={{ margin: 0, display: 'grid', gap: 5, fontSize: 12 }}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
            <dt style={{ color: C.quiet }}>{k}</dt>
            <dd style={{ margin: 0, color: C.text, fontVariantNumeric: 'tabular-nums' }}>{v}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <div style={{ fontSize: 12 }}>
      <VirtualList
        items={rows}
        itemHeight={ROW_HEIGHT}
        height={LIST_HEIGHT}
        noun="rows"
        label="Table rows"
        keyFor={([k], i) => `${k}-${i}`}
        renderItem={(pair) => <Row pair={pair} />}
      />
    </div>
  );
};

const Headlines: React.FC<{ items: string[] }> = ({ items }) => {
  if (items.length === 0) return <Empty>No headlines.</Empty>;
  if (items.length <= VIRTUALIZE_ABOVE) {
    return (
      <ul style={{ margin: 0, paddingLeft: 15, display: 'grid', gap: 5, fontSize: 12, color: C.dim }}>
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    );
  }
  return (
    <div style={{ fontSize: 12, color: C.dim }}>
      <VirtualList
        items={items}
        itemHeight={ROW_HEIGHT}
        height={LIST_HEIGHT}
        noun="headlines"
        label="Headlines"
        keyFor={(t, i) => `${t}-${i}`}
        renderItem={(t) => (
          <div style={{ display: 'flex', alignItems: 'center', height: ROW_HEIGHT }}>{t}</div>
        )}
      />
    </div>
  );
};

const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p style={{ margin: 0, fontSize: 12, color: C.quiet }}>{children}</p>
);
