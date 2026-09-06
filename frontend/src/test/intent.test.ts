/**
 * Natural-language workspace commands — §8.
 *
 * These resolve locally and instantly. Routing "simplify this" through a paid
 * model call would mean the workspace stops responding when a vendor is
 * unreachable, costs money to close a panel, and adds a second of latency to a
 * gesture that should feel immediate. The model handles what this does not
 * recognise; the two are reflex and thought, not rivals.
 *
 * Every mapping is asserted, which is what stops "show me risk" quietly opening
 * nothing after a refactor.
 */

import { describe, it, expect } from 'vitest';
import { readIntent } from '../hub/intent';

describe('the specification\'s own examples', () => {
  it('"show me everything affecting gold" opens the whole set, not one chart', () => {
    const i = readIntent('show me everything affecting gold');
    expect(i.open.length).toBeGreaterThan(1);
    expect(i.open.map((s) => s.kind)).toContain('chart');
    expect(i.open.map((s) => s.kind)).toContain('news');
  });

  it('"show me gold" opens just the chart', () => {
    // Answering a narrow question with six panels is its own kind of wrong.
    const i = readIntent('show me gold');
    expect(i.open).toHaveLength(1);
    expect(i.open[0]?.kind).toBe('chart');
  });

  it('"focus on risk" both opens risk and asks to focus it', () => {
    const i = readIntent('focus on risk');
    expect(i.focus).toContain('risk');
    expect(i.open.map((s) => s.key)).toContain('risk');
  });

  it('"simplify this" clears the plane', () => {
    expect(readIntent('simplify this').clear).toBe(true);
  });
});

describe('subjects', () => {
  it.each([
    ['what are my positions', 'positions'],
    ['any news?', 'news'],
    ['how much have we spent', 'spend'],
    ['what are the agents doing', 'agents'],
    ['look at this', 'camera'],
    ['show me the call log', 'calls'],
  ])('%o opens %o', (phrase, key) => {
    expect(readIntent(phrase).open.map((s) => s.key)).toContain(key);
  });

  it('gives risk a critical tier — it is the one that must dominate', () => {
    const i = readIntent('risk');
    expect(i.open[0]?.priority).toBe('critical');
  });
});

describe('what it does NOT pretend to understand', () => {
  it('marks an unrecognised question for the model rather than guessing', () => {
    // The failure to avoid: a keyword table that opens a chart because the
    // sentence happened to contain a word, and the operator's actual question
    // goes unanswered.
    const i = readIntent('what do you think about the fed meeting next week');
    expect(i.unhandled).toBe(true);
    expect(i.open).toEqual([]);
  });

  it('treats an empty phrase as nothing to do, not as unhandled', () => {
    const i = readIntent('   ');
    expect(i.unhandled).toBe(false);
    expect(i.open).toEqual([]);
  });
});
