/**
 * Phase G — §27 accessibility.
 *
 * Four accessibility defects were found in this session's own work, after the
 * code had been written and read: no focus rings on the presence overlay,
 * 22px hit areas on the control an operator reaches for when the assistant is
 * in their way, `text-slate-500` measured at 4.21:1 against a 4.5:1 floor, and
 * a second polite live region competing with the one `PresenceCore` already
 * owns.
 *
 * Each was fixed once. Fixed once is not the same as unrepeatable: the next
 * button added to the overlay can still omit the ring, the next muted colour
 * can still be picked by eye, and the next component that wants to announce
 * something can still add its own `aria-live`. So these tests are written
 * against a contract, not against the four sites — the numbers are MEASURED
 * here rather than asserted in a comment, and `hub_a11y_guard.test.ts` scans
 * for the shapes that would reintroduce them.
 */

import { describe, expect, it, beforeEach } from 'vitest';

import {
  CONTRAST_MODES,
  FORBIDDEN_TEXT,
  LARGE_TEXT_FLOOR,
  NON_TEXT_FLOOR,
  SURFACES,
  TEXT_FLOOR,
  contrastRatio,
  describeContrast,
  meetsContrast,
  textPalette,
} from '../hub/a11yContrast';
import { FOCUS_RING, HIT_AREA, MIN_HIT_AREA_PX, RovingFocus } from '../hub/a11yFocus';
import { LiveRegionRegistry, POLITENESS } from '../hub/a11yLiveRegion';
import { MOTION_LEVELS, motionFor, scaleDuration } from '../hub/a11yMotion';
import { POINTER_KINDS, affordanceVisibility, needsPersistentAffordance, pointerKindFrom } from '../hub/a11yPointer';
import { BREAKPOINTS, breakpointFor } from '../hub/a11yBreakpoints';

describe('§27 contrast — measured, never asserted', () => {
  it('computes the WCAG ratio the specification defines', () => {
    // The two anchors of the scale. If these are wrong, nothing below means
    // anything, so they are checked against the published values rather than
    // against this implementation's own output.
    expect(contrastRatio('#ffffff', '#000000')).toBeCloseTo(21, 2);
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
    // A published worked example: #767676 on white is the canonical 4.54:1
    // "just passes" grey.
    expect(contrastRatio('#767676', '#ffffff')).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio('#777777', '#ffffff')).toBeLessThan(4.6);
  });

  it('is symmetric, because a ratio has no foreground', () => {
    expect(contrastRatio('#3987e5', '#0f1a2a')).toBeCloseTo(contrastRatio('#0f1a2a', '#3987e5'), 10);
  });

  it('refuses a colour it cannot read rather than scoring it', () => {
    // A silently-zero luminance would score an unparseable token as maximum
    // contrast against a dark surface — the palette would pass by being broken.
    expect(() => contrastRatio('not-a-colour', '#000000')).toThrow(/hex/i);
    expect(() => contrastRatio('#12345', '#000000')).toThrow(/hex/i);
  });

  it('accepts the three-digit and eight-digit forms the codebase actually uses', () => {
    expect(contrastRatio('#fff', '#000')).toBeCloseTo(21, 2);
    expect(contrastRatio('#ffffffff', '#000000ff')).toBeCloseTo(21, 2);
  });

  describe.each(CONTRAST_MODES)('every %s text token on every surface', (mode) => {
    const palette = textPalette(mode);

    it('has at least one token, so an empty palette cannot pass vacuously', () => {
      expect(Object.keys(palette).length).toBeGreaterThan(0);
    });

    for (const [surfaceName, surface] of Object.entries(SURFACES)) {
      for (const [tokenName, hex] of Object.entries(palette)) {
        it(`${tokenName} on ${surfaceName} clears the floor`, () => {
          const floor = mode === 'high' ? 7 : TEXT_FLOOR;
          const measured = contrastRatio(hex, surface);
          expect(
            measured,
            `${tokenName} (${hex}) on ${surfaceName} (${surface}) measured ${measured.toFixed(2)}:1`,
          ).toBeGreaterThanOrEqual(floor);
        });
      }
    }
  });

  it('records why each forbidden colour is forbidden, and re-measures it', () => {
    expect(Object.keys(FORBIDDEN_TEXT).length).toBeGreaterThan(0);
    for (const [name, entry] of Object.entries(FORBIDDEN_TEXT)) {
      const measured = contrastRatio(entry.hex, SURFACES[entry.surface]);
      expect(measured, `${name} measured ${measured.toFixed(2)}:1`).toBeLessThan(TEXT_FLOOR);
      // The stated reason has to carry the ratio this run measured. A
      // prohibition whose number was typed once goes stale silently, and then
      // reads as a measurement when it is a memory — which is how the 4.21:1
      // figure from an earlier surface would have survived into a palette
      // where it no longer applies.
      expect(entry.reason, `${name}: reason does not carry ${measured.toFixed(2)}`).toContain(
        measured.toFixed(2),
      );
    }
  });

  it('names the greys that were actually reached for, so they cannot come back', () => {
    expect(FORBIDDEN_TEXT['text-slate-500']).toBeDefined();
    expect(FORBIDDEN_TEXT['text-slate-600']).toBeDefined();
  });

  it('applies the large-text and non-text floors where the standard does', () => {
    expect(LARGE_TEXT_FLOOR).toBe(3);
    expect(NON_TEXT_FLOOR).toBe(3);
    const borderline = '#6f7d90';
    expect(meetsContrast(borderline, SURFACES.panel, { large: true })).toBe(
      contrastRatio(borderline, SURFACES.panel) >= LARGE_TEXT_FLOOR,
    );
    expect(meetsContrast(borderline, SURFACES.panel)).toBe(
      contrastRatio(borderline, SURFACES.panel) >= TEXT_FLOOR,
    );
  });

  it('describes a pair in words that carry the number', () => {
    const said = describeContrast('#ffffff', '#000000');
    expect(said).toContain('21');
    expect(said).toMatch(/pass/i);
    expect(describeContrast('#111111', '#000000')).toMatch(/fail/i);
  });
});

describe('§27 focus — one ring, one hit area, named once', () => {
  it('replaces the outline it removes', () => {
    // The defect this exists to prevent is `outline: none` with nothing after
    // it, which removes the only indicator a keyboard user has.
    expect(FOCUS_RING).toContain('focus-visible:outline-none');
    expect(FOCUS_RING).toMatch(/focus-visible:ring-\d/);
  });

  it('states the minimum hit area as a number and as the class that achieves it', () => {
    expect(MIN_HIT_AREA_PX).toBe(44);
    // Tailwind's scale is 0.25rem per step: 11 * 4px = 44px.
    expect(HIT_AREA).toContain(`min-h-${MIN_HIT_AREA_PX / 4}`);
    expect(HIT_AREA).toContain(`min-w-${MIN_HIT_AREA_PX / 4}`);
  });
});

describe('§27 roving focus — one tab stop, arrows inside', () => {
  it('makes exactly one item tabbable', () => {
    const roving = new RovingFocus(['a', 'b', 'c']);
    const stops = ['a', 'b', 'c'].filter((id) => roving.tabIndexFor(id) === 0);
    expect(stops).toEqual(['a']);
    expect(roving.tabIndexFor('b')).toBe(-1);
  });

  it('throws on an id it does not know, rather than reporting -1', () => {
    // -1 for an unknown id is the failure mode that hides a typo: the element
    // silently becomes unreachable and nothing says so.
    const roving = new RovingFocus(['a', 'b']);
    expect(() => roving.tabIndexFor('c')).toThrow(/c/);
  });

  it('moves with the arrows and wraps at both ends', () => {
    const roving = new RovingFocus(['a', 'b', 'c']);
    expect(roving.onKey('ArrowDown')).toBe('b');
    expect(roving.active).toBe('b');
    expect(roving.onKey('ArrowDown')).toBe('c');
    expect(roving.onKey('ArrowDown')).toBe('a');
    expect(roving.onKey('ArrowUp')).toBe('c');
  });

  it('honours Home and End', () => {
    const roving = new RovingFocus(['a', 'b', 'c'], 'b');
    expect(roving.onKey('End')).toBe('c');
    expect(roving.onKey('Home')).toBe('a');
  });

  it('ignores the cross-axis keys when an orientation is declared', () => {
    const vertical = new RovingFocus(['a', 'b'], 'a', { orientation: 'vertical' });
    expect(vertical.onKey('ArrowRight')).toBeNull();
    expect(vertical.active).toBe('a');
    expect(vertical.onKey('ArrowDown')).toBe('b');

    const horizontal = new RovingFocus(['a', 'b'], 'a', { orientation: 'horizontal' });
    expect(horizontal.onKey('ArrowDown')).toBeNull();
    expect(horizontal.onKey('ArrowRight')).toBe('b');
  });

  it('returns null for a key it does not handle, so the event still bubbles', () => {
    const roving = new RovingFocus(['a', 'b']);
    expect(roving.onKey('Escape')).toBeNull();
    expect(roving.onKey('Tab')).toBeNull();
  });

  it('keeps the active item across a list change, and re-anchors when it goes', () => {
    const roving = new RovingFocus(['a', 'b', 'c'], 'b');
    roving.setItems(['a', 'b']);
    expect(roving.active).toBe('b');
    roving.setItems(['a', 'c']);
    // 'b' left the list; focus has to land somewhere real rather than nowhere.
    expect(roving.active).toBe('a');
  });

  it('survives an empty list without inventing a focused item', () => {
    const roving = new RovingFocus([]);
    expect(roving.active).toBe('');
    expect(roving.onKey('ArrowDown')).toBeNull();
    expect(() => roving.tabIndexFor('a')).toThrow();
  });
});

describe('§27 live regions — one owner per politeness', () => {
  let regions: LiveRegionRegistry;
  beforeEach(() => {
    regions = new LiveRegionRegistry();
  });

  it('offers exactly the two politeness levels ARIA defines', () => {
    expect([...POLITENESS]).toEqual(['polite', 'assertive']);
  });

  it('grants the first claim and names the owner', () => {
    const claim = regions.claim('polite', 'PresenceCore');
    expect(claim.granted).toBe(true);
    expect(regions.ownerOf('polite')).toBe('PresenceCore');
  });

  it('refuses a second owner and says who holds it', () => {
    regions.claim('polite', 'PresenceCore');
    const second = regions.claim('polite', 'PresenceAnywhere');
    expect(second.granted).toBe(false);
    expect(second.reason).toContain('PresenceCore');
    // The region did not change hands: two regions announcing at once is the
    // defect, and losing the first one to the second is a different defect.
    expect(regions.ownerOf('polite')).toBe('PresenceCore');
  });

  it('lets the same owner re-claim, because React mounts twice in strict mode', () => {
    expect(regions.claim('polite', 'PresenceCore').granted).toBe(true);
    expect(regions.claim('polite', 'PresenceCore').granted).toBe(true);
  });

  it('keeps polite and assertive separate, because an alert must interrupt', () => {
    regions.claim('polite', 'PresenceCore');
    expect(regions.claim('assertive', 'PresenceAnywhere').granted).toBe(true);
  });

  it('releases only to its own owner', () => {
    regions.claim('polite', 'PresenceCore');
    expect(regions.release('polite', 'Impostor')).toBe(false);
    expect(regions.ownerOf('polite')).toBe('PresenceCore');
    expect(regions.release('polite', 'PresenceCore')).toBe(true);
    expect(regions.ownerOf('polite')).toBe('');
    expect(regions.claim('polite', 'PresenceAnywhere').granted).toBe(true);
  });

  it('refuses an anonymous claim', () => {
    // An unnamed owner cannot be reported in the refusal message, which makes
    // the whole mechanism unable to say what went wrong.
    expect(() => regions.claim('polite', '  ')).toThrow(/owner/i);
  });
});

describe('§27 motion — the accessibility setting is a floor, not a vote', () => {
  it('offers three levels', () => {
    expect([...MOTION_LEVELS]).toEqual(['full', 'reduced', 'none']);
  });

  it('stops motion when the operator asked for it, on any machine', () => {
    const decided = motionFor({ prefersReduced: true, fidelity: 'full' });
    expect(decided.level).toBe('none');
    expect(decided.reason).toMatch(/reduced|prefer/i);
  });

  it('stops motion when the preference could not be read', () => {
    // Same reasoning as `usePrefersReducedMotion`: for some people this
    // setting is medical, and a wrong guess causes symptoms rather than
    // disappointment. An unmeasured preference is not "no preference".
    const decided = motionFor({ fidelity: 'full' });
    expect(decided.level).toBe('none');
    expect(decided.reason).toMatch(/not read|unknown|unmeasured/i);
  });

  it('takes the lower of the preference and what the machine can afford', () => {
    expect(motionFor({ prefersReduced: false, fidelity: 'full' }).level).toBe('full');
    expect(motionFor({ prefersReduced: false, fidelity: 'reduced' }).level).toBe('reduced');
    expect(motionFor({ prefersReduced: false, fidelity: 'minimal' }).level).toBe('none');
  });

  it('scales a duration to zero at "none", never to a token 1ms', () => {
    expect(scaleDuration('full', 200)).toBe(200);
    expect(scaleDuration('reduced', 200)).toBeLessThan(200);
    expect(scaleDuration('reduced', 200)).toBeGreaterThan(0);
    expect(scaleDuration('none', 200)).toBe(0);
  });
});

describe('§27 touch and mouse — parity, not a hover-only app', () => {
  it('names the pointer kinds the platform can see', () => {
    expect([...POINTER_KINDS]).toEqual(['mouse', 'touch', 'pen', 'unknown']);
  });

  it('reads the kind off a pointer event', () => {
    expect(pointerKindFrom({ pointerType: 'mouse' })).toBe('mouse');
    expect(pointerKindFrom({ pointerType: 'touch' })).toBe('touch');
    expect(pointerKindFrom({ pointerType: 'pen' })).toBe('pen');
  });

  it('reports unknown rather than guessing mouse', () => {
    // Guessing mouse is how a control ends up hover-only on a tablet: the
    // guess is invisible and the affordance simply never appears.
    expect(pointerKindFrom({})).toBe('unknown');
    expect(pointerKindFrom({ pointerType: 'wand' })).toBe('unknown');
    expect(pointerKindFrom(null)).toBe('unknown');
  });

  it('requires a persistent affordance for everything that cannot hover', () => {
    expect(needsPersistentAffordance('touch')).toBe(true);
    expect(needsPersistentAffordance('pen')).toBe(true);
    expect(needsPersistentAffordance('unknown')).toBe(true);
    expect(needsPersistentAffordance('mouse')).toBe(false);
  });

  it('overrides a hover-only preference for those kinds', () => {
    expect(affordanceVisibility('mouse', 'on-hover')).toBe('on-hover');
    expect(affordanceVisibility('touch', 'on-hover')).toBe('always');
    expect(affordanceVisibility('unknown', 'on-hover')).toBe('always');
    expect(affordanceVisibility('mouse', 'always')).toBe('always');
  });
});

describe('§27 responsive — one definition of narrow', () => {
  it('names the breakpoints in ascending order', () => {
    expect(BREAKPOINTS.narrow).toBeLessThan(BREAKPOINTS.medium);
    expect(BREAKPOINTS.medium).toBeLessThan(BREAKPOINTS.wide);
  });

  it('classifies a width into exactly one band', () => {
    expect(breakpointFor(375)).toBe('narrow');
    expect(breakpointFor(BREAKPOINTS.narrow - 1)).toBe('narrow');
    expect(breakpointFor(BREAKPOINTS.narrow)).toBe('medium');
    expect(breakpointFor(768)).toBe('medium');
    expect(breakpointFor(BREAKPOINTS.medium)).toBe('wide');
    expect(breakpointFor(1440)).toBe('wide');
  });

  it('treats an unreadable width as the narrowest, never the widest', () => {
    // A wide guess renders a six-column plane onto a phone. A narrow guess
    // renders one column onto a desktop: recoverable, and visibly wrong.
    expect(breakpointFor(0)).toBe('narrow');
    expect(breakpointFor(Number.NaN)).toBe('narrow');
    expect(breakpointFor(-1)).toBe('narrow');
  });
});
