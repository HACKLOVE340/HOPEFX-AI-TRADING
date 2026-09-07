/**
 * hub/a11yPointer.ts — §27 touch and mouse support.
 *
 * The platform is used on desktops and on tablets on a trading desk. A control
 * that only appears on hover is invisible on the tablet, and the failure is
 * silent: nothing errors, the affordance simply never exists for that operator.
 *
 * ## Unknown is not mouse
 *
 * `pointerType` is empty on synthetic events, on some assistive technologies
 * driving the page, and on older WebKit. Defaulting those to `mouse` is exactly
 * how a hover-only control ships: the guess is invisible, and the people it
 * fails are the ones least able to work around it.
 *
 * So an unreadable pointer is `unknown`, and `unknown` is treated as unable to
 * hover. That costs a desktop operator a permanently visible button. It saves a
 * tablet operator a button that does not exist.
 *
 * ## This is a policy, not a device database
 *
 * There is no attempt to detect "is this a touch device". A device can have
 * both, and the operator can switch between them mid-session — the question
 * worth answering is what the *current interaction* came from, which is what a
 * pointer event carries.
 */

export const POINTER_KINDS = ['mouse', 'touch', 'pen', 'unknown'] as const;
export type PointerKind = (typeof POINTER_KINDS)[number];

/** Whether an affordance is drawn all the time or only under a pointer. */
export type AffordanceVisibility = 'always' | 'on-hover';

const KNOWN = new Set<string>(['mouse', 'touch', 'pen']);

/**
 * The kind behind an interaction.
 *
 * Takes a structural shape rather than `PointerEvent` so it can be called from
 * a test, from a React synthetic event, and from a native one without three
 * call sites that disagree.
 */
export function pointerKindFrom(event: { pointerType?: string } | null | undefined): PointerKind {
  const raw = event?.pointerType;
  if (typeof raw === 'string' && KNOWN.has(raw)) return raw as PointerKind;
  return 'unknown';
}

/**
 * Whether this kind needs the affordance drawn permanently.
 *
 * True for everything that cannot hover, and for `unknown` — see the module
 * docstring for why the unmeasured case leans this way.
 */
export function needsPersistentAffordance(kind: PointerKind): boolean {
  return kind !== 'mouse';
}

/**
 * Resolve a component's preference against the pointer in use.
 *
 * A component asks for `on-hover`; this returns `always` when the pointer
 * cannot hover. The component never has to know which kinds those are, so a
 * new one added here reaches every call site at once.
 */
export function affordanceVisibility(kind: PointerKind, preferred: AffordanceVisibility): AffordanceVisibility {
  if (preferred === 'always') return 'always';
  return needsPersistentAffordance(kind) ? 'always' : 'on-hover';
}

/**
 * How far a press may drift and still be a tap.
 *
 * A finger moves; a mouse does not. Sharing one threshold means either the
 * mouse tolerates a drag as a click or the finger cannot tap at all.
 */
export const TAP_SLOP_PX: Readonly<Record<PointerKind, number>> = Object.freeze({
  mouse: 3,
  touch: 10,
  pen: 6,
  unknown: 10,
});

export function describePointer(kind: PointerKind): string {
  if (kind === 'unknown') {
    return 'pointer kind could not be read; treated as unable to hover, so affordances stay visible';
  }
  return needsPersistentAffordance(kind)
    ? `${kind}: cannot hover, so affordances stay visible`
    : `${kind}: can hover, so affordances may appear on hover`;
}
