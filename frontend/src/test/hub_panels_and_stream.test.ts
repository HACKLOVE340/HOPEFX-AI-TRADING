/**
 * Phase D2 — the last of §23: panels nobody hand-wrote, a second layout
 * geometry, accessibility that survives generation, and two streams that must
 * never become one.
 *
 * ## Generated panels are where accessibility quietly dies
 *
 * A hand-written panel gets a label because someone typed one. A generated
 * panel gets whatever the generator remembered — and the usual answer is
 * nothing, so a screen reader announces "region" forty times. §23 asks for
 * schema-driven generation and §27 asks for accessibility; the only way both
 * survive is for the descriptor to be **unable** to exist without a label.
 * `describePanel` refuses rather than emitting an unlabelled panel.
 *
 * ## A panel that cannot be drawn says so
 *
 * A `chart` with no series is not a chart. Rendering an empty frame produces a
 * panel that looks like a loading state for ever, and an operator waiting for
 * data that was never coming. `unrenderable` carries the reason instead.
 *
 * ## The layout engine gains a geometry, not a rewrite
 *
 * `place()` already decides span, visibility and collapse across seven layouts.
 * That is the CONTENT-independent half and it is not touched here: 2,231
 * existing tests depend on its output. The second strategy sits on top and
 * turns the same placements into different geometry — grid today, stack for
 * reading and for narrow screens.
 *
 * ## The cognitive stream is two streams, and they must not merge
 *
 * §3 lists a "cognitive stream" among what the platform already has. It does
 * not exist. The version worth building is the one §23 actually asks for: a
 * user-facing explanation kept **distinct from the internal trace**.
 *
 * Merging them is not a tidy-up, it is a leak. The trace carries prompts, tool
 * names, model identifiers and raw tool output; the explanation is a sentence
 * for somebody deciding whether to trust the answer. A stream that shows both
 * to the operator has published the first one.
 */

import { describe, it, expect } from 'vitest';

import { describePanel, PANEL_ROLE } from '../hub/panelSchema';
import { STRATEGIES, geometryFor } from '../hub/layoutStrategy';
import { CognitiveStream } from '../hub/cognitiveStream';

// ── schema-driven panels ─────────────────────────────────────────────────────

describe('panel schema', () => {
  it('turns a request into a descriptor nobody hand-wrote', () => {
    const panel = describePanel({
      kind: 'chart',
      intent: 'gold this session',
      data: { series: [1, 2, 3], unit: 'USD' },
    });
    expect(panel.renderable).toBe(true);
    expect(panel.kind).toBe('chart');
    expect(panel.fields.map((f) => f.name)).toContain('series');
  });

  it('gives every generated panel a real label, derived from the intent', () => {
    const panel = describePanel({ kind: 'table', intent: 'open positions', data: { rows: [] } });
    expect(panel.a11y.label).toMatch(/open positions/i);
    expect(panel.a11y.role).toBe(PANEL_ROLE.table);
  });

  it('refuses to generate a panel it cannot label', () => {
    // A generated panel with no label is how a screen reader ends up announcing
    // "region" forty times.
    expect(() => describePanel({ kind: 'chart', intent: '   ', data: { series: [1] } })).toThrow(/intent|label/i);
  });

  it('marks a chart with no series unrenderable, with the reason', () => {
    // An empty frame looks like a loading state for ever.
    const panel = describePanel({ kind: 'chart', intent: 'gold', data: {} });
    expect(panel.renderable).toBe(false);
    expect(panel.reason).toMatch(/series/i);
    expect(panel.fields).toEqual([]);
  });

  it('marks a table with no rows renderable, because an empty table is a real answer', () => {
    // "No open positions" is information. "No chart series" is a missing input.
    const panel = describePanel({ kind: 'table', intent: 'open positions', data: { rows: [] } });
    expect(panel.renderable).toBe(true);
    expect(panel.emptyMessage).toMatch(/no open positions|nothing/i);
  });

  it('refuses a kind it has no schema for rather than rendering a blank', () => {
    const panel = describePanel({ kind: 'simulation', intent: 'monte carlo', data: {} });
    expect(panel.renderable).toBe(false);
    expect(panel.reason).toMatch(/no schema|not described/i);
  });

  it('never invents a field the data does not carry', () => {
    const panel = describePanel({ kind: 'table', intent: 'positions', data: { rows: [{ a: 1 }] } });
    expect(panel.fields.every((f) => f.present)).toBe(true);
  });

  it('describes reduced motion as a property of the panel, not of the renderer', () => {
    const still = describePanel({ kind: 'chart', intent: 'gold', data: { series: [1] } }, { reducedMotion: true });
    expect(still.a11y.animated).toBe(false);
    const moving = describePanel({ kind: 'chart', intent: 'gold', data: { series: [1] } });
    expect(moving.a11y.animated).toBe(true);
  });

  it('carries a text alternative for every panel that is not text', () => {
    // §27: the drawing is never the only channel.
    const panel = describePanel({ kind: 'chart', intent: 'gold this session', data: { series: [1, 2] } });
    expect(panel.a11y.description.length).toBeGreaterThan(0);
  });
});

// ── the second layout geometry ───────────────────────────────────────────────

const SURFACES = [
  { id: 'a', span: 6, priority: 'primary' },
  { id: 'b', span: 6, priority: 'secondary' },
  { id: 'c', span: 12, priority: 'background' },
];

describe('layout strategy', () => {
  it('offers more than one geometry', () => {
    expect(STRATEGIES.length).toBeGreaterThan(1);
    expect(STRATEGIES).toContain('grid');
    expect(STRATEGIES).toContain('stack');
  });

  it('grid keeps the span the layout engine decided', () => {
    const geometry = geometryFor(SURFACES, { strategy: 'grid' });
    expect(geometry.map((g) => g.span)).toEqual([6, 6, 12]);
    expect(geometry.every((g) => g.strategy === 'grid')).toBe(true);
  });

  it('stack gives every surface the full width, in order', () => {
    const geometry = geometryFor(SURFACES, { strategy: 'stack' });
    expect(geometry.map((g) => g.span)).toEqual([12, 12, 12]);
    expect(geometry.map((g) => g.order)).toEqual([0, 1, 2]);
  });

  it('chooses stack on a narrow viewport without being told', () => {
    const geometry = geometryFor(SURFACES, { viewport: { width: 420 } });
    expect(geometry.every((g) => g.strategy === 'stack')).toBe(true);
  });

  it('chooses grid on a wide viewport', () => {
    const geometry = geometryFor(SURFACES, { viewport: { width: 1440 } });
    expect(geometry.every((g) => g.strategy === 'grid')).toBe(true);
  });

  it('an explicit strategy beats the viewport, and says it was forced', () => {
    const geometry = geometryFor(SURFACES, { strategy: 'grid', viewport: { width: 420 } });
    expect(geometry[0]?.strategy).toBe('grid');
    expect(geometry[0]?.forced).toBe(true);
  });

  it('refuses a strategy it does not have rather than falling back silently', () => {
    expect(() => geometryFor(SURFACES, { strategy: 'isometric' as never })).toThrow(/isometric/);
  });

  it('does not change what place() decided about span in grid', () => {
    // place() is the content-independent half and 2,231 tests depend on it.
    // The strategy layer adds geometry; it does not re-decide importance.
    const geometry = geometryFor(SURFACES, { strategy: 'grid' });
    expect(geometry.map((g) => g.span)).toEqual(SURFACES.map((s) => s.span));
  });

  it('reports an empty plane as empty rather than as one blank row', () => {
    expect(geometryFor([], { strategy: 'stack' })).toEqual([]);
  });
});

// ── the cognitive stream ─────────────────────────────────────────────────────

describe('cognitive stream', () => {
  it('keeps the explanation and the trace in separate lists', () => {
    const stream = new CognitiveStream();
    stream.step({ say: 'Checking the last four hours of gold prices.', trace: 'tool=read_prices args={"h":4}' });

    expect(stream.explanation()).toEqual(['Checking the last four hours of gold prices.']);
    expect(stream.trace()).toEqual(['tool=read_prices args={"h":4}']);
  });

  it('never puts a trace line into the explanation', () => {
    // Merging them is not a tidy-up, it is a leak: the trace carries prompts,
    // tool names and raw tool output.
    const stream = new CognitiveStream();
    stream.step({ say: 'Reading the risk limits.', trace: 'PROMPT: you are HOPEFX... KEY=sk-live-abc' });
    expect(stream.explanation().join(' ')).not.toContain('sk-live-abc');
    expect(stream.explanation().join(' ')).not.toContain('PROMPT');
  });

  it('says it is working rather than leaking the trace when there is nothing to say', () => {
    const stream = new CognitiveStream();
    stream.step({ trace: 'tool=internal_reindex' });
    expect(stream.explanation()).toEqual(['Working.']);
    expect(stream.explanation().join(' ')).not.toContain('internal_reindex');
  });

  it('refuses a step that is neither said nor traced', () => {
    const stream = new CognitiveStream();
    expect(() => stream.step({})).toThrow(/nothing/i);
  });

  it('keeps the trace even when the operator never sees it', () => {
    // The trace is for the audit, not for the screen. Dropping it because
    // nobody is looking is how an incident becomes unreconstructable.
    const stream = new CognitiveStream();
    stream.step({ say: 'Working.', trace: 'tool=x' });
    expect(stream.trace()).toHaveLength(1);
  });

  it('bounds both lists, so a long run is not a memory leak', () => {
    const stream = new CognitiveStream({ limit: 3 });
    for (let n = 0; n < 10; n += 1) stream.step({ say: `step ${n}`, trace: `t${n}` });
    expect(stream.explanation()).toHaveLength(3);
    expect(stream.trace()).toHaveLength(3);
    expect(stream.explanation()[2]).toBe('step 9');
  });

  it('reports how much it dropped rather than pretending it kept everything', () => {
    const stream = new CognitiveStream({ limit: 2 });
    for (let n = 0; n < 5; n += 1) stream.step({ say: `s${n}`, trace: `t${n}` });
    expect(stream.dropped()).toBe(3);
  });

  it('renders for the operator without the trace being reachable from the result', () => {
    const stream = new CognitiveStream();
    stream.step({ say: 'Reading positions.', trace: 'secret-internal-detail' });
    expect(JSON.stringify(stream.forOperator())).not.toContain('secret-internal-detail');
  });
});

// ── the registry ─────────────────────────────────────────────────────────────

describe('§23 is closed', () => {
  it('every generated panel role is one a screen reader can use', () => {
    // A role of "region" for everything is the same as no role: it tells the
    // user something is there and nothing about what.
    const usable = new Set(['img', 'table', 'article', 'feed', 'code', 'log', 'region']);
    for (const role of Object.values(PANEL_ROLE)) {
      expect(usable.has(role as string)).toBe(true);
    }
  });

  it('no panel kind claims a role it cannot honour', () => {
    // `table` role on something with no rows field would announce a table
    // structure that is not there.
    const table = describePanel({ kind: 'table', intent: 'positions', data: { rows: [] } });
    expect(table.a11y.role).toBe('table');
    const chart = describePanel({ kind: 'chart', intent: 'gold', data: { series: [1] } });
    expect(chart.a11y.role).toBe('img');
  });
});
