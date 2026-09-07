/**
 * §7: the holographic head, lip sync, the particle field used with restraint,
 * and moving toward the panel being discussed.
 *
 * The rule under all of it, and the reason this module is not a sine wave:
 * **an animation that is not driven by a measurement is a claim about
 * something nobody looked at.** The mouth flapping while `speaking` is true
 * looks approximately right, plays identically for "yes" and for a
 * four-hundred-word briefing, and keeps playing after synthesis has silently
 * died.
 *
 * Fails on the pre-fix tree — `hub/head.ts` does not exist there.
 */

import { describe, expect, it } from 'vitest';

import { gazeToward, headOffset, mouthFor, particleField } from '../hub/head';

describe('the mouth follows the utterance', () => {
  const text = 'Gold is up.';

  it('is shut when nothing is being said', () => {
    expect(mouthFor(text, 0.5, false).openness).toBe(0);
  });

  it('opens wider on an open vowel than on a consonant', () => {
    // "Gold": G-o-l-d. The o is index 1, the l is index 2.
    const onO = mouthFor('Gold', 1 / 4, true);
    const onL = mouthFor('Gold', 2 / 4, true);
    expect(onO.openness).toBeGreaterThan(onL.openness);
    expect(onO.measured).toBe(true);
  });

  it('closes the lips on m, b and p', () => {
    // A mouth hanging open on "must" reads as broken to anyone watching.
    for (const [word, index] of [['must', 0], ['big', 0], ['put', 0]] as const) {
      expect(mouthFor(word, index / word.length, true).openness).toBeLessThan(0.1);
    }
  });

  it('shuts at a full stop', () => {
    expect(mouthFor('Up.', 2 / 3, true).openness).toBe(0);
  });

  it('holds a steady shape, and says it is unmeasured, when progress is null', () => {
    // Half-open and still is honest. A waveform driven by Date.now() is a claim
    // about an audio signal nobody has looked at.
    const m = mouthFor(text, null, true);
    expect(m.measured).toBe(false);
    expect(m.openness).toBeGreaterThan(0);
    expect(m.openness).toBeLessThan(1);
  });

  it('does not claim a measurement for an empty utterance', () => {
    expect(mouthFor('', 0.5, true).measured).toBe(false);
  });

  it('never runs off the end of the text', () => {
    for (const p of [-1, 0, 0.999, 1, 4]) {
      expect(() => mouthFor('ab', p, true)).not.toThrow();
      expect(mouthFor('ab', p, true).openness).toBeGreaterThanOrEqual(0);
    }
  });

  it('is read from the text, not from a shared clock', () => {
    // The failure a sine wave hides: the same animation for every utterance,
    // still playing after synthesis has silently died. Same progress, same
    // moment, different text — different mouth.
    expect(mouthFor('aaaa', 0.5, true).openness).toBe(1);
    expect(mouthFor('mmmm', 0.5, true).openness).toBeLessThan(0.1);
    expect(mouthFor('....', 0.5, true).openness).toBe(0);
  });

  it('changes across one utterance as it is spoken', () => {
    const word = 'gold';
    const shapes = [0, 0.25, 0.5, 0.75].map((p) => mouthFor(word, p, true).openness);
    expect(new Set(shapes).size).toBeGreaterThan(1);
  });
});

describe('the particle field is used with restraint', () => {
  it('draws nothing under reduced motion', () => {
    // A field of drifting dots is exactly what that setting exists to stop.
    expect(particleField(0, { intensity: 1, reducedMotion: true, offline: false })).toEqual([]);
  });

  it('draws nothing when offline', () => {
    // Particles read as activity and there is none — the same reason the outer
    // ring stops dead rather than spinning prettily over a dead socket.
    expect(particleField(0, { intensity: 1, reducedMotion: false, offline: true })).toEqual([]);
  });

  it('gives a quiet system fewer than a busy one', () => {
    const quiet = particleField(0, { intensity: 0.1, reducedMotion: false, offline: false });
    const busy = particleField(0, { intensity: 1, reducedMotion: false, offline: false });
    expect(quiet.length).toBeLessThan(busy.length);
  });

  it('draws none at all when there is no activity', () => {
    expect(particleField(0, { intensity: 0, reducedMotion: false, offline: false })).toEqual([]);
  });

  it('stays inside the core rather than scattering over the panels', () => {
    for (const p of particleField(1234, { intensity: 1, reducedMotion: false, offline: false })) {
      expect(Math.hypot(p.x, p.y)).toBeLessThanOrEqual(1);
      expect(p.alpha).toBeGreaterThan(0);
      expect(p.alpha).toBeLessThanOrEqual(1);
    }
  });

  it('is the same field at the same time', () => {
    // A random field cannot be tested, and it flickers between frames on a
    // device slow enough to drop one.
    const a = particleField(500, { intensity: 0.7, reducedMotion: false, offline: false });
    const b = particleField(500, { intensity: 0.7, reducedMotion: false, offline: false });
    expect(a).toEqual(b);
  });

  it('moves between frames', () => {
    const a = particleField(0, { intensity: 0.7, reducedMotion: false, offline: false });
    const b = particleField(4000, { intensity: 0.7, reducedMotion: false, offline: false });
    expect(a).not.toEqual(b);
  });
});

describe('looking at the panel being discussed', () => {
  const core = { x: 100, y: 300, width: 200, height: 200 };

  it('looks right for a panel on the right', () => {
    const gaze = gazeToward(core, { x: 800, y: 350, width: 300, height: 100 });
    expect(gaze).not.toBeNull();
    expect(gaze!.x).toBeGreaterThan(0);
  });

  it('looks up for a panel above', () => {
    const gaze = gazeToward(core, { x: 150, y: 20, width: 200, height: 100 });
    expect(gaze!.y).toBeLessThan(0);
  });

  it('returns null rather than pointing at the origin when a rect is unmeasured', () => {
    // A presence that gestures at the top-left corner because a rect was zero
    // is worse than one that does not gesture.
    expect(gazeToward(core, null)).toBeNull();
    expect(gazeToward(null, core)).toBeNull();
    expect(gazeToward(core, { x: 0, y: 0, width: 0, height: 0 })).toBeNull();
    expect(gazeToward({ x: 0, y: 0, width: 0, height: 0 }, core)).toBeNull();
  });

  it('clamps rather than looking off the edge of its own head', () => {
    const gaze = gazeToward(core, { x: 90000, y: 90000, width: 10, height: 10 });
    expect(gaze!.x).toBeLessThanOrEqual(1);
    expect(gaze!.y).toBeLessThanOrEqual(1);
    expect(gaze!.reach).toBeLessThanOrEqual(1);
  });

  it('faces forward when the target is where the core is', () => {
    expect(gazeToward(core, core)).toEqual({ x: 0, y: 0, reach: 0 });
  });
});

describe('moving toward it', () => {
  it('shifts a little, not across the screen', () => {
    // A presence that slides over to a panel takes the operator's eyes off the
    // thing it is trying to draw them to.
    const gaze = gazeToward({ x: 0, y: 0, width: 300, height: 300 }, { x: 900, y: 0, width: 200, height: 200 });
    const offset = headOffset(gaze, 300, false);
    expect(Math.abs(offset.x)).toBeGreaterThan(0);
    expect(Math.abs(offset.x)).toBeLessThanOrEqual(300 * 0.06);
  });

  it('does not move at all under reduced motion', () => {
    const gaze = gazeToward({ x: 0, y: 0, width: 300, height: 300 }, { x: 900, y: 0, width: 200, height: 200 });
    expect(headOffset(gaze, 300, true)).toEqual({ x: 0, y: 0 });
  });

  it('does not move when there is nothing to look at', () => {
    expect(headOffset(null, 300, false)).toEqual({ x: 0, y: 0 });
  });
});
