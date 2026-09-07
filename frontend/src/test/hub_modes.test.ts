/**
 * §6's ten presentation modes, and the §5 rule that makes them safe:
 * "adapt explanation depth without changing the intelligence."
 *
 * The test that matters most is `every mode reports the same number`. Child-
 * simple mode may say "most of the room you gave yourself for losses" where
 * mission control says "daily loss 4.10% of a 5.00% limit" — and both must be
 * reporting 4.10. A mode that rounded or softened a risk figure to suit its
 * register would be a mode that lies, and an operator glancing at the screen
 * has no way to know which register they are in.
 *
 * Fails on the pre-fix tree — `hub/modes.ts` does not exist there.
 */

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_MODE,
  MODES,
  MODE_IDS,
  readMode,
  resolveMode,
  say,
  type Fact,
  type ModeId,
} from '../hub/modes';
import { LAYOUTS } from '../hub/layout';
import { SURFACE_KINDS } from '../hub/contracts.shared';

const DRAWDOWN: Fact = {
  label: 'Daily loss',
  value: '4.10%',
  plain: 'How much you are down today',
  meaning: 'Daily loss is what you have lost since the session opened.',
  context: 'Your limit is 5.00%.',
};

describe('a mode changes presentation, never the number', () => {
  it('renders the same digits in every register', () => {
    // The one that would cost real money if it failed.
    for (const id of MODE_IDS) {
      const text = say(DRAWDOWN, MODES[id].depth);
      expect(text, `${id} lost the value`).toContain('4.10%');
    }
  });

  it('never drops the limit a number is measured against', () => {
    // "You are down 4.10%" without "of 5.00%" is a different statement.
    for (const id of MODE_IDS) {
      const depth = MODES[id].depth;
      if (depth === 'headline') continue; // headline states the figure alone, by design
      expect(say(DRAWDOWN, depth), `${id} dropped the limit`).toContain('5.00%');
    }
  });

  it('changes the words, so the modes are not all the same sentence', () => {
    // Otherwise this is a colour scheme with ten names.
    const rendered = new Set(MODE_IDS.map((id) => say(DRAWDOWN, MODES[id].depth)));
    expect(rendered.size).toBeGreaterThan(1);
  });

  it('explains the term in the teaching registers and not elsewhere', () => {
    expect(say(DRAWDOWN, 'teaching')).toContain('since the session opened');
    expect(say(DRAWDOWN, 'headline')).not.toContain('since the session opened');
  });

  it('uses ordinary words for the label only where the register asks for it', () => {
    expect(say(DRAWDOWN, 'teaching')).toContain('How much you are down today');
    expect(say(DRAWDOWN, 'standard')).toContain('Daily loss');
  });

  it('survives a fact with nothing but a label and a value', () => {
    const bare: Fact = { label: 'Open risk', value: '1.20%' };
    for (const id of MODE_IDS) {
      const text = say(bare, MODES[id].depth);
      expect(text).toContain('1.20%');
      expect(text).not.toContain('undefined');
    }
  });
});

describe('an alert is a fact, not a register', () => {
  it('promotes emergency over whatever mode was chosen', () => {
    // A kill switch that trips while somebody is in "executive briefing" must
    // not stay quiet because the briefing register is calm.
    for (const id of MODE_IDS) {
      expect(resolveMode(id, 'alerting').id).toBe('emergency');
    }
  });

  it('honours the chosen mode when nothing is wrong', () => {
    expect(resolveMode('teaching', 'idle').id).toBe('teaching');
    expect(resolveMode('mission_control', 'thinking').id).toBe('mission_control');
  });

  it('falls back to the professional core when nothing was chosen', () => {
    expect(resolveMode(null, 'idle').id).toBe(DEFAULT_MODE);
    expect(MODES[DEFAULT_MODE].id).toBe('professional_core');
  });

  it('opens risk and positions in an emergency', () => {
    // The two things somebody woken by an alert needs on screen.
    const keys = MODES.emergency.opens.map((s) => s.key);
    expect(keys).toContain('risk');
    expect(keys).toContain('positions');
  });
});

describe('the registry itself', () => {
  it('has all ten modes §6 names', () => {
    expect(MODE_IDS).toHaveLength(10);
    for (const id of [
      'professional_core', 'market_analyst', 'research_scientist', 'engineering',
      'teaching', 'executive_briefing', 'mission_control', 'minimal_focus',
      'emergency', 'child_simple',
    ]) {
      expect(MODE_IDS).toContain(id as ModeId);
    }
  });

  it('gives every mode a greeting, so the presence introduces itself', () => {
    for (const id of MODE_IDS) {
      expect(MODES[id].greeting.length).toBeGreaterThan(15);
    }
  });

  it('names a layout that exists', () => {
    for (const id of MODE_IDS) expect(LAYOUTS).toContain(MODES[id].layout);
  });

  it('opens only surface kinds that can be drawn', () => {
    // A mode that opens a kind with no renderer greets you with a stated gap.
    for (const id of MODE_IDS) {
      for (const request of MODES[id].opens) {
        expect(SURFACE_KINDS, `${id} opens ${request.kind}`).toContain(request.kind);
      }
    }
  });

  it('keeps every density inside §8ʼs 1-20+ range', () => {
    for (const id of MODE_IDS) {
      expect(MODES[id].density).toBeGreaterThanOrEqual(1);
      expect(MODES[id].density).toBeLessThanOrEqual(20);
    }
  });

  it('makes the focused modes quieter than mission control', () => {
    expect(MODES.minimal_focus.density).toBeLessThan(MODES.mission_control.density);
    expect(MODES.executive_briefing.density).toBeLessThan(MODES.mission_control.density);
  });

  it('gives each mode its own identity rather than one accent for all', () => {
    expect(new Set(MODE_IDS.map((id) => MODES[id].accent)).size).toBeGreaterThan(3);
  });
});

describe('asking for a mode', () => {
  const cases: [string, ModeId][] = [
    ['switch to mission control', 'mission_control'],
    ['give me the executive briefing', 'executive_briefing'],
    ['teach me about this', 'teaching'],
    ['explain like I am five', 'child_simple'],
    ['plain english please', 'child_simple'],
    ['research mode', 'research_scientist'],
    ['engineering mode', 'engineering'],
    ['analyst mode', 'market_analyst'],
    ['minimal please', 'minimal_focus'],
    ['back to normal mode', 'professional_core'],
  ];

  for (const [phrase, expected] of cases) {
    it(`reads ${JSON.stringify(phrase)} as ${expected}`, () => {
      expect(readMode(phrase)).toBe(expected);
    });
  }

  it('returns null rather than guessing on an ordinary question', () => {
    // Otherwise every sentence containing "market" reshapes the whole screen.
    for (const phrase of ['show me gold', 'what is the risk', 'focus on risk', '']) {
      expect(readMode(phrase)).toBeNull();
    }
  });

  it('reaches every mode from at least one phrase', () => {
    // A mode nobody can ask for is a mode that does not exist.
    const reachable = new Set(
      cases.map(([phrase]) => readMode(phrase)).filter((id): id is ModeId => id !== null),
    );
    for (const id of MODE_IDS) {
      if (id === 'emergency') continue; // reached by an alert, and also by phrase
      expect(reachable, `${id} is unreachable`).toContain(id);
    }
    expect(readMode('emergency mode')).toBe('emergency');
  });
});
