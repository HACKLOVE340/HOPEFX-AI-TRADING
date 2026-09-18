/**
 * hub/a11yFocus.ts — §27 keyboard navigation and focus states.
 *
 * Two defects in this session's own work live here as constants:
 *
 *   * the presence overlay shipped with no focus ring, because the browser
 *     default is close to invisible on a near-black panel and the obvious
 *     remedy — `outline: none` — removes the only indicator a keyboard user
 *     has;
 *   * its dismiss control was a 14px icon in `p-1`, about 22px square. Half
 *     the minimum, on the button an operator reaches for when the assistant
 *     is covering the thing they are trying to read.
 *
 * Both were fixed at the site. Naming them here is what stops the next button
 * from repeating them: `hub_a11y_guard.test.ts` reads every `<button>` in
 * `hub/` and fails the ones that do not carry both.
 *
 * ## Roving focus, and why a list is not a tab stop each
 *
 * A panel of twelve surfaces with twelve tab stops means twelve presses to
 * cross it and no way back. The ARIA authoring practice is one tab stop for
 * the group, arrows inside it. `RovingFocus` holds which item that is; the
 * component asks it for `tabIndexFor` and hands it keys.
 *
 * It throws on an id it does not know rather than returning -1. Returning -1
 * is the failure that hides a typo: the element becomes silently unreachable,
 * which looks exactly like an element that was meant to be skipped.
 */

/**
 * The ring every interactive element in `hub/` carries.
 *
 * `focus-visible` rather than `focus`, so a mouse click does not leave a ring
 * behind — and `outline-none` is only ever paired with the ring that replaces
 * it, never on its own.
 */
export const FOCUS_RING =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 ' +
  'focus-visible:ring-offset-slate-950';

/**
 * The target size for anything an operator reaches for under pressure.
 *
 * WCAG 2.5.5 (AAA) and both platform HIGs land on 44. Every control in the
 * presence chrome is held to it, because those are the controls somebody uses
 * while the assistant is covering the thing they were reading.
 */
export const MIN_HIT_AREA_PX = 44;

/**
 * The absolute floor: WCAG 2.5.8 Target Size (Minimum), AA.
 *
 * Two numbers rather than one, because a single 44px rule applied to every
 * button in `hub/` would be a redesign of the dense panel chrome — a 26px icon
 * in a 34px panel header cannot become 44px without the header growing — and a
 * rule that cannot be followed gets suppressed rather than obeyed.
 *
 * 24 is what the standard actually requires at AA, and it is the number that
 * matters here: the dismiss control that shipped at ~22px failed even this. So
 * `hub_a11y_guard.test.ts` enforces 24 across every hub button and 44 on the
 * ones written in the Tailwind classes below.
 */
export const MIN_TARGET_PX = 24;

/** `MIN_HIT_AREA_PX` in Tailwind's 0.25rem scale: 11 x 4px. */
export const HIT_AREA = 'min-h-11 min-w-11 inline-flex items-center justify-center';

export type Orientation = 'vertical' | 'horizontal' | 'both';

export interface RovingOptions {
  /**
   * Which arrows move focus. `both` is the default because most hub groups are
   * grids; declaring an axis stops the cross-axis arrows from being swallowed,
   * so they still reach the scroll container underneath.
   */
  orientation?: Orientation;
  /** Whether the ends wrap. On by default; a list that stops dead reads as broken. */
  wrap?: boolean;
}

const NEXT_KEYS: Readonly<Record<Orientation, readonly string[]>> = Object.freeze({
  vertical: ['ArrowDown'],
  horizontal: ['ArrowRight'],
  both: ['ArrowDown', 'ArrowRight'],
});

const PREVIOUS_KEYS: Readonly<Record<Orientation, readonly string[]>> = Object.freeze({
  vertical: ['ArrowUp'],
  horizontal: ['ArrowLeft'],
  both: ['ArrowUp', 'ArrowLeft'],
});

/** One tab stop for a group, arrows within it. */
export class RovingFocus {
  private items: string[];
  private current: string;
  private readonly orientation: Orientation;
  private readonly wrap: boolean;

  constructor(items: readonly string[], active?: string, options: RovingOptions = {}) {
    this.items = [...items];
    this.orientation = options.orientation ?? 'both';
    this.wrap = options.wrap ?? true;
    this.current = active !== undefined && this.items.includes(active) ? active : (this.items[0] ?? '');
  }

  /** The item that holds the group's single tab stop. Empty when there are none. */
  get active(): string {
    return this.current;
  }

  /** The ids, in the order the arrows walk them. */
  get order(): readonly string[] {
    return [...this.items];
  }

  /**
   * `0` for the active item, `-1` for the rest.
   *
   * Throws on an unknown id. See the module docstring: -1 would make a typo
   * indistinguishable from a deliberate skip.
   */
  tabIndexFor(id: string): 0 | -1 {
    if (!this.items.includes(id)) {
      throw new Error(
        `a11yFocus: ${id} is not in this roving group (${this.items.join(', ') || 'empty'}); ` +
          'returning -1 would make it silently unreachable',
      );
    }
    return id === this.current ? 0 : -1;
  }

  setActive(id: string): void {
    if (!this.items.includes(id)) {
      throw new Error(`a11yFocus: cannot focus ${id}; it is not in this roving group`);
    }
    this.current = id;
  }

  /**
   * Replace the list, keeping focus where it was if that item survived.
   *
   * A panel closing must not send focus to nowhere: if the active item left,
   * focus re-anchors to the first remaining one, and to nothing only when
   * nothing remains.
   */
  setItems(items: readonly string[]): void {
    this.items = [...items];
    if (!this.items.includes(this.current)) this.current = this.items[0] ?? '';
  }

  /**
   * Handle a key. Returns the newly focused id, or `null` when the key is not
   * this group's — so the caller knows whether to call `preventDefault`, and an
   * unhandled Escape or Tab still reaches whatever is listening above.
   */
  onKey(key: string): string | null {
    if (this.items.length === 0) return null;
    const index = this.items.indexOf(this.current);
    const at = index >= 0 ? index : 0;

    let target: number | null = null;
    if (NEXT_KEYS[this.orientation].includes(key)) target = at + 1;
    else if (PREVIOUS_KEYS[this.orientation].includes(key)) target = at - 1;
    else if (key === 'Home') target = 0;
    else if (key === 'End') target = this.items.length - 1;
    if (target === null) return null;

    if (target < 0 || target >= this.items.length) {
      if (!this.wrap) return null;
      target = (target + this.items.length) % this.items.length;
    }

    this.current = this.items[target] ?? '';
    return this.current;
  }
}
