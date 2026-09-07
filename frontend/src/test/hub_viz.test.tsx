/**
 * §21: heatmaps for intensity, network graphs for relationships, timelines for
 * chronology, media panels, and interactive drill-down.
 *
 * ## The palette is computed, and these tests hold it to that
 *
 * The colours in `hub/vizPalette.ts` were produced by running the data-viz
 * validator against this workspace's real composited surface (`#0f1a2a`), not
 * by eye. Two findings shaped the design and are asserted here so a later
 * "let's add a fourth category" has something to fail against:
 *
 *   · three categorical hues is the ceiling — every candidate fourth measured a
 *     normal-vision ΔE below 15, meaning full-colour readers cannot reliably
 *     tell the pair apart, which no amount of labelling excuses;
 *   · the intensity ramp is five steps, because seven put adjacent steps ΔL
 *     0.047 apart — below the 0.06 floor, the measured version of "these two
 *     cells look the same".
 *
 * Fails on the pre-fix tree — `hub/VizMarks.tsx` does not exist there.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { CATEGORY, INTENSITY, OTHER, categoryColour, intensityStep } from '../hub/vizPalette';
import { Heatmap, NetworkGraph, Timeline } from '../hub/VizMarks';
import type { Cell, Edge, Event, Node } from '../hub/surfaceData';

const CELLS: Cell[] = [
  { row: 'Movement', column: 'T1', intensity: 0.1, label: '0.40 peak move' },
  { row: 'Movement', column: 'T2', intensity: 0.9, label: '3.60 peak move' },
];

const NODES: Node[] = [
  { id: 'a', label: 'XAUUSD', category: 'Position' },
  { id: 'b', label: 'Risk limits', category: 'Risk' },
];
const EDGES: Edge[] = [{ from: 'a', to: 'b', because: 'those limits govern this position' }];

const EVENTS: Event[] = [
  { at: Date.parse('2026-03-10T09:00:00Z'), label: 'CPI print', category: 'bearish' },
  { at: Date.parse('2026-03-10T13:00:00Z'), label: 'Fed speaker', category: 'neutral' },
];

describe('the palette holds the shape the validator produced', () => {
  it('offers exactly three categorical hues', () => {
    // Every candidate fourth failed the normal-vision floor on this surface:
    // yellow ΔE 10.6, violet 9.8, magenta 11.6, all below 15.
    expect(CATEGORY).toHaveLength(3);
  });

  it('folds a fourth category into a neutral rather than inventing a hue', () => {
    // A colour that cannot be told from another colour is worse than an honest
    // "not one of the named three", because the reader believes the first one.
    expect(categoryColour(0)).toBe(CATEGORY[0]);
    expect(categoryColour(2)).toBe(CATEGORY[2]);
    expect(categoryColour(3)).toBe(OTHER);
    expect(categoryColour(99)).toBe(OTHER);
  });

  it('keeps the intensity ramp to five steps', () => {
    expect(INTENSITY).toHaveLength(5);
  });

  it('maps the whole 0-1 range onto the ramp without running off either end', () => {
    expect(intensityStep(0)).toBe(INTENSITY[0]);
    expect(intensityStep(1)).toBe(INTENSITY[INTENSITY.length - 1]);
    expect(intensityStep(1.4)).toBe(INTENSITY[INTENSITY.length - 1]);
    expect(intensityStep(-3)).toBe(INTENSITY[0]);
  });

  it('does not colour an unmeasured value', () => {
    // NaN is "nobody measured this". Painting it the lowest step would draw it
    // as the quietest cell on the grid.
    expect(INTENSITY).not.toContain(intensityStep(Number.NaN));
  });

  it('reuses no status colour as a category', () => {
    // A status colour meaning "halted" reused as "series 3" is a chart that can
    // say the wrong thing.
    for (const status of ['#42d392', '#f5b84b', '#f36d78']) {
      expect(CATEGORY as readonly string[]).not.toContain(status);
    }
  });
});

describe('the heatmap', () => {
  it('draws a cell per bucket, each reachable and described', () => {
    render(<Heatmap cells={CELLS} />);
    expect(screen.getByLabelText(/T1, Movement: 0\.40 peak move/)).toBeTruthy();
    expect(screen.getByLabelText(/T2, Movement: 3\.60 peak move/)).toBeTruthy();
  });

  it('draws a busier bucket differently from a quiet one', () => {
    render(<Heatmap cells={CELLS} />);
    const quiet = screen.getByLabelText(/T1/).style.background;
    const busy = screen.getByLabelText(/T2/).style.background;
    expect(quiet).not.toBe(busy);
  });

  it('gives every cell a hit target of at least 24 pixels', () => {
    // A cell you have to land on dead-centre is a cell nobody uses.
    render(<Heatmap cells={CELLS} />);
    expect(Number.parseFloat(screen.getByLabelText(/T1/).style.height)).toBeGreaterThanOrEqual(24);
  });

  it('shows the same thing on keyboard focus as on hover', () => {
    render(<Heatmap cells={CELLS} />);
    const cell = screen.getByLabelText(/T2/);
    fireEvent.focus(cell);
    expect(screen.getByText('3.60 peak move')).toBeTruthy();
  });

  it('drills into the cell that was clicked, named after that cell', () => {
    const onDrill = vi.fn();
    render(<Heatmap cells={CELLS} onDrill={onDrill} />);
    fireEvent.click(screen.getByLabelText(/T2/));
    expect(onDrill).toHaveBeenCalledWith(expect.stringContaining('3.60'));
  });
});

describe('the network graph', () => {
  it('names every category in text, not only in colour', () => {
    render(<NetworkGraph nodes={NODES} edges={EDGES} />);
    expect(screen.getByText('Position')).toBeTruthy();
    expect(screen.getByText('Risk')).toBeTruthy();
  });

  it('says why two things are connected', () => {
    // An edge with no stated reason is a claim the reader cannot check.
    const { container } = render(<NetworkGraph nodes={NODES} edges={EDGES} />);
    expect(container.querySelector('line title')?.textContent).toMatch(/govern this position/);
  });

  it('places the same graph the same way twice', () => {
    // A force layout settles differently on every render, so "the one on the
    // left" stops meaning anything a minute later.
    const first = render(<NetworkGraph nodes={NODES} edges={EDGES} />).container.innerHTML;
    const second = render(<NetworkGraph nodes={NODES} edges={EDGES} />).container.innerHTML;
    expect(first).toBe(second);
  });

  it('does not repaint the survivors when a node is removed', () => {
    // Colour follows the entity, never its rank.
    const { container: withBoth } = render(<NetworkGraph nodes={NODES} edges={EDGES} />);
    const positionFill = withBoth.querySelector('circle')?.getAttribute('fill');

    const { container: withOne } = render(
      <NetworkGraph nodes={[NODES[0]!, { id: 'c', label: 'DXY', category: 'Position' }]} edges={[]} />,
    );
    expect(withOne.querySelector('circle')?.getAttribute('fill')).toBe(positionFill);
  });

  it('drills into a node by its own name', () => {
    const onDrill = vi.fn();
    const { container } = render(<NetworkGraph nodes={NODES} edges={EDGES} onDrill={onDrill} />);
    fireEvent.click(container.querySelectorAll('circle')[0]!);
    expect(onDrill).toHaveBeenCalledWith('XAUUSD');
  });

  it('shows no legend box for a single category', () => {
    render(<NetworkGraph nodes={[NODES[0]!]} edges={[]} />);
    expect(screen.queryByText('Risk')).toBeNull();
  });
});

describe('the timeline', () => {
  it('places events in order across the span', () => {
    render(<Timeline events={EVENTS} />);
    const marks = screen.getAllByRole('button');
    expect(Number.parseFloat(marks[0]!.style.left)).toBeLessThan(Number.parseFloat(marks[1]!.style.left));
  });

  it('labels each event with its time and what it was', () => {
    render(<Timeline events={EVENTS} />);
    expect(screen.getByLabelText(/CPI print/)).toBeTruthy();
  });

  it('gives every event a hit target of at least 24 pixels', () => {
    render(<Timeline events={EVENTS} />);
    expect(Number.parseFloat(screen.getAllByRole('button')[0]!.style.width)).toBeGreaterThanOrEqual(24);
  });

  it('drills into an event', () => {
    const onDrill = vi.fn();
    render(<Timeline events={EVENTS} onDrill={onDrill} />);
    fireEvent.click(screen.getByLabelText(/Fed speaker/));
    expect(onDrill).toHaveBeenCalledWith('Fed speaker');
  });

  it('survives every event sharing one timestamp', () => {
    // A zero span divides by zero and puts every mark at NaN%.
    const same = Date.parse('2026-03-10T09:00:00Z');
    render(
      <Timeline events={[{ at: same, label: 'A', category: 'x' }, { at: same, label: 'B', category: 'x' }]} />,
    );
    for (const mark of screen.getAllByRole('button')) {
      expect(mark.style.left).not.toContain('NaN');
    }
  });
});

describe('the accessible twin', () => {
  it('is reachable from a panel that encodes in colour', async () => {
    const { SurfaceView } = await import('../hub/SurfaceView');
    const { Workspace } = await import('../hub/workspace');
    const ws = new Workspace();
    ws.open({ kind: 'heatmap', intent: 'Session movement', priority: 'primary', key: 'session-heatmap' });
    const surface = ws.surfaces[0]!;

    render(<SurfaceView surface={surface} focused={false} onClose={() => {}} onPin={() => {}} />);
    const toggle = screen.getByLabelText(/as a table/i);
    expect(toggle).toBeTruthy();
    fireEvent.click(toggle);
    expect(screen.getByLabelText(/as a chart/i)).toBeTruthy();
  });

  it('is absent from a panel with no colour-only encoding', async () => {
    const { SurfaceView } = await import('../hub/SurfaceView');
    const { Workspace } = await import('../hub/workspace');
    const ws = new Workspace();
    ws.open({ kind: 'table', intent: 'Open positions', priority: 'primary', key: 'positions' });

    render(<SurfaceView surface={ws.surfaces[0]!} focused={false} onClose={() => {}} onPin={() => {}} />);
    expect(screen.queryByLabelText(/as a table/i)).toBeNull();
  });
});

describe('media panels', () => {
  it('cannot be built without a description', async () => {
    // `alt` is a required field on the data rather than an optional prop: a
    // panel nobody can describe is one nobody can read aloud.
    const { Media } = await import('../hub/VizMarks');
    const { container } = render(<Media media={{ src: 'x.png', alt: 'A chart of gold', kind: 'image' }} />);
    expect(within(container).getByAltText('A chart of gold')).toBeTruthy();
  });

  it('renders video with controls rather than autoplaying', async () => {
    const { Media } = await import('../hub/VizMarks');
    const { container } = render(<Media media={{ src: 'x.mp4', alt: 'Replay', kind: 'video' }} />);
    const video = container.querySelector('video');
    expect(video?.hasAttribute('controls')).toBe(true);
    expect(video?.hasAttribute('autoplay')).toBe(false);
  });
});

// ── they have to be reachable, or they are renderers nobody can open ──────────

describe('summoning them', () => {
  it('opens a heatmap for the question, not for the chart type', async () => {
    // Somebody asks "where was the movement", not "render a heatmap".
    const { readIntent } = await import('../hub/intent');
    for (const phrase of ['where was the movement', 'show me the heatmap', 'when was it busiest']) {
      expect(readIntent(phrase).open.map((r) => r.kind)).toContain('heatmap');
    }
  });

  it('opens a network graph for a relationship question', async () => {
    const { readIntent } = await import('../hub/intent');
    for (const phrase of ['show me the connections', 'show me the network']) {
      expect(readIntent(phrase).open.map((r) => r.kind)).toContain('network');
    }
  });

  it('opens a timeline for a chronology question', async () => {
    const { readIntent } = await import('../hub/intent');
    for (const phrase of ['show me the timeline', 'what happened when']) {
      expect(readIntent(phrase).open.map((r) => r.kind)).toContain('timeline');
    }
  });

  it('opens keys the data layer actually binds', async () => {
    // A surface whose key no `surfaceData` case matches renders the default
    // "nothing is connected to this yet" note — the renderer would be built,
    // reachable, and permanently empty.
    const { readIntent } = await import('../hub/intent');
    const keys = ['where was the movement', 'show me the connections', 'show me the timeline'].flatMap(
      (p) => readIntent(p).open.map((r) => r.key),
    );
    expect(keys).toEqual(['session-heatmap', 'relationships', 'chronology']);
  });

  it('does not fire on an ordinary question', async () => {
    const { readIntent } = await import('../hub/intent');
    for (const phrase of ['show me gold', 'what is the risk']) {
      const kinds = readIntent(phrase).open.map((r) => r.kind);
      expect(kinds).not.toContain('heatmap');
      expect(kinds).not.toContain('network');
      expect(kinds).not.toContain('timeline');
    }
  });
});

describe('what the panels say when there is nothing to draw', () => {
  it('does not draw a grid of zeros for an unmeasured session', async () => {
    // A heatmap of one reading reads as a calm session rather than an
    // unmeasured one, and those are opposite facts.
    const { useStore } = await import('../store');
    const { surfaceData } = await import('../hub/surfaceData');
    useStore.setState({ priceHistory: { 'XAU/USD': [2000] } } as never);
    const data = surfaceData({ kind: 'heatmap', key: 'session-heatmap' });
    expect(data.empty).toBe(true);
    expect(data.note).toMatch(/grid of zeros/i);
  });

  it('distinguishes a quiet feed from headlines that carry no timestamp', async () => {
    const { useStore } = await import('../store');
    const { surfaceData } = await import('../hub/surfaceData');

    useStore.setState({ newsItems: [] } as never);
    expect(surfaceData({ kind: 'timeline', key: 'chronology' }).note).toMatch(/nothing timestamped/i);

    useStore.setState({ newsItems: [{ title: 'A headline', published_at: null }] } as never);
    const untimed = surfaceData({ kind: 'timeline', key: 'chronology' });
    expect(untimed.empty).toBe(true);
    expect(untimed.note).toMatch(/none carries a timestamp/i);
  });

  it('builds the relationship graph from declared edges, not from a guess', async () => {
    const { useStore } = await import('../store');
    const { surfaceData } = await import('../hub/surfaceData');
    useStore.setState({
      positions: [{ id: '1', symbol: 'XAUUSD', side: 'buy', size: 1, unrealized_pnl: 4 }],
      newsItems: [],
    } as never);
    const data = surfaceData({ kind: 'network', key: 'relationships' });
    expect(data.nodes?.map((n) => n.label)).toContain('XAUUSD');
    // Every edge states why, because an edge with no reason is a claim the
    // reader cannot check.
    expect(data.edges?.every((e) => e.because.length > 10)).toBe(true);
  });
});

// ── the pre-delivery checklist, as assertions ────────────────────────────────

describe('the accessibility rules these renderers have to keep', () => {
  it('does not remove the browser focus ring from any mark', () => {
    // The first version set `outline: none` and drew its own ring from the same
    // state as hover. That looks equivalent and is not: it vanishes the moment
    // that state handling changes, and it never existed for a reader whose
    // browser ring is the only thing they rely on.
    //
    // Asserted on the rendered element rather than on the source text, which is
    // what the first version of this test did — and it failed on the sentence
    // above, because a comment explaining the rule is not a violation of it.
    const heat = render(<Heatmap cells={CELLS} />);
    expect(heat.getByLabelText(/T1/).style.outline).toBe('');

    const net = render(<NetworkGraph nodes={NODES} edges={EDGES} />);
    expect((net.container.querySelector('circle') as SVGElement).style.outline).toBe('');

    const time = render(<Timeline events={EVENTS} />);
    expect(time.container.querySelectorAll('button')[0]!.style.outline).toBe('');
  });

  it('keeps every text colour above the 4.5:1 floor on the real surface', async () => {
    const { INK, VIZ_SURFACE } = await import('../hub/vizPalette');
    const lin = (c: number) => {
      const v = c / 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    };
    const luminance = (hex: string) =>
      0.2126 * lin(parseInt(hex.slice(1, 3), 16)) +
      0.7152 * lin(parseInt(hex.slice(3, 5), 16)) +
      0.0722 * lin(parseInt(hex.slice(5, 7), 16));
    const ratio = (a: string, b: string) => {
      const [l1, l2] = [luminance(a), luminance(b)];
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    };

    for (const [role, hex] of Object.entries(INK)) {
      expect(ratio(hex, VIZ_SURFACE), `${role} ${hex}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('removes motion rather than shortening it under prefers-reduced-motion', async () => {
    const { matchMedia } = window;
    // Reduced motion ON: the declaration is the word `none`, not a short duration.
    // A 1ms transition is still a transition.
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: () => ({ matches: true, addEventListener() {}, removeEventListener() {} }),
    });
    const still = render(<Heatmap cells={CELLS} />);
    expect(still.getByLabelText(/T1/).style.transition).toBe('none');

    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    });
    const moving = render(<Heatmap cells={CELLS} />);
    const marks = moving.getAllByLabelText(/T1/);
    const declaration = marks[marks.length - 1]!.style.transition;
    expect(declaration).not.toBe('none');
    for (const match of declaration.matchAll(/(\d+)ms/g)) {
      const ms = Number(match[1]);
      expect(ms).toBeGreaterThanOrEqual(150);
      expect(ms).toBeLessThanOrEqual(300);
    }
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: matchMedia });
  });

  it('gives every clickable mark a pointer cursor', async () => {
    render(<Heatmap cells={CELLS} />);
    expect(screen.getByLabelText(/T1/).style.cursor).toBe('pointer');
  });
});
