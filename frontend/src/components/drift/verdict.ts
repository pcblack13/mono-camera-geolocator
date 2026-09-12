/**
 * `drift/verdict.ts` — which verdict is the one to show.
 *
 * ★ THE NEWEST READING WINS, whoever produced it. The strip used to prefer the
 *   monitor's last verdict unconditionally — so a watch that had been STOPPED, or a
 *   watch on an older reference of the same camera, kept outranking a fresh
 *   "Check now" and the button looked dead. Time is the only honest tiebreak.
 */

import type { DriftVerdict } from '../../api/drift';

export function freshestVerdict(
  ...candidates: ReadonlyArray<DriftVerdict | null | undefined>
): DriftVerdict | null {
  let best: DriftVerdict | null = null;
  for (const v of candidates) {
    if (v == null) continue;
    if (best === null || v.checked_utc > best.checked_utc) best = v;
  }
  return best;
}
