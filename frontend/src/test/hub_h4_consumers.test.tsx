/**
 * Phase H4 — the three rows whose notes said, in my own words, that nothing
 * consumed them.
 *
 * `a11y.high_contrast`: "NOTHING RENDERS IT YET — no component asks for the
 * high palette." `a11y.touch_and_mouse`: "NO COMPONENT CALLS IT YET."
 * `workspace.surface_types`: six of §8's twelve kinds do not render.
 *
 * Staging them rather than claiming them was right — a contract whose evidence
 * resolves and whose behaviour never runs is F176 with a passing test. But a
 * refusal recorded twice and never acted on is just a slower version of the
 * same omission, so this phase is the consumers.
 *
 * ## What is deliberately still not built
 *
 * `map` and `simulation`. There is no tile source in this deployment and no
 * simulator behind a simulation panel, and a map drawn from nothing is worse
 * than a panel that says it cannot draw one — an operator reads a rendered map
 * as a map. Those two keep the honest note, and a test below asserts they keep
 * it rather than letting the set drift.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { surfaceData } from '../hub/surfaceData';
import { RENDERED_KINDS, UNRENDERED_KINDS } from '../hub/SurfaceView';
import { CONTRAST_MODES, contrastRatio, surfacePalette, SURFACES } from '../hub/a11yContrast';
import { readContrastMode } from '../hub/useContrastMode';

function stubMatchMedia(matching: readonly string[] = []): void {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: matching.some((m) => query.includes(m)),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

beforeEach(() => {
  localStorage.clear();
  stubMatchMedia();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('§8 a surface the AI opens with content actually shows it', () => {
  it('passes caller-supplied body through for a kind with no built-in feed', () => {
    // The defect: the `default` branch discarded `data` entirely, so an AI
    // opening a document surface WITH the document in it got "nothing is
    // connected to a document surface yet". The panel was real, the content
    // was supplied, and the screen said neither had happened.
    const out = surfaceData({ kind: 'document', key: 'brief-2026-09', data: { body: 'The gold thesis.' } });
    expect(out.empty).toBe(false);
    expect(out.body).toBe('The gold thesis.');
  });

  it('still says so when a kind has no feed and no supplied content', () => {
    const out = surfaceData({ kind: 'document', key: 'nothing-here', data: {} });
    expect(out.empty).toBe(true);
    expect(out.note).toMatch(/not connected|nothing is connected/i);
  });

  it('accepts rows and items too, not only a body', () => {
    const rows = surfaceData({ kind: 'research', key: 'r', data: { rows: [['a', 'b']] } });
    expect(rows.empty).toBe(false);
    expect(rows.rows).toEqual([['a', 'b']]);

    const items = surfaceData({ kind: 'research', key: 'r2', data: { items: ['one', 'two'] } });
    expect(items.empty).toBe(false);
    expect(items.items).toEqual(['one', 'two']);
  });

  it('refuses content of the wrong shape rather than rendering a cast', () => {
    // `data` comes from a model. A string where rows belong would reach a
    // renderer that maps over it, and a crash inside a panel takes the plane
    // down with it.
    const out = surfaceData({ kind: 'document', key: 'x', data: { rows: 'not rows' } });
    expect(out.empty).toBe(true);
  });

  it('renders document, code and research, which are text and always could', () => {
    for (const kind of ['document', 'code', 'research']) {
      expect(RENDERED_KINDS).toContain(kind);
    }
  });

  it('renders a camera surface as its consent state, not as "cannot draw"', () => {
    // §25 already decides whether a camera may be used. A panel that said the
    // deployment cannot draw a camera was describing a missing renderer while
    // the actual answer — consent has not been given — was already known.
    expect(RENDERED_KINDS).toContain('camera');
  });

  it('keeps map and simulation honestly unrendered', () => {
    // Not an oversight, and asserted so it cannot become one by drift. A map
    // drawn without a tile source is read as a map.
    expect([...UNRENDERED_KINDS].sort()).toEqual(['map', 'simulation']);
  });

  it('has no kind that is both rendered and declared unrendered', () => {
    for (const kind of UNRENDERED_KINDS) expect(RENDERED_KINDS).not.toContain(kind);
  });
});

describe('§27 high contrast has a consumer', () => {
  it('reads the operator preference from the media queries that carry it', () => {
    stubMatchMedia(['prefers-contrast: more']);
    expect(readContrastMode()).toBe('high');

    stubMatchMedia(['forced-colors: active']);
    expect(readContrastMode()).toBe('high');

    stubMatchMedia([]);
    expect(readContrastMode()).toBe('standard');
  });

  it('falls back to standard when the query cannot be read', () => {
    vi.stubGlobal('matchMedia', undefined);
    expect(readContrastMode()).toBe('standard');
  });

  it('gives the panel a full palette per mode, not only body text', () => {
    // A high-contrast mode that raised the body text and left the semantic
    // colours alone would be a screen where the words are readable and the
    // warnings are not.
    for (const mode of CONTRAST_MODES) {
      const palette = surfacePalette(mode);
      for (const role of ['text', 'dim', 'quiet', 'core', 'ok', 'warn', 'bad'] as const) {
        expect(palette[role], `${mode} palette has no ${role}`).toBeTruthy();
      }
    }
  });

  it('actually raises the measured contrast in high mode', () => {
    // The claim the row makes. Measured, not asserted — the same discipline
    // the palette itself is held to.
    const standard = surfacePalette('standard');
    const high = surfacePalette('high');
    for (const role of ['dim', 'quiet'] as const) {
      const before = contrastRatio(standard[role], SURFACES.panel);
      const after = contrastRatio(high[role], SURFACES.panel);
      expect(after, `${role}: ${after.toFixed(2)} is not above ${before.toFixed(2)}`).toBeGreaterThan(before);
      expect(after).toBeGreaterThanOrEqual(7);
    }
  });

  it('drives the rendered panel, not just a palette object', async () => {
    stubMatchMedia(['prefers-contrast: more']);
    const { SurfaceView } = await import('../hub/SurfaceView');
    render(
      <SurfaceView
        surface={{
          id: 's1',
          kind: 'document',
          meaning: 'A brief',
          priority: 'primary',
          span: 6,
          pinned: false,
          key: 'brief',
          openedAt: 1,
          order: 0,
          data: { body: 'Readable text.' },
        }}
        focused={false}
        onClose={vi.fn()}
        onPin={vi.fn()}
      />,
    );
    const panel = document.querySelector('[data-surface-id="s1"]') as HTMLElement;
    expect(panel).not.toBeNull();
    // The panel says which mode it is in, so a screenshot and a bug report can
    // agree about what was on screen.
    expect(panel.getAttribute('data-contrast')).toBe('high');
    // And it PAINTS it. The attribute alone only proves the query was read —
    // pinning the palette to standard while still reporting "high" passed this
    // test until the custom properties were asserted too, which is the
    // measured-versus-told distinction the whole registry is built on.
    const high = surfacePalette('high');
    expect(panel.style.getPropertyValue('--panel-quiet')).toBe(high.quiet);
    expect(panel.style.getPropertyValue('--panel-dim')).toBe(high.dim);
    expect(panel.style.getPropertyValue('--panel-bad')).toBe(high.bad);
  });
});

describe('§27 touch and mouse has a consumer', () => {
  /**
   * A heatmap surface. Its marks carry their meaning in a readout below the
   * grid, opened by hover or keyboard focus — neither of which a tablet
   * operator has.
   */
  const heatmapSurface = {
    id: 'h1',
    kind: 'heatmap' as const,
    meaning: 'Session movement',
    priority: 'secondary' as const,
    span: 6,
    pinned: false,
    // A key surfaceData has no case for, so the cells below are the ones
    // rendered — the store-backed 'session-heatmap' key would ignore them.
    key: 'ad-hoc-heatmap',
    openedAt: 1,
    order: 0,
    data: {
      cells: [
        { row: 'Mon', column: 'London', intensity: 0.8, label: '0.8% peak move' },
        { row: 'Mon', column: 'NY', intensity: 0.2, label: '0.2% peak move' },
      ],
    },
  };

  async function renderHeatmap() {
    const { SurfaceView } = await import('../hub/SurfaceView');
    return render(<SurfaceView surface={heatmapSurface} focused={false} onClose={vi.fn()} onPin={vi.fn()} />);
  }

  it('records the affordance the pointer in use requires', async () => {
    // The policy, observable. `unknown` before any pointer is seen, because
    // guessing mouse is how a hover-only affordance ships — the guess is
    // invisible and the people it fails are the ones least able to work round
    // it. A desktop operator loses nothing by it.
    await renderHeatmap();
    const marks = document.querySelectorAll('[data-mark-label]');
    expect(marks.length).toBeGreaterThan(0);
    expect((marks[0] as HTMLElement).getAttribute('data-affordance')).toBe('always');

    fireEvent.pointerDown(marks[0]!, { pointerType: 'mouse' });
    expect(
      (document.querySelectorAll('[data-mark-label]')[0] as HTMLElement).getAttribute('data-affordance'),
    ).toBe('on-hover');
  });

  it('treats an unreadable pointer as unable to hover', async () => {
    await renderHeatmap();
    const marks = document.querySelectorAll('[data-mark-label]');
    // No pointerType — a synthetic event, an older WebKit, some assistive
    // technology driving the page.
    fireEvent.pointerDown(marks[0]!, {});
    expect(
      (document.querySelectorAll('[data-mark-label]')[0] as HTMLElement).getAttribute('data-affordance'),
    ).toBe('always');
  });

  it('opens the readout on a tap, which is the whole point', async () => {
    // The real defect, and the one an attribute alone would not have caught:
    // `mouseenter` does not fire on touch and iOS Safari does not reliably
    // focus a button on tap, so the readout — the accessible twin this file
    // already ships — was reachable by mouse and keyboard and by nothing a
    // tablet operator could do.
    await renderHeatmap();
    const marks = document.querySelectorAll('[data-mark-label]');
    expect(screen.queryByText(/0\.8% peak move/)).toBeNull();
    fireEvent.pointerDown(marks[0]!, { pointerType: 'touch' });
    expect(screen.getByText(/0\.8% peak move/)).toBeTruthy();
  });
});
