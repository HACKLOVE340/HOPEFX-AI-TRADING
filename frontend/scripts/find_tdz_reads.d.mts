/**
 * Types for scripts/find_tdz_reads.mjs, so `src/test/no_render_time_tdz.test.tsx`
 * can import the scanner under `strict` without an implicit `any`.
 */

export interface TdzFinding {
  /** Absolute path of the file containing the read. */
  file: string;
  /** Name of the block-scoped binding read before it was initialised. */
  name: string;
  /** 1-based line of the read. */
  readLine: number;
  /** 1-based line of the declaration. Always greater than `readLine`. */
  declLine: number;
}

/**
 * Walk every `.ts`/`.tsx` file under `root` and report block-scoped variables
 * read during the render pass above their own declaration.
 */
export function scan(root?: string): TdzFinding[];
