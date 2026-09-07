/**
 * §18 ambient awareness, and §7's idle attention — the half that needs no camera.
 *
 * ## The judgement this phase turned on
 *
 * §18 has five rows and they are not equally buildable. Three are achievable
 * right now, locally, with no camera, no new dependency and no consent
 * conversation at all — and those are the ones a careful engineer builds first,
 * because the cheapest way to respect somebody's privacy is not to need their
 * permission.
 *
 *   attention-aware    document visibility, window focus, time since input
 *   source selection   which source, each behind its own consent
 *   local processing   deciding HERE whether a frame has to leave at all
 *
 * Two are not. Camera gesture recognition and physical pointing both need hand
 * or body landmarks, and this repository has no landmark source. The pointer
 * half of each IS real — a swipe is a gesture, and a hit test answers "what am
 * I pointing at" — so that is built and the rows stay `staged` with the
 * missing half named. Building a recogniser that nothing feeds would be the
 * `hopefx-dead-controls` defect wearing a camera.
 *
 * ## Unknown is not "away"
 *
 * §22's rule again. An attention state derived from inputs nobody supplied is
 * not "the operator has left" — it is "nobody looked". Reporting the first
 * would have the presence go quiet on somebody sitting right there.
 *
 * ## Local processing is the privacy row, not a performance one
 *
 * The point of deciding locally is that most frames never leave the machine.
 * A frame identical to the last one, or blank, or arriving faster than the
 * rate allows, is dropped HERE — and every drop is counted with a reason, so
 * "the AI saw nothing" stays distinguishable from "we sent nothing".
 */

import { describe, it, expect } from 'vitest';

import { ATTENTION_STATES, attentionFrom, idleMotion } from '../hub/attention';
import { SOURCES, availableSources, selectSource } from '../hub/visionSource';
import { FrameTriage } from '../hub/frameTriage';
import { recogniseGesture, pointingAt } from '../hub/gestures';
import { SceneGraph } from '../hub/sceneGraph';

// ── attention, with no camera ────────────────────────────────────────────────

describe('attention', () => {
  it('reads engaged when the tab is visible, focused and recently touched', () => {
    const state = attentionFrom({ visible: true, focused: true, msSinceInput: 2_000 });
    expect(state.state).toBe('engaged');
  });

  it('reads present when the tab is visible but nothing has been touched for a while', () => {
    const state = attentionFrom({ visible: true, focused: true, msSinceInput: 120_000 });
    expect(state.state).toBe('present');
  });

  it('reads away when the tab is hidden', () => {
    const state = attentionFrom({ visible: false, focused: false, msSinceInput: 1_000 });
    expect(state.state).toBe('away');
  });

  it('reads away when the window lost focus, even with the tab visible', () => {
    const state = attentionFrom({ visible: true, focused: false, msSinceInput: 1_000 });
    expect(state.state).toBe('away');
  });

  it('reads unknown when nobody supplied the inputs, never away', () => {
    // "The operator has left" and "nobody looked" are different facts, and
    // reporting the first would have the presence go quiet on somebody sitting
    // right there.
    const state = attentionFrom({});
    expect(state.state).toBe('unknown');
    expect(state.reason).toMatch(/not measured|no input/i);
  });

  it('always states a reason for a state that is not engaged', () => {
    for (const input of [{}, { visible: false }, { visible: true, focused: true, msSinceInput: 999_999 }]) {
      expect(attentionFrom(input).reason.length).toBeGreaterThan(0);
    }
  });

  it('names every state it can produce, so the renderer can be checked against it', () => {
    expect(ATTENTION_STATES).toContain('engaged');
    expect(ATTENTION_STATES).toContain('present');
    expect(ATTENTION_STATES).toContain('away');
    expect(ATTENTION_STATES).toContain('unknown');
  });

  it('needs no camera and no consent to answer', () => {
    // The cheapest way to respect somebody's privacy is not to need their
    // permission in the first place.
    const state = attentionFrom({ visible: true, focused: true, msSinceInput: 0 });
    expect(state.usedCamera).toBe(false);
  });
});

// ── §7: idle movement driven by attention ────────────────────────────────────

describe('idle motion', () => {
  it('breathes while the operator is present', () => {
    const motion = idleMotion(attentionFrom({ visible: true, focused: true, msSinceInput: 120_000 }));
    expect(motion.amplitude).toBeGreaterThan(0);
    expect(motion.reason).toMatch(/present|idle/i);
  });

  it('settles when the operator is away, rather than animating to an empty room', () => {
    const motion = idleMotion(attentionFrom({ visible: false }));
    expect(motion.amplitude).toBe(0);
  });

  it('keeps breathing on unknown attention, because a still presence reads as broken', () => {
    // Going still because nobody measured would make the presence look dead on
    // every browser that does not report visibility.
    const motion = idleMotion(attentionFrom({}));
    expect(motion.amplitude).toBeGreaterThan(0);
  });

  it('stops entirely under reduced motion whatever the attention', () => {
    const motion = idleMotion(attentionFrom({ visible: true, focused: true, msSinceInput: 0 }), true);
    expect(motion.amplitude).toBe(0);
    expect(motion.reason).toMatch(/reduced motion/i);
  });
});

// ── source selection ─────────────────────────────────────────────────────────

describe('vision source selection', () => {
  it('offers camera, screen and none', () => {
    expect(SOURCES).toEqual(['none', 'camera', 'screen']);
  });

  it('reports what the browser can actually do', () => {
    const available = availableSources({ hasCamera: true, hasScreenCapture: false });
    expect(available.camera.available).toBe(true);
    expect(available.screen.available).toBe(false);
    expect(available.screen.reason).toMatch(/screen/i);
  });

  it('says a capability is unknown rather than unavailable when nobody checked', () => {
    const available = availableSources({});
    expect(available.camera.available).toBe(false);
    expect(available.camera.reason).toMatch(/not checked|unknown/i);
  });

  it('refuses a source without its own consent', () => {
    const chosen = selectSource('camera', { consent: { camera: false, screen: false } });
    expect(chosen.allowed).toBe(false);
    expect(chosen.reason).toMatch(/consent/i);
  });

  it('treats screen capture as a different consent from the camera', () => {
    // A webcam shows a face. A screen share shows the whole desktop, including
    // every other application. Consenting to one is not consenting to the other.
    const chosen = selectSource('screen', { consent: { camera: true, screen: false } });
    expect(chosen.allowed).toBe(false);
    expect(chosen.reason).toMatch(/screen/i);
  });

  it('allows a source that is both available and consented', () => {
    const chosen = selectSource('camera', { consent: { camera: true, screen: false } });
    expect(chosen.allowed).toBe(true);
  });

  it('always allows none, which is the way to turn it off', () => {
    const chosen = selectSource('none', { consent: { camera: false, screen: false } });
    expect(chosen.allowed).toBe(true);
  });

  it('refuses a source it does not have rather than falling back to the camera', () => {
    expect(() => selectSource('microphone' as never, { consent: { camera: true, screen: true } })).toThrow();
  });
});

// ── local processing ─────────────────────────────────────────────────────────

describe('frame triage', () => {
  it('sends the first real frame', () => {
    const triage = new FrameTriage();
    const decision = triage.consider({ fingerprint: 'abc', variance: 0.4, at: 0 });
    expect(decision.send).toBe(true);
  });

  it('drops a frame identical to the last one it sent', () => {
    const triage = new FrameTriage();
    triage.consider({ fingerprint: 'abc', variance: 0.4, at: 0 });
    const decision = triage.consider({ fingerprint: 'abc', variance: 0.4, at: 5_000 });
    expect(decision.send).toBe(false);
    expect(decision.reason).toMatch(/unchanged|identical/i);
  });

  it('drops a blank frame, which is a lens cap rather than a scene', () => {
    const triage = new FrameTriage();
    const decision = triage.consider({ fingerprint: 'blank', variance: 0.001, at: 0 });
    expect(decision.send).toBe(false);
    expect(decision.reason).toMatch(/blank|uniform/i);
  });

  it('drops a frame arriving faster than the rate allows', () => {
    const triage = new FrameTriage({ minIntervalMs: 1_000 });
    triage.consider({ fingerprint: 'a', variance: 0.4, at: 0 });
    const decision = triage.consider({ fingerprint: 'b', variance: 0.4, at: 200 });
    expect(decision.send).toBe(false);
    expect(decision.reason).toMatch(/rate|too soon/i);
  });

  it('counts what it dropped and why, so nothing sent is distinguishable from nothing seen', () => {
    const triage = new FrameTriage({ minIntervalMs: 1_000 });
    triage.consider({ fingerprint: 'a', variance: 0.4, at: 0 });
    triage.consider({ fingerprint: 'a', variance: 0.4, at: 5_000 });
    triage.consider({ fingerprint: 'blank', variance: 0.0, at: 10_000 });

    const report = triage.report();
    expect(report.considered).toBe(3);
    expect(report.sent).toBe(1);
    expect(report.dropped.unchanged).toBe(1);
    expect(report.dropped.blank).toBe(1);
  });

  it('reports the proportion that never left the machine, which is the point', () => {
    const triage = new FrameTriage({ minIntervalMs: 1_000 });
    for (let n = 0; n < 10; n += 1) triage.consider({ fingerprint: 'same', variance: 0.4, at: n * 2_000 });
    const report = triage.report();
    expect(report.sent).toBe(1);
    expect(report.keptLocal).toBe(9);
  });

  it('never sends when consent is absent, whatever the frame looks like', () => {
    const triage = new FrameTriage();
    const decision = triage.consider({ fingerprint: 'abc', variance: 0.9, at: 0 }, { consented: false });
    expect(decision.send).toBe(false);
    expect(decision.reason).toMatch(/consent/i);
  });
});

// ── gestures and pointing: the halves that are real ──────────────────────────

describe('pointer gestures', () => {
  it('recognises a swipe', () => {
    expect(recogniseGesture([{ x: 300, y: 100, t: 0 }, { x: 60, y: 108, t: 180 }])).toBe('swipe_left');
    expect(recogniseGesture([{ x: 60, y: 100, t: 0 }, { x: 300, y: 96, t: 180 }])).toBe('swipe_right');
  });

  it('recognises a long press', () => {
    expect(recogniseGesture([{ x: 100, y: 100, t: 0 }, { x: 102, y: 101, t: 900 }])).toBe('long_press');
  });

  it('returns null for a movement it cannot name, rather than the nearest gesture', () => {
    // A wrong gesture on a trading screen moves a panel somebody was reading.
    expect(recogniseGesture([{ x: 100, y: 100, t: 0 }, { x: 140, y: 150, t: 120 }])).toBeNull();
  });

  it('returns null for a single point, because one point is not a movement', () => {
    expect(recogniseGesture([{ x: 100, y: 100, t: 0 }])).toBeNull();
  });

  it('does not call a slow drift a swipe', () => {
    expect(recogniseGesture([{ x: 300, y: 100, t: 0 }, { x: 60, y: 100, t: 4_000 }])).toBeNull();
  });
});

describe('pointing at an object', () => {
  it('answers what is under a point', () => {
    const graph = new SceneGraph();
    graph.place('chart', { x: 0, y: 0, width: 200, height: 200 });
    graph.place('news', { x: 300, y: 0, width: 200, height: 200 });
    expect(pointingAt(graph, 100, 100)).toBe('chart');
    expect(pointingAt(graph, 350, 50)).toBe('news');
  });

  it('answers the topmost when panels overlap', () => {
    const graph = new SceneGraph();
    graph.place('back', { x: 0, y: 0, width: 200, height: 200 }, { z: 0 });
    graph.place('front', { x: 50, y: 50, width: 200, height: 200 }, { z: 5 });
    expect(pointingAt(graph, 100, 100)).toBe('front');
  });

  it('answers null on empty space rather than the nearest panel', () => {
    const graph = new SceneGraph();
    graph.place('chart', { x: 0, y: 0, width: 100, height: 100 });
    expect(pointingAt(graph, 500, 500)).toBeNull();
  });
});
