/**
 * hub/intent.ts — turning what someone said into surfaces to open.
 *
 * §8: "Allow natural-language commands such as 'show me everything affecting
 * gold', 'focus on risk', 'bring back yesterday's workspace', and 'simplify
 * this'."
 *
 * ## Why this is local and deterministic
 *
 * A model can read intent far better than a keyword table, and eventually one
 * will — the gateway is right there. But routing every "simplify this" through a
 * paid model call means the workspace stops responding when a vendor is
 * unreachable, costs money to close a panel, and adds a second of latency to a
 * gesture that should feel instant.
 *
 * So the obvious commands resolve locally and instantly, and anything this does
 * not recognise falls through to the model. The two are not competing: this is
 * the reflex, the model is the thought.
 *
 * Deterministic also means testable. Every mapping below is asserted, which is
 * what stops "show me risk" quietly opening nothing after a refactor.
 */

import type { SurfaceRequest } from './contracts.shared';

export interface Intent {
  /** Surfaces to open, in the order they should appear. */
  open: SurfaceRequest[];
  /** Wipe the plane first — "simplify this", "clear". */
  clear: boolean;
  /** A phrase to resolve against what is already open — "focus the gold chart". */
  focus: string | null;
  /** True when nothing here matched and the model should be asked instead. */
  unhandled: boolean;
}

const EMPTY: Intent = { open: [], clear: false, focus: null, unhandled: true };

/**
 * Subjects this deployment can put on the plane, and what a mention pulls up.
 *
 * Each entry is deliberately more than one surface where the subject warrants
 * it: §8's example is "show me everything affecting gold", and answering that
 * with a single chart would be answering a different question.
 */
const SUBJECTS: { match: RegExp; surfaces: SurfaceRequest[] }[] = [
  {
    match: /\b(gold|xau|xauusd)\b/i,
    surfaces: [
      { kind: 'chart', intent: 'Gold price', priority: 'primary', key: 'gold-chart' },
      { kind: 'news', intent: 'Gold headlines', priority: 'secondary', key: 'gold-news' },
      { kind: 'table', intent: 'Gold exposure', priority: 'secondary', key: 'gold-exposure' },
    ],
  },
  {
    match: /\brisk\b|\bdrawdown\b|\bexposure\b/i,
    surfaces: [
      { kind: 'table', intent: 'Risk limits and headroom', priority: 'critical', key: 'risk' },
      { kind: 'distribution', intent: 'Loss distribution', priority: 'secondary', key: 'risk-dist' },
    ],
  },
  {
    match: /\bposition|\bportfolio\b|\bopen trades?\b/i,
    surfaces: [{ kind: 'table', intent: 'Open positions', priority: 'primary', key: 'positions' }],
  },
  {
    match: /\bnews\b|\bheadlines?\b|\bmacro\b/i,
    surfaces: [{ kind: 'news', intent: 'Market headlines', priority: 'secondary', key: 'news' }],
  },
  {
    match: /\bcosts?\b|\bspen[dt]\b|\bspending\b|\bbudget\b|\bceiling\b/i,
    surfaces: [{ kind: 'table', intent: 'AI spend against the ceiling', priority: 'secondary', key: 'spend' }],
  },
  {
    match: /\bagents?\b|\bdepartments?\b/i,
    surfaces: [{ kind: 'agent_activity', intent: 'What the agents are doing', priority: 'secondary', key: 'agents' }],
  },
  {
    match: /\bcamera\b|\bscan\b|\bsee this\b|\blook at\b/i,
    surfaces: [{ kind: 'camera', intent: 'Camera', priority: 'primary', key: 'camera' }],
  },
  {
    match: /\blog|\bterminal\b|\bcalls?\b/i,
    surfaces: [{ kind: 'terminal', intent: 'Recent model calls', priority: 'background', key: 'calls' }],
  },
  // §21. Each names the QUESTION it answers, not the chart type, because that
  // is how somebody asks: "where was the movement", not "render a heatmap".
  {
    match: /\bheat ?map\b|\bintensity\b|\bwhere was the (movement|action)\b|\bbusiest\b/i,
    surfaces: [
      { kind: 'heatmap', intent: 'Session movement', priority: 'secondary', key: 'session-heatmap' },
    ],
  },
  {
    match: /\bnetwork\b|\brelationships?\b|\bhow (do|does) .* (relate|connect)\b|\bconnections?\b|\bgraph\b/i,
    surfaces: [
      { kind: 'network', intent: 'How these relate', priority: 'secondary', key: 'relationships' },
    ],
  },
  {
    match: /\btimeline\b|\bchronolog|\bwhat happened when\b|\bin order\b|\bsequence of events\b/i,
    surfaces: [
      { kind: 'timeline', intent: 'What happened, in order', priority: 'secondary', key: 'chronology' },
    ],
  },
];

const CLEAR = /\bsimplify\b|\bclear\b|\bclose everything\b|\bhide everything\b|\bstart over\b|\bclean\b/i;
const FOCUS = /\bfocus (?:on )?(.+)|\bzoom (?:in )?(?:on )?(.+)|\bjust (?:show )?(?:me )?(.+)/i;
const EVERYTHING = /\beverything\b|\ball of it\b|\bwhole picture\b/i;

export function readIntent(phrase: string): Intent {
  const text = (phrase ?? '').trim();
  if (!text) return { ...EMPTY, unhandled: false };

  const clear = CLEAR.test(text);
  const focusMatch = FOCUS.exec(text);
  const focus = focusMatch ? (focusMatch[1] ?? focusMatch[2] ?? focusMatch[3] ?? '').trim() : null;

  const open: SurfaceRequest[] = [];
  for (const subject of SUBJECTS) {
    if (!subject.match.test(text)) continue;
    // "Show me gold" is the chart. "Show me everything affecting gold" is the
    // whole set — §8's own example, and the difference between answering the
    // question and answering a smaller one.
    open.push(...(EVERYTHING.test(text) ? subject.surfaces : subject.surfaces.slice(0, 1)));
  }

  // A focus phrase that also names a subject opens it first, so "focus on risk"
  // works whether or not risk is already on the plane.
  const handled = clear || open.length > 0 || (focus !== null && focus.length > 0);
  return { open, clear, focus: focus || null, unhandled: !handled };
}
