/**
 * hub/vizPalette.ts — the colours the §21 renderers are allowed to use.
 *
 * Not chosen by eye. Every set below was run through the data-viz validator
 * against this workspace's real panel surface, and the output is recorded
 * beside it so a future change can be re-checked rather than re-argued.
 *
 * The surface is `#0f1a2a`: the panel hull
 * (`rgba(16,26,44,.92)` → `rgba(11,19,34,.92)`) composited over the stage void
 * `#070c16`. Validating against `#000` or against the token literal would have
 * measured a background that is not on screen.
 *
 * ## The finding that shaped the network graph
 *
 * A relationship graph wants a colour per category, and the obvious move is to
 * hand out six or eight. Measured on this surface, **three is the ceiling**:
 *
 *   #3987e5, #d95926, #199e70        all-pairs → every check PASS
 *   + #c98500 (yellow)               CVD ΔE 4.8, normal-vision ΔE 10.6 → FAIL
 *   + #9085e9 (violet)               CVD ΔE 1.9, normal-vision ΔE 9.8  → FAIL
 *   + #d55181 (magenta)              CVD ΔE 1.6, normal-vision ΔE 11.6 → FAIL
 *
 * A normal-vision ΔE below 15 means full-colour readers cannot reliably tell
 * the pair apart, and no amount of labelling excuses that — labels rescue
 * colour-vision-deficient readers, not everybody. So the fourth category and
 * beyond fold into `OTHER`, and every node carries its name.
 *
 * ## And the finding that shaped the heatmap
 *
 * The first ramp tried was seven steps of the blue scale. Monotone and single
 * hue, but adjacent steps differed by ΔL ≈ 0.047 — below the 0.06 floor, which
 * is the measured version of "these two cells look the same". Five wider steps
 * pass all four checks. Past about seven bins adjacent classes blur anyway, so
 * this is a ceiling worth having.
 *
 * ## What is deliberately not here
 *
 * The existing `ok`/`warn`/`bad` tokens. Those are **status** colours — they
 * mean tripped, stale, halted — and a status colour reused as "series 4" is a
 * chart that can say the wrong thing. They also measure ΔE 6.6 apart under
 * deuteranopia (red vs green, the classic pair), which is survivable where the
 * platform already pairs them with words and is not survivable as silent
 * category encoding.
 */

/** The composited panel background these were validated against. */
export const VIZ_SURFACE = '#0f1a2a';

/**
 * Sequential intensity, low → high. Five steps of one hue.
 *
 * Validator, dark, surface #0f1a2a, --ordinal:
 *   Lightness monotone  PASS   steps read light→dark
 *   Adjacent ΔL         PASS   all gaps >= 0.06
 *   Light-end contrast  PASS   #184f95 at 2.16:1 vs surface
 *   Single hue          PASS   hue spread 3°
 */
export const INTENSITY = ['#184f95', '#256abf', '#3987e5', '#6da7ec', '#9ec5f4'] as const;

/**
 * Categorical identity. Three, and only three.
 *
 * Validator, dark, surface #0f1a2a, --pairs all:
 *   Lightness band       PASS   all 3 inside L 0.48–0.67
 *   Chroma floor         PASS   all 3 >= 0.1
 *   CVD separation       PASS   worst #199e70↔#d95926 ΔE 9.4 (deutan)
 *   Normal-vision floor  PASS   worst #199e70↔#3987e5 ΔE 20.9
 *   Contrast vs surface  PASS   all 3 >= 3:1
 */
export const CATEGORY = ['#3987e5', '#d95926', '#199e70'] as const;

/**
 * Everything past the third category.
 *
 * Grey rather than a fourth hue: a colour that cannot be told from another
 * colour is worse than an honest "not one of the named three", because the
 * reader believes the first one.
 */
export const OTHER = '#8296b4';

/** Hairline grid and axis. Solid, one shade off the surface — never dashed. */
export const GRID = '#1b2942';

/**
 * Text, measured against the same surface.
 *
 *   primary    #e7edf7   14.86:1
 *   secondary  #a7b5c9    8.40:1
 *   muted      #7d8ca6    5.14:1
 *
 * `muted` is a shade lighter than the stage's own `#70809a`, which measures
 * 4.36:1 here — under the 4.5:1 floor for text. It carries scale ends,
 * timestamps and the "(other)" qualifier, all of which are meaning rather than
 * decoration, so the stage's value was not close enough.
 */
export const INK = {
  primary: '#e7edf7',
  secondary: '#a7b5c9',
  muted: '#7d8ca6',
} as const;

/** Which intensity step a 0-1 value lands in. */
export function intensityStep(value: number): string {
  if (!Number.isFinite(value)) return GRID;
  const clamped = Math.max(0, Math.min(1, value));
  const index = Math.min(INTENSITY.length - 1, Math.floor(clamped * INTENSITY.length));
  return INTENSITY[index] as string;
}

/**
 * The colour for a category, by its position in a stable ordering.
 *
 * Order comes from the caller and must be stable: colour follows the entity,
 * never its rank, so filtering the graph must not repaint the survivors.
 */
export function categoryColour(index: number): string {
  return index < CATEGORY.length ? (CATEGORY[index] as string) : OTHER;
}
