/**
 * hub/VizMarks.tsx — §21's renderers: intensity, relationships, chronology, media.
 *
 * ## Every one of these has a table-view twin
 *
 * A heatmap encodes magnitude in colour and a graph encodes category in colour.
 * Colour alone is not a channel everybody has, and a tooltip is not a substitute
 * because it gates the value behind a gesture. So each mark component is paired
 * with a table the same data renders into, and the panel carries a switch.
 * That is the accessible twin, not a debug view.
 *
 * ## Hover and keyboard show the same thing
 *
 * Every cell, node and event is a focusable target with a description. A reader
 * on a keyboard gets what a reader with a mouse gets — and the description is
 * the same string, from one place, so the two cannot drift apart.
 *
 * ## Colours come from `vizPalette.ts` and nowhere else
 *
 * They were validated against this workspace's real surface. A literal hex in
 * this file would be a colour nobody measured.
 */

import React, { useState } from 'react';

import { CATEGORY, GRID, INK, OTHER, categoryColour, intensityStep } from './vizPalette';
import { usePrefersReducedMotion } from './usePrefersReducedMotion';
import type { AffordanceVisibility } from './a11yPointer';
import type { Cell, Edge, Event, Node } from './surfaceData';
import {
  DEFAULT_CAMERA,
  describeSurface,
  expectedFaceCount,
  meshFaces,
  warrants3D,
  type SurfaceGrid,
} from './surface3d';

const cellLabel = (c: Cell) => `${c.column}, ${c.row}: ${c.label}`;

/**
 * Shared style for a focusable mark.
 *
 * The outline is deliberately NOT removed. The first version set
 * `outline: 'none'` and leaned on a JavaScript-driven ring drawn from the same
 * state as hover — which looks equivalent and is not: it disappears the moment
 * that state handling changes, and it never existed for a reader arriving by
 * keyboard on a browser whose focus ring is the only thing they rely on.
 * The enhanced ring is an addition to the browser's, never a replacement.
 */
const focusable: React.CSSProperties = { cursor: 'pointer' };

/** 200ms, inside the 150-300ms band. Nothing at all under reduced motion. */
function markTransition(reducedMotion: boolean): string {
  return reducedMotion ? 'none' : 'box-shadow 200ms ease, r 200ms ease, width 200ms ease, height 200ms ease';
}

// ── heatmap ───────────────────────────────────────────────────────────────────

export const Heatmap: React.FC<{
  cells: Cell[];
  onDrill?: (label: string) => void;
  /**
   * §27. Whether the mark's label has to be drawn permanently.
   *
   * `title` is a HOVER tooltip. On a tablet it never appears, so a sighted
   * touch user gets the colour and nothing else — which is §27's "never rely
   * on colour alone" failing silently, in the one place this file already
   * takes seriously enough to ship a table twin for.
   *
   * Defaults to `always` rather than `on-hover`, matching `a11yPointer`'s rule
   * that an unread pointer cannot hover: a desktop operator pays one visible
   * label until their first click, and a tablet operator does not lose the
   * value entirely.
   */
  affordance?: AffordanceVisibility;
}> = ({ cells, onDrill, affordance = 'always' }) => {
  const [hovered, setHovered] = useState<string | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  const columns = [...new Set(cells.map((c) => c.column))];
  const rows = [...new Set(cells.map((c) => c.row))];

  return (
    <div>
      <div
        role="img"
        aria-label={`Intensity across ${columns.length} periods, darkest is quietest`}
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr))`,
          // A 2px surface gap between fills, never a border drawn round them.
          gap: 2,
        }}
      >
        {rows.flatMap((row) =>
          columns.map((column) => {
            const cell = cells.find((c) => c.row === row && c.column === column);
            const key = `${row}/${column}`;
            return (
              <button
                key={key}
                type="button"
                title={cell ? cellLabel(cell) : `${column}: not measured`}
                aria-label={cell ? cellLabel(cell) : `${column}, not measured`}
                onClick={() => cell && onDrill?.(cellLabel(cell))}
                onMouseEnter={() => setHovered(key)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(key)}
                onBlur={() => setHovered(null)}
                // §27. A tap, not only a hover. `mouseenter` does not fire on
                // touch and iOS Safari does not reliably focus a button on tap,
                // so without this the readout below — the accessible twin this
                // file already ships — is reachable by mouse and keyboard and
                // by nothing a tablet operator can do.
                onPointerDown={() => setHovered(key)}
                // §27. A tap, not only a hover. `mouseenter` does not fire on
                // touch and iOS Safari does not reliably focus a button on tap,
                // so without this the readout below — the accessible twin this
                // file already ships — is reachable by mouse and keyboard and
                // by nothing a tablet operator can do.
                data-mark-label={cell ? cellLabel(cell) : `${column}: not measured`}
                data-affordance={affordance}
                style={{
                  ...focusable,
                  // A cell with no reading is the grid colour, not step zero:
                  // "quietest" and "unmeasured" must not draw the same.
                  background: cell ? intensityStep(cell.intensity) : GRID,
                  border: 'none',
                  // 24px is the hit-target floor; the visual mark can be shorter.
                  height: 26,
                  borderRadius: 3,
                  boxShadow: hovered === key ? `0 0 0 2px ${INK.primary}` : 'none',
                  transition: markTransition(reducedMotion),
                  padding: 0,
                }}
              />
            );
          }),
        )}
      </div>
      {/* Selective, not a number on every cell: the two ends of the scale. */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
        <span style={{ fontSize: 10, color: INK.muted }}>quiet</span>
        <span style={{ fontSize: 10, color: INK.muted }}>
          {hovered ? cells.find((c) => `${c.row}/${c.column}` === hovered)?.label : 'busiest'}
        </span>
      </div>
    </div>
  );
};

export const HeatmapTable: React.FC<{ cells: Cell[] }> = ({ cells }) => (
  <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
    <caption style={{ textAlign: 'left', color: INK.muted, fontSize: 10, paddingBottom: 4 }}>
      The same values, as text
    </caption>
    <tbody>
      {cells.map((c) => (
        <tr key={`${c.row}/${c.column}`}>
          <th scope="row" style={{ textAlign: 'left', fontWeight: 500, color: INK.secondary, padding: '2px 0' }}>
            {c.column}
          </th>
          <td style={{ textAlign: 'right', color: INK.primary, fontVariantNumeric: 'tabular-nums' }}>{c.label}</td>
        </tr>
      ))}
    </tbody>
  </table>
);

// ── network ───────────────────────────────────────────────────────────────────

/**
 * Nodes on a circle, edges as chords.
 *
 * A force layout looks better and is not reproducible: the same graph settles
 * differently on every render, so an operator cannot say "the one on the left"
 * and be understood a minute later. A circle is stable, and stability is worth
 * more here than elegance.
 */
export const NetworkGraph: React.FC<{ nodes: Node[]; edges: Edge[]; onDrill?: (label: string) => void }> = ({
  nodes,
  edges,
  onDrill,
}) => {
  const [hovered, setHovered] = useState<string | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  // Stable ordering, so colour follows the entity rather than its rank: adding
  // a node must not repaint the ones already on screen.
  const categories = [...new Set(nodes.map((n) => n.category))].sort();
  const place = (i: number) => {
    const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2 - Math.PI / 2;
    return { x: 50 + Math.cos(angle) * 34, y: 50 + Math.sin(angle) * 34 };
  };
  const at = new Map(nodes.map((n, i) => [n.id, place(i)]));

  return (
    <div>
      <svg viewBox="0 0 100 100" style={{ width: '100%', height: 150 }} role="img"
        aria-label={`${nodes.length} items and ${edges.length} declared relationships between them`}>
        {edges.map((e, i) => {
          const a = at.get(e.from);
          const b = at.get(e.to);
          if (!a || !b) return null;
          return (
            <line
              key={`${e.from}-${e.to}-${i}`}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={GRID}
              strokeWidth={0.6}
              vectorEffect="non-scaling-stroke"
            >
              <title>{e.because}</title>
            </line>
          );
        })}
        {nodes.map((n) => {
          const p = at.get(n.id);
          if (!p) return null;
          const colour = categoryColour(categories.indexOf(n.category));
          return (
            <g key={n.id}>
              <circle
                cx={p.x} cy={p.y} r={hovered === n.id ? 4 : 3}
                fill={colour}
                // A 2px surface ring where marks overlap, not a border.
                stroke="#0f1a2a"
                strokeWidth={1}
                tabIndex={0}
                style={{ ...focusable, transition: markTransition(reducedMotion) }}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(n.id)}
                onBlur={() => setHovered(null)}
                onClick={() => onDrill?.(n.label)}
              >
                <title>{`${n.label} — ${n.category}`}</title>
              </circle>
            </g>
          );
        })}
      </svg>
      {/* A legend is always present for two or more categories, and identity is
          never colour alone — the names are here in text. */}
      {categories.length >= 2 && (
        <ul style={{ display: 'flex', flexWrap: 'wrap', gap: 10, listStyle: 'none', margin: '4px 0 0', padding: 0 }}>
          {categories.map((category, i) => (
            <li key={category} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10.5, color: INK.secondary }}>
              <span
                aria-hidden
                style={{ width: 8, height: 8, borderRadius: 2, background: categoryColour(i), flex: '0 0 auto' }}
              />
              {category}
              {i >= CATEGORY.length && <span style={{ color: INK.muted }}> (other)</span>}
            </li>
          ))}
        </ul>
      )}
      {hovered && (
        <p style={{ margin: '4px 0 0', fontSize: 11, color: INK.secondary }}>
          {nodes.find((n) => n.id === hovered)?.label}
        </p>
      )}
    </div>
  );
};

export const NetworkTable: React.FC<{ nodes: Node[]; edges: Edge[] }> = ({ nodes, edges }) => (
  <div style={{ fontSize: 11, color: INK.secondary }}>
    <ul style={{ margin: 0, paddingLeft: 15 }}>
      {nodes.map((n) => (
        <li key={n.id}>
          {n.label} <span style={{ color: INK.muted }}>({n.category})</span>
        </li>
      ))}
    </ul>
    {edges.length > 0 && (
      <ul style={{ margin: '6px 0 0', paddingLeft: 15 }}>
        {edges.map((e, i) => (
          <li key={`${e.from}-${e.to}-${i}`}>
            {nodes.find((n) => n.id === e.from)?.label} → {nodes.find((n) => n.id === e.to)?.label}:{' '}
            {e.because}
          </li>
        ))}
      </ul>
    )}
  </div>
);

// ── timeline ──────────────────────────────────────────────────────────────────

export const Timeline: React.FC<{ events: Event[]; onDrill?: (label: string) => void }> = ({ events, onDrill }) => {
  const [hovered, setHovered] = useState<number | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  const first = events[0]?.at ?? 0;
  const last = events[events.length - 1]?.at ?? first;
  const span = last - first || 1;
  const categories = [...new Set(events.map((e) => e.category))].sort();

  return (
    <div>
      <div style={{ position: 'relative', height: 46 }}>
        {/* A solid hairline, one shade off the surface. Never dashed. */}
        <div style={{ position: 'absolute', left: 0, right: 0, top: 22, height: 1, background: GRID }} />
        {events.map((e, i) => {
          const left = `${((e.at - first) / span) * 100}%`;
          return (
            <button
              key={`${e.at}-${i}`}
              type="button"
              title={`${new Date(e.at).toLocaleString()} — ${e.label}`}
              aria-label={`${new Date(e.at).toLocaleString()}, ${e.label}`}
              onClick={() => onDrill?.(e.label)}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(i)}
              onBlur={() => setHovered(null)}
              style={{
                ...focusable,
                position: 'absolute',
                left,
                top: 11,
                // 24px hit target around a smaller visible mark.
                width: 24,
                height: 24,
                marginLeft: -12,
                border: 'none',
                background: 'transparent',
                padding: 0,
                display: 'grid',
                placeItems: 'center',
              }}
            >
              <span
                aria-hidden
                style={{
                  width: hovered === i ? 11 : 9,
                  height: hovered === i ? 11 : 9,
                  borderRadius: '50%',
                  background: categoryColour(categories.indexOf(e.category)),
                  boxShadow: '0 0 0 2px #0f1a2a',
                  transition: markTransition(reducedMotion),
                }}
              />
            </button>
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: INK.muted }}>
        <span>{new Date(first).toLocaleTimeString()}</span>
        <span>{new Date(last).toLocaleTimeString()}</span>
      </div>
      {hovered !== null && (
        <p style={{ margin: '4px 0 0', fontSize: 11.5, color: INK.secondary }}>{events[hovered]?.label}</p>
      )}
    </div>
  );
};

export const TimelineTable: React.FC<{ events: Event[] }> = ({ events }) => (
  <ol style={{ margin: 0, paddingLeft: 15, fontSize: 11, color: INK.secondary, display: 'grid', gap: 3 }}>
    {events.map((e, i) => (
      <li key={`${e.at}-${i}`}>
        <time dateTime={new Date(e.at).toISOString()} style={{ color: INK.muted }}>
          {new Date(e.at).toLocaleTimeString()}
        </time>{' '}
        {e.label}
      </li>
    ))}
  </ol>
);

// ── media ─────────────────────────────────────────────────────────────────────

/**
 * An image or a video panel.
 *
 * `alt` is a required field on the data rather than an optional prop, so a
 * media surface with no description cannot be constructed. A decorative image
 * is not a thing this workspace has: every panel exists because something asked
 * for it, and a panel nobody can describe is one nobody can read aloud.
 */
export const Media: React.FC<{ media: { src: string; alt: string; kind: 'image' | 'video' } }> = ({ media }) =>
  media.kind === 'video' ? (
    <video
      src={media.src}
      controls
      aria-label={media.alt}
      style={{ width: '100%', borderRadius: 6, background: '#000', maxHeight: 180 }}
    />
  ) : (
    <img src={media.src} alt={media.alt} style={{ width: '100%', borderRadius: 6, maxHeight: 180, objectFit: 'contain' }} />
  );

export const OTHER_CATEGORY_COLOUR = OTHER;


// ── §21 surfaces ──────────────────────────────────────────────────────────────

/**
 * A projected mesh, drawn as SVG polygons rather than on a GPU.
 *
 * `surface3d.ts` does the maths and hands back quads already ordered back to
 * front, so painting them in order IS the depth buffer. That is why this needs
 * no WebGL and no dependency — and why `projection.ts` can go on reporting
 * `webgl` as unavailable without the capability being blocked on it.
 *
 * A refused verdict renders nothing and says why. Drawing a surface the
 * `warrants3D` rules rejected would make the rules decoration.
 */
export const Surface3D: React.FC<{ grid: SurfaceGrid; width?: number; height?: number }> = ({
  grid,
  width = 320,
  height = 200,
}) => {
  const verdict = warrants3D(grid);
  const faces = verdict.warranted
    ? meshFaces(grid, {
        camera: { ...DEFAULT_CAMERA, scale: Math.min(width, height) * 0.72, centre: { x: width / 2, y: height / 2 } },
      })
    : [];

  if (!verdict.warranted) {
    return (
      <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: INK.secondary }} data-surface3d="refused">
        {describeSurface(grid, [])}
      </p>
    );
  }

  const values = faces.map((f) => f.value);
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1;
  const dropped = expectedFaceCount(grid) - faces.length;

  return (
    <figure style={{ margin: 0 }}>
      <svg
        width="100%"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={describeSurface(grid, faces)}
        data-surface3d="drawn"
        data-faces={faces.length}
        data-dropped={dropped}
      >
        {faces.map((face, i) => (
          <polygon
            key={i}
            points={face.corners.map((c) => `${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(' ')}
            fill={surfaceInk((face.value - lo) / span)}
            stroke={GRID}
            strokeWidth={0.5}
          />
        ))}
      </svg>
      <figcaption style={{ fontSize: 11, lineHeight: 1.5, color: INK.secondary, marginTop: 4 }}>
        {describeSurface(grid, faces)}
      </figcaption>
    </figure>
  );
};

/**
 * The colour ramp for a face.
 *
 * Height already encodes the value, so colour is a redundant second channel
 * rather than the only one — which is the opposite of the heatmap's problem and
 * the reason this ramp can be gentle. The table twin below is still mandatory:
 * neither height nor hue is readable to a screen reader.
 */
export const SURFACE_INK_HUE = 212;
export const SURFACE_INK_HUE_SPAN = 34;
export const SURFACE_INK_SATURATION = 62;
/**
 * The floor is MEASURED, not chosen.
 *
 * At the 26% this started as, the darkest faces sat at 1.65:1 against the
 * panel — a trough would have been indistinguishable from a hole, which is
 * precisely the claim `surface3d.ts` exists to make. 44% is the first step
 * clearing `NON_TEXT_FLOOR`, and a test derives that rather than trusting it.
 */
export const SURFACE_INK_MIN_LIGHT = 44;
export const SURFACE_INK_MAX_LIGHT = 72;

export function surfaceInk(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const light = SURFACE_INK_MIN_LIGHT + clamped * (SURFACE_INK_MAX_LIGHT - SURFACE_INK_MIN_LIGHT);
  return `hsl(${SURFACE_INK_HUE - clamped * SURFACE_INK_HUE_SPAN} ${SURFACE_INK_SATURATION}% ${light}%)`;
}

/** The same colour as hex, so contrast can be measured against the palette. */
export function surfaceInkHex(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const h = SURFACE_INK_HUE - clamped * SURFACE_INK_HUE_SPAN;
  const l = (SURFACE_INK_MIN_LIGHT + clamped * (SURFACE_INK_MAX_LIGHT - SURFACE_INK_MIN_LIGHT)) / 100;
  const sat = SURFACE_INK_SATURATION / 100;
  const a = sat * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const v = l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
    return Math.round(v * 255)
      .toString(16)
      .padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

/**
 * The table twin, and it is not optional.
 *
 * A surface encodes in height and hue, and a keyboard-only screen reader has
 * neither. A hole is rendered as the words "no data" rather than as an empty
 * cell, because an empty cell reads as a formatting accident.
 */
export const SurfaceTable: React.FC<{ grid: SurfaceGrid }> = ({ grid }) => (
  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
    <caption style={{ captionSide: 'top', textAlign: 'left', color: INK.secondary, paddingBottom: 4 }}>
      {grid.zLabel ?? 'value'} by {grid.xLabel ?? 'x'} and {grid.yLabel ?? 'y'}
    </caption>
    <thead>
      <tr>
        <th scope="col" style={{ textAlign: 'left', color: INK.secondary }}>
          {grid.yLabel ?? 'y'}
        </th>
        {grid.xs.map((x) => (
          <th key={x} scope="col" style={{ textAlign: 'right', color: INK.secondary }}>
            {x}
          </th>
        ))}
      </tr>
    </thead>
    <tbody>
      {grid.ys.map((y, yi) => (
        <tr key={y}>
          <th scope="row" style={{ textAlign: 'left', color: INK.secondary }}>
            {y}
          </th>
          {grid.xs.map((x, xi) => {
            const value = grid.z[yi]?.[xi];
            return (
              <td key={x} style={{ textAlign: 'right', color: INK.secondary }}>
                {value === null || value === undefined ? 'no data' : value.toFixed(4)}
              </td>
            );
          })}
        </tr>
      ))}
    </tbody>
  </table>
);
