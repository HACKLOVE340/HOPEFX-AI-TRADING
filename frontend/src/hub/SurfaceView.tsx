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
import { surfacePalette } from './a11yContrast';
import { useContrastMode } from './useContrastMode';
import {
  affordanceVisibility,
  pointerKindFrom,
  type AffordanceVisibility,
  type PointerKind,
} from './a11yPointer';

/**
 * The panel's structural colours, and its text colours at STANDARD contrast.
 *
 * The text roles come from the §27 palette, which is measured against the
 * composited panel hull on every test run rather than chosen by eye — spread
 * here so a literal cannot creep back in. `hull` and `edge` stay local: they
 * are surfaces, not text, and different contrast floors govern them.
 *
 * A component that wants the operator's actual mode calls `surfacePalette`
 * with it. `C` is what a module-level style object can use before any hook
 * has run.
 */
const STANDARD = surfacePalette('standard');

/**
 * The panel's colours, as CSS custom properties with the standard palette as
 * the fallback.
 *
 * A variable rather than a literal so the operator's contrast mode reaches
 * every leaf at once. The alternative was threading a palette through
 * `Rows`, `Headlines`, `Prose`, `Code` and six more — which works until
 * somebody adds the eleventh and forgets, and then one element stays at
 * standard contrast in high-contrast mode and nothing says so.
 *
 * The fallback is the standard palette, so a module-level style object
 * evaluated before any panel has mounted still resolves to a measured colour.
 * `hull` and `edge` stay literal: they are surfaces, not text, and different
 * contrast floors govern them.
 */
const C = {
  hull: 'linear-gradient(155deg, rgba(16,26,44,.92), rgba(11,19,34,.92))',
  edge: '#1e2d47',
  text: `var(--panel-text, ${STANDARD.text})`,
  dim: `var(--panel-dim, ${STANDARD.dim})`,
  quiet: `var(--panel-quiet, ${STANDARD.quiet})`,
  core: `var(--panel-core, ${STANDARD.core})`,
  ok: `var(--panel-ok, ${STANDARD.ok})`,
  speak: `var(--panel-speak, ${STANDARD.speak})`,
  warn: `var(--panel-warn, ${STANDARD.warn})`,
  bad: `var(--panel-bad, ${STANDARD.bad})`,
} as const;

/**
 * Raw values for the places a CSS variable cannot go.
 *
 * A canvas fill, an SVG attribute and a computed gradient all need a real
 * colour. Kept beside `C` so the two cannot name different sets of roles.
 */
const RAW = STANDARD;

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
type RendererProps = {
  surface: Surface;
  data: SurfaceData;
  onDrill?: (label: string) => void;
  /**
   * §27. Whether a mark's label must be drawn permanently rather than on hover.
   *
   * Decided once, in the panel, from the pointer actually in use — a renderer
   * that detected this itself would be one more place to get it wrong, and the
   * places that get it wrong are the ones nobody tests on a tablet.
   */
  affordance: AffordanceVisibility;
};

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
  heatmap: ({ data, onDrill, affordance }) => (
    <Heatmap cells={data.cells ?? []} onDrill={onDrill} affordance={affordance} />
  ),
  network: ({ data, onDrill }) => (
    <NetworkGraph nodes={data.nodes ?? []} edges={data.edges ?? []} onDrill={onDrill} />
  ),
  timeline: ({ data, onDrill }) => <Timeline events={data.events ?? []} onDrill={onDrill} />,
  image: ({ data }) =>
    data.media ? <Media media={data.media} /> : <Empty>No image source.</Empty>,
  video: ({ data }) =>
    data.media ? <Media media={data.media} /> : <Empty>No video source.</Empty>,
  // §8's remaining text-shaped kinds. They were unrendered not for want of a
  // renderer but because `surfaceData` discarded caller-supplied content, so
  // there was never anything for one to draw.
  document: ({ data }) => <Prose body={data.body ?? ''} />,
  research: ({ data }) =>
    data.items ? <Headlines items={data.items} /> : data.rows ? <Rows rows={data.rows} /> : <Prose body={data.body ?? ''} />,
  code: ({ data }) => <Code body={data.body ?? ''} />,
  // A camera panel draws its CONSENT state, not a stream. §25 already decides
  // whether the camera may be used, and a panel that said "this deployment
  // cannot draw a camera" was describing a missing renderer while the real
  // answer — nobody has agreed — was already known.
  camera: () => <CameraConsent />,
};

/**
 * The kinds that render, and the two that deliberately do not.
 *
 * Exported so the registry's §8 claim is checked against the component rather
 * than against a note somebody typed. `map` needs a tile source this
 * deployment does not have and `simulation` needs a simulator — and a map
 * drawn from nothing is worse than a panel saying it cannot draw one, because
 * an operator reads a rendered map as a map.
 */
export const RENDERED_KINDS: readonly string[] = Object.freeze(Object.keys(RENDERERS));
export const UNRENDERED_KINDS: readonly string[] = Object.freeze(['map', 'simulation']);

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

  // §27. The operator's contrast preference, and the pointer they are actually
  // using — both read here and handed down, so no renderer has to know how
  // either is detected.
  const contrast = useContrastMode();
  const palette = React.useMemo(() => surfacePalette(contrast), [contrast]);

  // Starts `unknown`, which `affordanceVisibility` treats as unable to hover.
  // Guessing mouse is how a hover-only affordance ships: the guess is
  // invisible, and the people it fails are the ones least able to work round
  // it. A desktop operator pays one visible label until their first click.
  const [pointer, setPointer] = React.useState<PointerKind>('unknown');
  const onPointerDown = React.useCallback((event: React.PointerEvent) => {
    const kind = pointerKindFrom(event.nativeEvent as unknown as { pointerType?: string });
    setPointer((previous) => (previous === kind ? previous : kind));
  }, []);
  const markAffordance = affordanceVisibility(pointer, 'on-hover');

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
      // Which contrast mode painted this, so a screenshot and a bug report can
      // agree about what was on screen.
      data-contrast={contrast}
      onPointerDown={onPointerDown}
      style={{
        // The mode's palette, published to every descendant at once. See `C`.
        ...({
          '--panel-text': palette.text,
          '--panel-dim': palette.dim,
          '--panel-quiet': palette.quiet,
          '--panel-core': palette.core,
          '--panel-ok': palette.ok,
          '--panel-speak': palette.speak,
          '--panel-warn': palette.warn,
          '--panel-bad': palette.bad,
        } as React.CSSProperties),
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
            affordance={markAffordance}
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

/** A document or a research brief: prose, at a readable measure. */
const Prose: React.FC<{ body: string }> = ({ body }) =>
  body ? (
    <div style={{ maxHeight: LIST_HEIGHT, overflowY: 'auto' }}>
      {body.split(/\n{2,}/).map((paragraph, i) => (
        <p
          key={i}
          // 65-75 characters is the readable measure; 1.6 is inside the
          // 1.5-1.75 band for body text.
          style={{ margin: i === 0 ? 0 : '9px 0 0', fontSize: 12.5, lineHeight: 1.6, color: C.dim, maxWidth: '70ch' }}
        >
          {paragraph}
        </p>
      ))}
    </div>
  ) : (
    <Empty>This document has no content.</Empty>
  );

/**
 * Code. Monospace and unhighlighted on purpose.
 *
 * A syntax highlighter is a dependency and a language guess, and a wrong guess
 * colours the code misleadingly — which is worse than no colour on a screen
 * where colour already means something else.
 */
const Code: React.FC<{ body: string }> = ({ body }) =>
  body ? (
    <pre
      style={{
        margin: 0,
        maxHeight: LIST_HEIGHT,
        overflow: 'auto',
        fontSize: 11.5,
        lineHeight: 1.6,
        color: C.text,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        // Never wrapped. Wrapped code changes what the lines are, and a line
        // number in a review comment stops matching what is on screen.
        whiteSpace: 'pre',
        tabSize: 2,
      }}
    >
      {body}
    </pre>
  ) : (
    <Empty>This code surface has no content.</Empty>
  );

/**
 * The camera panel: what the consent gate currently says.
 *
 * It never opens a stream. §25 grants consent from an explicit operator
 * action, and a panel that requested the camera because it was rendered would
 * make opening a panel the consent — which is the whole thing the gate exists
 * to prevent.
 */
const CameraConsent: React.FC = () => (
  <div style={{ display: 'grid', gap: 6 }}>
    <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: C.dim }}>
      The camera is off. Nothing is captured, streamed or stored until you grant camera consent, and
      granting it is an action you take — opening this panel is not one.
    </p>
    <p style={{ margin: 0, fontSize: 11.5, lineHeight: 1.6, color: C.quiet }}>
      Consent is per operator and can be withdrawn at any time; withdrawing it stops any use
      immediately rather than at the next request.
    </p>
  </div>
);

const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p style={{ margin: 0, fontSize: 12, color: C.quiet }}>{children}</p>
);
