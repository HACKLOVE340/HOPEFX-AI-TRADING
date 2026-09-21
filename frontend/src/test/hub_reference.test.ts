/**
 * §9 "speech references synchronised with visual focus" and "target
 * highlighting"; §10 "what is being explained receives visual focus".
 *
 * The rule the whole module is arranged around: **progress is measured, never
 * estimated.** The obvious implementation times each sentence from its word
 * count. It drifts within two sentences — synthesis rate varies by voice, by
 * engine and by whether a cloud request was slow — and a drifted highlight
 * points at the wrong panel while the AI confidently describes another.
 *
 * These fail on the pre-fix tree — `hub/reference.ts` does not exist there.
 */

import { describe, expect, it } from 'vitest';

import { referencesIn, sentenceAt, sentencesOf, spokenFocus } from '../hub/reference';
import { Workspace, type Surface } from '../hub/workspace';

function plane(): readonly Surface[] {
  const ws = new Workspace();
  ws.open({ kind: 'chart', intent: 'Gold price', priority: 'primary', key: 'gold-chart' });
  ws.open({ kind: 'table', intent: 'Risk limits and headroom', priority: 'critical', key: 'risk' });
  ws.open({ kind: 'news', intent: 'Market headlines', priority: 'secondary', key: 'news' });
  return ws.surfaces;
}

function idOf(surfaces: readonly Surface[], key: string): string {
  const found = surfaces.find((s) => s.key === key);
  if (!found) throw new Error(`no surface with key ${key}`);
  return found.id;
}

describe('splitting an utterance', () => {
  it('keeps each sentence and where it starts', () => {
    const text = 'Gold is up. Risk is fine. Headlines are quiet.';
    const s = sentencesOf(text);
    expect(s.map((x) => x.text)).toEqual(['Gold is up.', 'Risk is fine.', 'Headlines are quiet.']);
    expect(text.slice(s[1]!.start, s[1]!.end)).toBe('Risk is fine.');
  });

  it('handles an utterance with no terminal punctuation', () => {
    expect(sentencesOf('gold is up').map((x) => x.text)).toEqual(['gold is up']);
  });

  it('returns nothing for nothing', () => {
    expect(sentencesOf('')).toEqual([]);
    expect(sentencesOf('   ')).toEqual([]);
  });
});

describe('unmeasured progress is not zero', () => {
  it('returns null rather than the first sentence', () => {
    // The distinction the whole module rests on. Reading null as 0 would make
    // an unmeasured utterance permanently highlight whatever its first sentence
    // named, for as long as it spoke.
    const s = sentencesOf('Gold is up. Risk is fine.');
    expect(sentenceAt(s, null, 25)).toBeNull();
  });

  it('finds the sentence a real fraction lands in', () => {
    const text = 'Gold is up. Risk is fine. Headlines are quiet.';
    const s = sentencesOf(text);
    expect(sentenceAt(s, 0.02, text.length)).toBe(0);
    expect(sentenceAt(s, 0.4, text.length)).toBe(1);
    expect(sentenceAt(s, 0.95, text.length)).toBe(2);
  });

  it('clamps rather than running off the end', () => {
    const text = 'Gold is up.';
    const s = sentencesOf(text);
    expect(sentenceAt(s, 5, text.length)).toBe(0);
    expect(sentenceAt(s, -3, text.length)).toBe(0);
  });

  it('treats a NaN progress as unmeasured', () => {
    // `currentTime / duration` is NaN until the audio element has metadata.
    const s = sentencesOf('Gold is up.');
    expect(sentenceAt(s, Number.NaN, 11)).toBeNull();
  });
});

describe('which surfaces a sentence is about', () => {
  it('finds the one it names', () => {
    const surfaces = plane();
    expect(referencesIn('drawdown is inside the risk limits', surfaces)).toEqual([idOf(surfaces, 'risk')]);
  });

  it('finds both when a sentence names two', () => {
    // Highlighting only the higher-scoring one would answer a smaller question
    // than the sentence asked.
    const surfaces = plane();
    const ids = referencesIn('gold is up but the headlines are ugly', surfaces);
    expect(ids.sort()).toEqual([idOf(surfaces, 'gold-chart'), idOf(surfaces, 'news')].sort());
  });

  it('matches whole words only', () => {
    const ws = new Workspace();
    ws.open({ kind: 'chart', intent: 'Brisk market breadth', priority: 'primary', key: 'breadth' });
    // "risk" is a substring of "brisk". Substring matching lit this up in an
    // earlier draft — the class of defect this repository keeps rediscovering.
    expect(referencesIn('what is the risk', ws.surfaces)).toEqual([]);
  });

  it('is not fooled by a sentence made of filler', () => {
    const surfaces = plane();
    expect(referencesIn('here is what you are seeing now', surfaces)).toEqual([]);
  });

  it('returns nothing when the plane is empty', () => {
    expect(referencesIn('gold is up', [])).toEqual([]);
  });
});

describe('the highlight while speaking', () => {
  it('follows the sentence when progress is measured', () => {
    const surfaces = plane();
    const utterance = 'Gold is up two dollars. Risk headroom is thin. The headlines are quiet.';

    const early = spokenFocus({ utterance, surfaces, progress: 0.05 });
    expect(early.ids).toEqual([idOf(surfaces, 'gold-chart')]);
    expect(early.wholeUtterance).toBe(false);

    const middle = spokenFocus({ utterance, surfaces, progress: 0.5 });
    expect(middle.ids).toEqual([idOf(surfaces, 'risk')]);

    const late = spokenFocus({ utterance, surfaces, progress: 0.95 });
    expect(late.ids).toEqual([idOf(surfaces, 'news')]);
  });

  it('covers the whole utterance when nothing measured it, and says so', () => {
    // Correct but less precise, rather than precise and wrong. The flag exists
    // so a caller can never present the fallback as a measurement.
    const surfaces = plane();
    const focus = spokenFocus({
      utterance: 'Gold is up. Risk headroom is thin.',
      surfaces,
      progress: null,
    });
    expect(focus.wholeUtterance).toBe(true);
    expect(focus.sentence).toBeNull();
    expect(focus.ids.sort()).toEqual([idOf(surfaces, 'gold-chart'), idOf(surfaces, 'risk')].sort());
  });

  it('holds the previous target through a sentence that names nothing', () => {
    // "It is at four percent." refers to whatever came before it. Going dark
    // mid-thought reads as the highlight breaking.
    const surfaces = plane();
    const utterance = 'Look at the risk table. It is at four percent.';
    const second = spokenFocus({ utterance, surfaces, progress: 0.8 });
    expect(second.ids).toEqual([idOf(surfaces, 'risk')]);
  });

  it('highlights nothing when nothing is being said', () => {
    expect(spokenFocus({ utterance: '', surfaces: plane(), progress: 0.5 }).ids).toEqual([]);
  });

  it('highlights nothing when the plane is empty', () => {
    expect(spokenFocus({ utterance: 'gold is up', surfaces: [], progress: 0.5 }).ids).toEqual([]);
  });
});
