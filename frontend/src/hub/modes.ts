/**
 * hub/modes.ts — the ten presentation modes of §6, and the one rule they all obey.
 *
 * §6 asks the presence to change character with the task: a market analyst
 * reads differently from a teacher, and a mission-control screen at 03:00
 * differently from an executive briefing. §5 adds the constraint that makes
 * this safe rather than gimmicky:
 *
 *   **"Adapt explanation depth without changing the intelligence."**
 *
 * ## A mode changes presentation. It never changes what is true.
 *
 * This is the whole design, and it is the difference between a feature and a
 * defect on a platform that moves money. Child-simple mode may say "you have
 * used up most of the room you gave yourself for losses today" where mission
 * control says "daily loss 4.10% of a 5.00% limit" — and both must be reporting
 * **4.10**. A mode that rounded, softened, or omitted a risk figure to suit its
 * register would be a mode that lies, and the operator has no way to know which
 * register they are in when they glance at the screen.
 *
 * So `say()` takes a structured fact and renders words around it. The number is
 * passed through untouched, and a test asserts that every mode renders the same
 * digits for the same fact. Modes choose *which* facts to lead with and how much
 * scaffolding to put round them, never what the facts are.
 *
 * ## Emergency is not a mode you can be in instead of the truth
 *
 * `resolveMode` promotes emergency whenever the presence is alerting, whatever
 * mode was chosen. A kill switch that trips while somebody is in "executive
 * briefing" must not stay quiet because the briefing register is calm. Selecting
 * a mode is a preference; an alert is a fact, and facts win.
 */

import type { LayoutName } from './layout';
import type { PresenceState } from './presence';
import type { SurfaceRequest } from './contracts.shared';

export type ModeId =
  | 'professional_core'
  | 'market_analyst'
  | 'research_scientist'
  | 'engineering'
  | 'teaching'
  | 'executive_briefing'
  | 'mission_control'
  | 'minimal_focus'
  | 'emergency'
  | 'child_simple';

/**
 * How much scaffolding goes round a fact.
 *
 * Explicitly not "how much truth" — see the module note. `headline` states the
 * fact; `teaching` states the same fact and explains the term.
 */
export type Depth = 'headline' | 'brief' | 'standard' | 'detailed' | 'teaching';

export interface PresentationMode {
  id: ModeId;
  name: string;
  /** What the AI says on entering. §6 wants the presence to introduce itself. */
  greeting: string;
  layout: LayoutName;
  depth: Depth;
  /** Concurrent surface ceiling. Mission control wants many; focus wants few. */
  density: number;
  /** Opened on entry, because a mode with no surfaces is a colour scheme. */
  opens: SurfaceRequest[];
  /** Accent for the presence core. Never the only signal for anything. */
  accent: string;
}

const GOLD: SurfaceRequest = { kind: 'chart', intent: 'Gold price', priority: 'primary', key: 'gold-chart' };
const RISK: SurfaceRequest = { kind: 'table', intent: 'Risk limits and headroom', priority: 'critical', key: 'risk' };
const NEWS: SurfaceRequest = { kind: 'news', intent: 'Market headlines', priority: 'secondary', key: 'news' };
const POSITIONS: SurfaceRequest = { kind: 'table', intent: 'Open positions', priority: 'primary', key: 'positions' };
const AGENTS: SurfaceRequest = { kind: 'agent_activity', intent: 'What the agents are doing', priority: 'secondary', key: 'agents' };
const CALLS: SurfaceRequest = { kind: 'terminal', intent: 'Recent model calls', priority: 'background', key: 'calls' };
const DIST: SurfaceRequest = { kind: 'distribution', intent: 'Loss distribution', priority: 'secondary', key: 'risk-dist' };

export const MODES: Record<ModeId, PresentationMode> = {
  professional_core: {
    id: 'professional_core',
    name: 'Professional',
    greeting: 'Standing by. Ask for anything on the platform and I will put it up.',
    layout: 'auto',
    depth: 'standard',
    density: 12,
    opens: [],
    accent: '#73a7ff',
  },
  market_analyst: {
    id: 'market_analyst',
    name: 'Market analyst',
    greeting: 'Analyst mode. Price, exposure and the headlines moving them.',
    layout: 'auto',
    depth: 'detailed',
    density: 12,
    opens: [GOLD, POSITIONS, NEWS],
    accent: '#73a7ff',
  },
  research_scientist: {
    id: 'research_scientist',
    name: 'Research',
    greeting: 'Research mode. I will show distributions and say what I am uncertain about.',
    layout: 'compare',
    depth: 'detailed',
    density: 12,
    opens: [DIST, GOLD],
    accent: '#8b7dff',
  },
  engineering: {
    id: 'engineering',
    name: 'Engineering',
    greeting: 'Engineering mode. Calls, agents and what the platform is doing.',
    layout: 'split',
    depth: 'detailed',
    density: 12,
    opens: [CALLS, AGENTS],
    accent: '#42d392',
  },
  teaching: {
    id: 'teaching',
    name: 'Teaching',
    greeting: 'Teaching mode. Same numbers, more explanation — I will define the terms as I go.',
    layout: 'focus',
    depth: 'teaching',
    density: 6,
    opens: [RISK],
    accent: '#f5b84b',
  },
  executive_briefing: {
    id: 'executive_briefing',
    name: 'Executive briefing',
    greeting: 'Briefing mode. The headline numbers and nothing else unless you ask.',
    layout: 'presentation',
    depth: 'headline',
    density: 4,
    opens: [RISK],
    accent: '#73a7ff',
  },
  mission_control: {
    id: 'mission_control',
    name: 'Mission control',
    greeting: 'Mission control. Everything at once.',
    layout: 'war_room',
    depth: 'brief',
    density: 20,
    opens: [RISK, GOLD, POSITIONS, NEWS, AGENTS, CALLS],
    accent: '#f5b84b',
  },
  minimal_focus: {
    id: 'minimal_focus',
    name: 'Minimal focus',
    greeting: 'Minimal. One thing at a time.',
    layout: 'focus',
    depth: 'brief',
    density: 3,
    opens: [],
    accent: '#70809a',
  },
  emergency: {
    id: 'emergency',
    name: 'Emergency',
    greeting: 'Something needs you now. Risk and positions are up.',
    layout: 'focus',
    depth: 'headline',
    density: 4,
    opens: [RISK, POSITIONS],
    accent: '#f36d78',
  },
  child_simple: {
    id: 'child_simple',
    name: 'Plain language',
    greeting: 'Plain language mode. Same numbers, ordinary words.',
    layout: 'focus',
    depth: 'teaching',
    density: 4,
    opens: [RISK],
    accent: '#42d392',
  },
};

export const MODE_IDS = Object.keys(MODES) as ModeId[];

export const DEFAULT_MODE: ModeId = 'professional_core';

/**
 * The mode actually in force.
 *
 * A preference, unless something is wrong. `alerting` is derived by
 * `hub/presence.ts` from a tripped kill switch, a dead socket or a stale feed —
 * facts, not moods — and none of those become less true because somebody
 * selected the briefing register five minutes ago.
 */
export function resolveMode(chosen: ModeId | null, presenceState: PresenceState): PresentationMode {
  if (presenceState === 'alerting') return MODES.emergency;
  return MODES[chosen ?? DEFAULT_MODE];
}

/** Read a mode out of what was said. Null when none was named. */
export function readMode(phrase: string): ModeId | null {
  const text = (phrase ?? '').toLowerCase();
  if (/\b(mission control|war room mode|everything at once mode|control room)\b/.test(text)) return 'mission_control';
  if (/\b(executive|briefing|board|summary mode|top line)\b/.test(text)) return 'executive_briefing';
  // Checked before teaching, and `explain like` is deliberately not a teaching
  // trigger: "explain like I'm five" matched it first and landed in the wrong
  // register, which is the more specific phrase losing to the vaguer one.
  if (/\b(plain (english|language)|simple(r)? (words|terms)|like i(?:'?m| am) five|child)\b/.test(text)) return 'child_simple';
  if (/\b(teach me|teaching|tutorial|walk me through)\b/.test(text)) return 'teaching';
  if (/\b(research|scientist|scientific|distributions?)\b/.test(text)) return 'research_scientist';
  if (/\b(engineer(ing)?|developer|debug mode|platform mode)\b/.test(text)) return 'engineering';
  if (/\b(analyst|analysis mode|trading mode|market mode)\b/.test(text)) return 'market_analyst';
  if (/\b(minimal|quiet mode|one thing at a time|declutter)\b/.test(text)) return 'minimal_focus';
  if (/\b(emergency|critical mode|alert mode)\b/.test(text)) return 'emergency';
  if (/\b(normal mode|default mode|professional|standard mode|reset mode)\b/.test(text)) return 'professional_core';
  return null;
}

/**
 * A fact, before anybody has chosen how to say it.
 *
 * Structured rather than pre-formatted so that a mode cannot accidentally
 * reformat a number while rewording a sentence. `value` reaches every register
 * unchanged; only `label`, `context` and the scaffolding move.
 */
export interface Fact {
  /** What it is, in the platform's own vocabulary. */
  label: string;
  /** The number, already rounded by whoever measured it. Never touched here. */
  value: string;
  /** An ordinary-language name for the same thing, for the plain registers. */
  plain?: string;
  /** What the term means. Used by the teaching registers only. */
  meaning?: string;
  /** Where it sits against a limit, when there is one. */
  context?: string;
}

/**
 * Render a fact in a register.
 *
 * The number appears verbatim in every branch. That is asserted by test across
 * all ten modes, because "child mode rounds a drawdown" is exactly the sort of
 * helpfulness that gets somebody stopped out.
 */
export function say(fact: Fact, depth: Depth): string {
  const name = depth === 'teaching' ? (fact.plain ?? fact.label) : fact.label;
  const context = fact.context ? ` ${fact.context}` : '';

  switch (depth) {
    case 'headline':
      return `${fact.label} ${fact.value}.`;
    case 'brief':
      return `${fact.label} ${fact.value}.${context}`;
    case 'detailed':
      return `${fact.label} is ${fact.value}.${context}${fact.meaning ? ` ${fact.meaning}` : ''}`;
    case 'teaching':
      return (
        `${name} is ${fact.value}.` +
        (fact.meaning ? ` ${fact.meaning}` : '') +
        context
      );
    case 'standard':
    default:
      return `${fact.label} is ${fact.value}.${context}`;
  }
}
