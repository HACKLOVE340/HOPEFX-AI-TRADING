/**
 * hub/reference.ts — what the AI is talking about, right now.
 *
 * §9: "speech references synchronised with visual focus", "target highlighting".
 * §10: "what is being explained receives visual focus."
 *
 * This is the difference between an assistant that reads a paragraph at you and
 * one that is standing in front of the screen pointing at things. The words
 * "drawdown is at four percent" mean much more when the risk panel lights up as
 * they are said.
 *
 * ## Progress is measured, never estimated
 *
 * The obvious implementation times each sentence from its word count and steps
 * the highlight on a timer. It is wrong roughly immediately: synthesis rate
 * varies by voice, by engine, by sentence, and by whether a cloud request was
 * slow. A highlight that has drifted two sentences ahead is pointing at the
 * wrong panel while the AI confidently describes another — the exact failure
 * `Workspace.resolve` returns null to avoid.
 *
 * So progress arrives as a real measurement or not at all:
 *
 * - Cloud TTS plays through an `<audio>` element: `currentTime / duration`.
 * - Web Speech emits `boundary` events carrying `charIndex`.
 * - Muted, unsupported, or before the first event: **null**.
 *
 * Null does not mean "assume the start". It means the highlight covers
 * everything the whole utterance refers to, held for as long as it is speaking.
 * That is still useful and it is never wrong; a stepped highlight driven by a
 * guess would be neither.
 */

import type { Surface } from './workspace';

export interface Sentence {
  text: string;
  /** Character offset of the first character, within the whole utterance. */
  start: number;
  /** Character offset just past the last character. */
  end: number;
}

/**
 * Words that match everything and therefore point at nothing.
 *
 * The same list this repository has now needed three times — `Scene.resolve`,
 * `Workspace.resolve`, `AppSurface.search`. Without it "showing this now"
 * highlights whichever panel happens to have "show" in its title.
 */
const STOPWORDS = new Set([
  'the', 'this', 'that', 'these', 'those', 'and', 'for', 'with', 'about', 'its',
  'show', 'showing', 'give', 'need', 'want', 'please', 'from', 'into', 'onto',
  'what', 'whats', 'have', 'has', 'are', 'was', 'were', 'can', 'you', 'your',
  'our', 'their', 'not', 'but', 'all', 'any', 'now', 'then', 'here', 'there',
  'looks', 'look', 'see', 'seeing', 'says', 'said', 'been', 'being', 'over',
]);

/** Split into sentences, keeping each one's offset in the original string. */
export function sentencesOf(text: string): Sentence[] {
  const source = text ?? '';
  const out: Sentence[] = [];
  // Split on sentence-ending punctuation followed by whitespace, keeping the
  // punctuation with the sentence it ends. A regex `split` would lose the
  // offsets, which are the whole point.
  const pattern = /[^.!?\n]+[.!?]*\s*/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source)) !== null) {
    const raw = match[0];
    const trimmed = raw.trim();
    if (!trimmed) continue;
    const lead = raw.length - raw.trimStart().length;
    out.push({ text: trimmed, start: match.index + lead, end: match.index + lead + trimmed.length });
  }
  return out;
}

/**
 * Which sentence a fraction-of-the-way-through lands in.
 *
 * `progress` is a fraction of the utterance, 0 to 1. Null progress returns
 * null — "not measured", not "the first one".
 */
export function sentenceAt(sentences: readonly Sentence[], progress: number | null, total: number): number | null {
  if (progress === null || !Number.isFinite(progress) || sentences.length === 0 || total <= 0) return null;
  const at = Math.max(0, Math.min(1, progress)) * total;
  for (let i = 0; i < sentences.length; i += 1) {
    const s = sentences[i]!;
    if (at < s.end) return i;
  }
  return sentences.length - 1;
}

/**
 * Which surfaces a phrase is about. Possibly several — possibly none.
 *
 * Unlike `Workspace.resolve`, which answers "which ONE panel did they mean" and
 * returns null rather than guessing, this answers "which panels does this
 * sentence touch". A sentence comparing gold and the dollar genuinely refers to
 * two, and highlighting only the higher-scoring one would be a worse answer
 * than highlighting both.
 *
 * A word must be a whole word. Substring matching made "risk" light up a panel
 * called "brisk market" in an earlier draft of this, which is the class of
 * defect this repository keeps rediscovering.
 */
export function referencesIn(phrase: string, surfaces: readonly Surface[]): string[] {
  const words = (phrase ?? '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length >= 3 && !STOPWORDS.has(w));
  if (words.length === 0) return [];

  const wanted = new Set(words);
  const hits: { id: string; score: number }[] = [];
  for (const surface of surfaces) {
    const hay = new Set(
      `${surface.meaning} ${surface.kind} ${surface.key}`
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter(Boolean),
    );
    let score = 0;
    for (const word of wanted) if (hay.has(word)) score += 1;
    if (score > 0) hits.push({ id: surface.id, score });
  }
  if (hits.length === 0) return [];

  // Everything that matched as well as the best match. One shared word is a
  // real reference when the panel is "Gold price" and the sentence says gold;
  // it is noise when another panel matched three. Keeping only the top tier
  // avoids lighting up half the plane on a long sentence.
  const best = Math.max(...hits.map((h) => h.score));
  return hits.filter((h) => h.score === best).map((h) => h.id);
}

export interface SpokenFocusInput {
  /** What is being said. Empty when nothing is. */
  utterance: string;
  surfaces: readonly Surface[];
  /** 0-1 through the utterance, or null when nothing has measured it. */
  progress: number | null;
}

export interface SpokenFocus {
  /** Surface ids to highlight. */
  ids: string[];
  /** The sentence currently being spoken, or null when progress is unmeasured. */
  sentence: string | null;
  /**
   * True when the highlight covers the whole utterance because progress was
   * never measured, rather than following it sentence by sentence. The caller
   * may want to say so; it must never present a guess as a measurement.
   */
  wholeUtterance: boolean;
}

export function spokenFocus({ utterance, surfaces, progress }: SpokenFocusInput): SpokenFocus {
  const text = (utterance ?? '').trim();
  if (!text || surfaces.length === 0) return { ids: [], sentence: null, wholeUtterance: false };

  const sentences = sentencesOf(text);
  const index = sentenceAt(sentences, progress, text.length);

  if (index === null) {
    // Unmeasured. Highlight everything the utterance refers to — correct, if
    // less precise. A stepped highlight from a timer would be precise and wrong.
    //
    // The union of each SENTENCE's references, not one score over the whole
    // blob. Scoring the blob applies the top-tier rule across sentence
    // boundaries, so "Gold is up. Risk headroom is thin." scored the risk panel
    // 2 and the gold chart 1, and dropped gold entirely — an utterance that
    // plainly mentions both, highlighting one. The top-tier rule earns its keep
    // within a sentence and is wrong across them.
    const union: string[] = [];
    for (const sentence of sentences) {
      for (const id of referencesIn(sentence.text, surfaces)) {
        if (!union.includes(id)) union.push(id);
      }
    }
    return { ids: union, sentence: null, wholeUtterance: true };
  }

  const current = sentences[index]!;
  const ids = referencesIn(current.text, surfaces);
  // A sentence that names nothing keeps the previous sentence's targets rather
  // than going dark mid-thought — "It is at four percent." refers to whatever
  // the sentence before it named.
  if (ids.length === 0) {
    for (let i = index - 1; i >= 0; i -= 1) {
      const earlier = referencesIn(sentences[i]!.text, surfaces);
      if (earlier.length > 0) {
        return { ids: earlier, sentence: current.text, wholeUtterance: false };
      }
    }
  }
  return { ids, sentence: current.text, wholeUtterance: false };
}
