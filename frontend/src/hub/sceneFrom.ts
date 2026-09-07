/**
 * hub/sceneFrom.ts — the producer `sceneGraph.ts` was missing.
 *
 * §9 asks for a scene model carrying identity, position, size, z-order,
 * content and meaning. `sceneGraph.ts` holds the model and answers the
 * relative questions; measured just before this file was written, it was
 * constructed in **zero** production modules. `gestures.ts` imports the type.
 * A scene graph nothing places panels into answers every question with a throw
 * — `hopefx-dead-controls` with a spatial API on it.
 *
 * `PresenceStage` already reads every panel's `getBoundingClientRect()` once a
 * frame, derives which ninth of the screen it sits in, and discards the
 * rectangle. This is the same measurement, kept.
 *
 * ## An unmeasured rectangle is not a panel at the origin
 *
 * `getBoundingClientRect()` on an element that has not been laid out returns
 * all zeros, and `spatial.positionOf` already refuses to call that "top left".
 * The same refusal applies here and matters more: a zero rect placed in the
 * scene sits at the origin, so it wins "the panel on the far left" — and the
 * AI points an operator at a panel that is not on their screen.
 *
 * ## Containment is declared, never inferred
 *
 * The obvious inference is that a rectangle inside another rectangle is inside
 * it. It is wrong here twice over: panels in a grid never contain each other,
 * and two panels transiently overlap during a layout change. Inferring would
 * report "the gold chart is inside the order ticket" for one frame, and §9's
 * whole point is answering "inside what" correctly.
 *
 * So `parent` is passed in by the caller that knows — a war-room container
 * naming its children — and a parent that was not itself measured is refused
 * rather than silently dropped.
 */

import { SceneGraph } from './sceneGraph';
import type { Rect } from './spatial';

export interface Measurement {
  id: string;
  rect: Rect;
  /**
   * The container this panel is inside, if the caller knows of one.
   *
   * Must appear earlier in the same list. A parent measured after its child
   * cannot be placed first, and `SceneGraph.place` refuses a parent that does
   * not exist yet — which is the correct refusal, surfaced here with the
   * caller's own id in it.
   */
  parent?: string;
}

/**
 * Build a populated scene from one measurement pass.
 *
 * `z` is the index in the list, which for a DOM query is paint order. Leaving
 * every node at 0 would make `occludedBy` return nothing for every pair
 * whatever they overlap — indistinguishable, to a reader, from "nothing is
 * covered".
 */
export function sceneFrom(measurements: readonly Measurement[]): SceneGraph {
  const scene = new SceneGraph();
  let z = 0;
  for (const { id, rect, parent } of measurements) {
    if (!id || !id.trim()) continue;
    if (!isLaidOut(rect)) continue;
    if (parent !== undefined && !scene.ids().includes(parent)) {
      throw new Error(
        `sceneFrom: ${id} names ${parent} as its container, and ${parent} was not measured; ` +
          'a container must appear earlier in the same pass',
      );
    }
    scene.place(id, rect, { parent: parent ?? null, z });
    z += 1;
  }
  return scene;
}

/** A rect with no area was never laid out. See the module docstring. */
function isLaidOut(rect: Rect): boolean {
  return (
    Number.isFinite(rect.width) &&
    Number.isFinite(rect.height) &&
    Number.isFinite(rect.x) &&
    Number.isFinite(rect.y) &&
    rect.width > 0 &&
    rect.height > 0
  );
}
