/**
 * hub/a11yLiveRegion.ts — §27 screen-reader semantics: one announcer, not two.
 *
 * `PresenceCore` owns a polite live region. The presence overlay built in
 * Phase P added a second one, and a second polite region is not twice the
 * announcement — screen readers interleave them, so the operator hears half of
 * one sentence, half of another, and no reliable way to tell which is current.
 * That defect was found by reading the diff, which is not a mechanism.
 *
 * This is the mechanism. A component claims a politeness level by name before
 * rendering its region; a second claimant is refused and told who holds it.
 *
 * ## What this deliberately does not do
 *
 * It does not announce anything, and it does not render. It records ownership.
 * A registry that also announced would be tempting to use as "the announcer",
 * and then the region's markup would live somewhere other than the component
 * whose content it describes — which is how a live region ends up announcing a
 * string that has already been replaced on screen.
 *
 * ## Why the same owner may re-claim
 *
 * React mounts effects twice in strict mode, and route changes remount. An
 * idempotent re-claim by the same name is the normal case; refusing it would
 * make the second mount of a component lose the region it already had.
 */

export const POLITENESS = ['polite', 'assertive'] as const;
export type Politeness = (typeof POLITENESS)[number];

export interface Claim {
  granted: boolean;
  /** Who holds the level after this call — the claimant, or the incumbent. */
  owner: string;
  /** Empty when granted. Names the incumbent when refused. */
  reason: string;
}

export class LiveRegionRegistry {
  private owners: Map<Politeness, string> = new Map();

  /**
   * Claim a politeness level.
   *
   * Refusal never displaces the incumbent: two regions announcing at once is
   * the defect, and silently taking the region from the component that already
   * owns it is a second one wearing the fix's clothes.
   */
  claim(politeness: Politeness, owner: string): Claim {
    if (typeof owner !== 'string' || !owner.trim()) {
      throw new Error('a11yLiveRegion: a claim needs a named owner, so a refusal can say who holds the region');
    }
    const held = this.owners.get(politeness) ?? '';
    if (held && held !== owner) {
      return {
        granted: false,
        owner: held,
        reason:
          `the ${politeness} live region is held by ${held}; ` +
          'a second one interleaves with it and the operator hears neither sentence whole',
      };
    }
    this.owners.set(politeness, owner);
    return { granted: true, owner, reason: '' };
  }

  /** Release. Only the holder can; a mistimed unmount must not free somebody else's region. */
  release(politeness: Politeness, owner: string): boolean {
    if (this.owners.get(politeness) !== owner) return false;
    this.owners.delete(politeness);
    return true;
  }

  ownerOf(politeness: Politeness): string {
    return this.owners.get(politeness) ?? '';
  }

  /** Both levels and who holds them. For the developer overlay and for tests. */
  snapshot(): Record<Politeness, string> {
    return { polite: this.ownerOf('polite'), assertive: this.ownerOf('assertive') };
  }
}

/**
 * The one registry the app uses.
 *
 * Process-wide on purpose: a per-component registry would grant every claim and
 * measure nothing, which is the shape of the defect rather than the fix.
 */
export const liveRegions = new LiveRegionRegistry();
