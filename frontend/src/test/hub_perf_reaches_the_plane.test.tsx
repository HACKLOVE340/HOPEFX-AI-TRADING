/**
 * §26 driven through the real plane.
 *
 * Both rows were `planned`, and both deciders already existed:
 * `virtualization.ts:windowFor` since Phase D1, `frameBudget.ts:nextFidelity`
 * since Phase D1. Measured before this phase, each was called from exactly
 * zero components. A decider nobody asks is `hopefx-dead-controls` with a unit
 * test attached — and both had passing unit tests.
 *
 * So the assertions here are about the document: how many nodes a five
 * thousand row table puts on the plane, and whether a plane told the machine
 * is struggling says so where somebody can read it.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { PresenceStage } from '../hub/PresenceStage';
import { VIRTUALIZE_ABOVE } from '../hub/VirtualList';
import type { Presence } from '../hub/presence';
import type { Surface } from '../hub/workspace';

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({
    speak: vi.fn(),
    cancelSpeak: vi.fn(),
    startListening: vi.fn(),
    stopListening: vi.fn(),
    speaking: false,
    listening: false,
    sttSupported: false,
    transcript: '',
    status: null,
    spokenText: '',
    speechProgress: null,
  }),
}));

const presence: Presence = {
  state: 'idle',
  tone: 'ok',
  reason: 'Nothing needs attention.',
  intensity: 0.2,
  headroomKnown: true,
};

/**
 * The real data path, not a hand-fed one.
 *
 * `SurfaceView` renders from `surfaceData(...)`, which builds a table's rows
 * from the store — a surface carrying rows in its own `data` renders the
 * "nothing connected yet" note instead. Seeding the store is what a five
 * thousand row table actually looks like in this app.
 */
async function seedPositions(count: number): Promise<void> {
  const { useStore } = await import('../store');
  useStore.setState({
    positions: Array.from({ length: count }, (_, i) => ({
      symbol: 'XAUUSD',
      side: i % 2 === 0 ? 'buy' : 'sell',
      size: 0.01 * (i + 1),
      unrealized_pnl: i - count / 2,
    })),
  } as never);
}

function tableSurface(): Surface {
  return {
    id: 'big-table',
    kind: 'table',
    meaning: 'Every open position',
    priority: 'primary',
    span: 12,
    pinned: false,
    key: 'positions',
    openedAt: 1_700_000_000_000,
    order: 0,
    data: {},
  };
}

function renderStage(surfaces: Surface[]) {
  return render(
    <PresenceStage
      presence={presence}
      surfaces={surfaces}
      focusedId={null}
      listening={false}
      muted={false}
      sttSupported={false}
      transcript={[]}
      layout="auto"
      onCommand={vi.fn()}
      onTalk={vi.fn()}
      onStop={vi.fn()}
      onToggleMute={vi.fn()}
      onCloseSurface={vi.fn()}
      onPinSurface={vi.fn()}
      onExit={vi.fn()}
    />,
  );
}

/** Rendered row nodes inside the table panel, however the panel chose to draw them. */
function renderedRowCount(): number {
  const panel = document.querySelector('[data-surface-id="big-table"]');
  if (!panel) return 0;
  const dl = panel.querySelectorAll('dl > div').length;
  const virtual = panel.querySelectorAll('[role="group"] > div > div > div').length;
  return dl + virtual;
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
  // jsdom has no matchMedia, and `usePrefersReducedMotion` correctly defaults
  // to "reduce" when it cannot read the query — which caps fidelity outright
  // and would make every assertion below pass without the load path running
  // at all. An operator who has expressed no preference is the case under test.
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('§26 large workspaces', () => {
  it('renders a short table whole, so nothing pays for a window it does not need', async () => {
    await seedPositions(10);
    renderStage([tableSurface()]);
    expect(renderedRowCount()).toBe(10);
    // No scroll container: virtualising ten rows breaks find-in-page and
    // copy-the-whole-table to save nothing.
    expect(document.querySelector('[data-surface-id="big-table"] [role="group"]')).toBeNull();
  });

  it('renders a window of a five thousand row table, not five thousand rows', async () => {
    await seedPositions(5000);
    renderStage([tableSurface()]);
    const drawn = renderedRowCount();
    expect(drawn).toBeGreaterThan(0);
    // The exact number depends on the measured viewport; the claim is that it
    // is a window. Before this phase it was 5000.
    expect(drawn).toBeLessThan(200);
  });

  it('tells a reader the list is longer than what is drawn', async () => {
    // A window is a lie by omission: fifty rows of five thousand look like
    // fifty rows. The scrollbar is not an indicator everybody has.
    await seedPositions(5000);
    renderStage([tableSurface()]);
    const group = document.querySelector('[data-surface-id="big-table"] [role="group"]');
    expect(group).not.toBeNull();
    expect(group!.getAttribute('aria-rowcount')).toBe('5000');
    expect(group!.textContent).toContain('5000 rows');
  });

  it('draws different rows after a scroll', async () => {
    await seedPositions(5000);
    renderStage([tableSurface()]);
    const group = document.querySelector('[data-surface-id="big-table"] [role="group"]') as HTMLElement;
    const before = group.textContent ?? '';
    fireEvent.scroll(group, { target: { scrollTop: 4000 } });
    expect(group.textContent).not.toBe(before);
  });

  it('switches at the declared threshold rather than at a number in the component', async () => {
    await seedPositions(VIRTUALIZE_ABOVE);
    const { unmount } = renderStage([tableSurface()]);
    expect(document.querySelector('[data-surface-id="big-table"] [role="group"]')).toBeNull();
    unmount();
    await seedPositions(VIRTUALIZE_ABOVE + 1);
    renderStage([tableSurface()]);
    expect(document.querySelector('[data-surface-id="big-table"] [role="group"]')).not.toBeNull();
  });
});

describe('§26 reduced fidelity under load', () => {
  it('says nothing while nothing has been measured', async () => {
    // The default. An unmeasured machine holds at full, and a plane that
    // announced "reduced fidelity" because a probe had not returned yet would
    // train the operator to ignore the words.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no server here')));
    await seedPositions(4);
    renderStage([tableSurface()]);
    await waitFor(() => expect(screen.queryByText(/fidelity/i)).toBeNull());
  });

  it('names the level on screen once the host reports it is struggling', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          host: { readings: { cpu: { name: 'cpu', value: 97, unit: '%', reason: '', measured: true, at: 1 } } },
        }),
      }),
    );
    await seedPositions(4);
    renderStage([tableSurface()]);
    // A word, not a dimmed animation: §27's rule that colour is never the only
    // indicator, applied to a state the operator would otherwise read as "the
    // app is just slow today".
    const shown = await screen.findByText(/reduced fidelity/i, undefined, { timeout: 4000 });
    expect(shown).toBeTruthy();
    expect(shown.getAttribute('title')).toContain('97');
  });

  it('holds at full when the host says its probe could not run', async () => {
    // The F176 shape: a null CPU must not read as an idle machine, and must
    // not read as a busy one either.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          host: {
            readings: {
              cpu: { name: 'cpu', value: null, unit: '%', reason: 'psutil is not installed', measured: false, at: 1 },
            },
          },
        }),
      }),
    );
    await seedPositions(4);
    renderStage([tableSurface()]);
    await waitFor(() => expect(screen.queryByText(/fidelity/i)).toBeNull(), { timeout: 2000 });
  });
});
