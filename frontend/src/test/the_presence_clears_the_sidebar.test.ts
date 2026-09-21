/**
 * The presence panel landed inside the sidebar.
 *
 * `dockFor` tries each corner and takes the first that collides with nothing in
 * its `avoid` list. `floatingLanes` fed it the support launcher, which is why it
 * stopped choosing bottom-right — and then it chose bottom-LEFT, which is where
 * the desktop sidebar is. Measured in Chromium at 1440x900 on /ai: the presence
 * sat at (24,600) 268x276 while the sidebar occupies x 0-310, so it covered the
 * navigation and the left edge of the "Where to next" footer. The footer's
 * heading read "TO NEXT" in the screenshot because "WHERE" was underneath it.
 *
 * The machinery was right and its inputs were incomplete: it knew about other
 * floating controls and nothing about the app chrome. The sidebar now claims a
 * lane like any other persistent occupant, so no new logic is needed in the
 * dock — the same rule that moved the presence off the launcher moves it off
 * the sidebar.
 */
import { describe, it, expect, beforeEach } from 'vitest';

import { readLanes, reserveLane, releaseLane, SIDEBAR_LANE } from '../hub/floatingLanes';
import { dockFor } from '../hub/presenceDock';

const VIEWPORT = { x: 0, y: 0, width: 1440, height: 900 };
const SIDEBAR = { x: 0, y: 0, width: 310, height: 900 };
const LAUNCHER = { x: 1358, y: 824, width: 56, height: 56 };

const overlaps = (a: typeof SIDEBAR, b: typeof SIDEBAR) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

beforeEach(() => {
  readLanes().forEach((_, i) => void i);
  releaseLane(SIDEBAR_LANE);
  releaseLane('support-launcher');
});

describe('the presence dock clears the app chrome', () => {
  it('exports a stable id for the sidebar lane', () => {
    expect(typeof SIDEBAR_LANE).toBe('string');
    expect(SIDEBAR_LANE.length).toBeGreaterThan(0);
  });

  it('does not sit on the sidebar when the sidebar has claimed its space', () => {
    reserveLane(SIDEBAR_LANE, SIDEBAR);
    reserveLane('support-launcher', LAUNCHER);

    const dock = dockFor({ viewport: VIEWPORT, state: 'active', avoid: readLanes() });
    expect(dock.visible).toBe(true);
    expect(overlaps(dock.rect, SIDEBAR), `presence at ${JSON.stringify(dock.rect)} is on the sidebar`).toBe(false);
    expect(overlaps(dock.rect, LAUNCHER), 'presence is back on the support launcher').toBe(false);
  });

  it('still reports the overlap rather than hiding it when every corner is taken', () => {
    reserveLane('everything', { x: 0, y: 0, width: 1440, height: 900 });
    const dock = dockFor({ viewport: VIEWPORT, state: 'active', avoid: readLanes() });
    expect(dock.overlapping.length, 'a dock with nowhere to go must say so').toBeGreaterThan(0);
    expect(dock.reason).toBeTruthy();
  });
});
