/**
 * How the wait is presented over time (docs/UX-V0.md §7).
 *
 * The expected duration is configuration, never a constant: a whole week takes
 * around thirty seconds on the cloud model and 182 seconds measured on the
 * local 8B. A threshold written into the code would be wrong in one of the two
 * deployments.
 */

export type WaitPhase = "playful" | "slow" | "stalled";

/** Past roughly twice the expected time, the light register is dropped — a
 * joke on the ninetieth second, while the model is stuck, is humiliating. Past
 * three times it, nothing is coming: the plan is written before the endpoint
 * replies, so if it has not landed by now it never will. */
export function waitPhase(elapsedMs: number, expectedMs: number): WaitPhase {
  if (elapsedMs >= expectedMs * 3) return "stalled";
  if (elapsedMs >= expectedMs * 2) return "slow";
  return "playful";
}

/** Rotates through the playful messages on a fixed cadence.
 *
 * Deterministic rather than random: the same wait shows the same sequence,
 * which is testable and, more to the point, never lands twice on the same line
 * in a row. */
export function playfulIndex(elapsedMs: number, count: number, everyMs = 6000): number {
  if (count <= 0) return 0;
  return Math.floor(Math.max(0, elapsedMs) / everyMs) % count;
}

/** Never a percentage and never a bar: there is nothing real to measure, the
 * model returns in one block. A bar that advances on its own and then sits at
 * 90% is worse than no bar. */
export const SHOWS_PROGRESS = false;
