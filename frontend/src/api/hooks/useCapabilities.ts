/**
 * ★★ `useCapabilities` — endpoint 3, and **THE UI'S DEFERRAL GATE**.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ SCOPE.md §4 rule 4: *"The UI states it plainly. Deferred features appear
 *    disabled with an honest tooltip ('Automatic matching is not enabled in this
 *    build — place GCPs manually'). **No spinner that never resolves**, no fake
 *    confidence, no placeholder coordinates."*
 *
 *    That rule can only be kept BEFORE the click. Discovering deferral from a `501`
 *    means the request was already fired, and the honest tooltip arrives after the
 *    spinner — which is the thing the rule forbids. So:
 *
 *      - **{@link useIsFeatureDeferred} is the mechanism.** It reads the server's
 *        `deferred_features` list and the control never fires.
 *      - **`isDeferredError` (client.ts) is the backstop**, for a request that got out
 *        anyway (a stale capabilities cache, a race, a direct link).
 *
 * ★★ WHY THE LIST COMES FROM THE SERVER. SCOPE.md §7: *"Implementing the engine must
 *    require **zero changes outside `ai_engine/`**, plus flipping the deferred
 *    endpoints from 501 to live and enabling the UI controls."* A hard-coded
 *    `const DEFERRED = ['matching', …]` in the bundle is precisely a change outside
 *    `ai_engine/` — and one that would be forgotten, leaving the controls dead after
 *    the engine shipped. IU-23's `CapabilitiesResponse.deferred_features` exists so
 *    the UI gates off **one server-provided list**, and this file is its only reader.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import type { CapabilitiesResponse } from '../../types/capabilities';
import { capabilitiesApi } from '../capabilities';
import { qk } from '../queryKeys';

/**
 * Endpoint 3 — `GET /capabilities`.
 *
 * ★ `staleTime: Infinity`. The report is computed ONCE in `main.py`'s lifespan and
 *   cached on `app.state` (§11.1) — it cannot change without an API restart, which
 *   reloads the SPA anyway. Re-fetching it would poll a constant.
 *   `scripts/download_models.py` says the same thing from the other side: new weights
 *   *"require a WORKER RESTART to take effect (preflight is cached)"*.
 */
export function useCapabilities(): UseQueryResult<CapabilitiesResponse> {
  return useQuery({
    queryKey: qk.capabilities(),
    queryFn: ({ signal }) => capabilitiesApi.get(signal),
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

/**
 * The features this build defers (SCOPE.md §1).
 *
 * ★ THESE STRINGS ARE THE SERVER'S TO DEFINE — `models/policy.py` (IU-02/IU-19) emits
 *   `deferred_features`, and this union is the frontend's reading of IU-23's
 *   documented list: *"matching, feature extraction, RANSAC, pose, heatmap,
 *   segmentation, landmark suggestion"*. The exact spellings were never fixed by
 *   contract, so {@link isFeatureDeferred} compares NORMALISED (case- and
 *   separator-insensitive) — `camera_pose`, `camera-pose` and `cameraPose` all match.
 *
 *   ★ That normalisation is a deliberate tolerance, not laziness: if the frontend and
 *     `policy.py` disagreed on a spelling the gate would silently return `false`, the
 *     control would render **enabled**, and the surveyor would get the dead spinner
 *     rule 4 exists to prevent. **A gate that fails silently open is worse than no
 *     gate.** Flagged for IU-19: the strings must match these names.
 */
export type DeferredFeature =
  | 'matching'
  | 'feature_extraction'
  | 'ransac'
  | 'camera_pose'
  | 'heatmap'
  | 'semantic_segmentation'
  | 'landmark_suggestion';

/**
 * ★ Three states, because two would lie.
 *
 *   - `deferred`  — the server said so. Show the honest tooltip.
 *   - `available` — the server said this build has it.
 *   - `unknown`   — capabilities has not loaded, or could not be reached.
 *
 * ★ `unknown` is NOT folded into `deferred`. "Automatic matching is not enabled in
 *   this build" is a **false statement** when the real cause is that the API is
 *   unreachable, and L12 (*refuse rather than answer wrongly*) applies to what the UI
 *   tells a surveyor as much as to a coordinate. A control should be disabled while
 *   `unknown` — you cannot usefully click it either way — but the reason shown must
 *   be the true one.
 */
export type DeferralState = 'deferred' | 'available' | 'unknown';

/** Normalise for comparison: case, hyphens, underscores and spaces are all noise. */
function normalise(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/** Pure predicate over an already-fetched list. Exported for tests and non-hook callers. */
export function isFeatureDeferred(
  deferredFeatures: readonly string[],
  feature: DeferredFeature,
): boolean {
  const target = normalise(feature);
  return deferredFeatures.some((f) => normalise(f) === target);
}

/** The full deferral state of one feature — see {@link DeferralState}. */
export function useFeatureDeferral(feature: DeferredFeature): DeferralState {
  const { data, isSuccess } = useCapabilities();
  if (!isSuccess || data === undefined) return 'unknown';
  return isFeatureDeferred(data.deferred_features, feature) ? 'deferred' : 'available';
}

/**
 * ★ THE GATE. `true` only when the server has CONFIRMED the feature is deferred.
 *
 * ```tsx
 * const deferred = useIsFeatureDeferred('matching');
 * <Button disabled={deferred} title={deferred ? DEFERRED_TOOLTIP.matching : undefined} />
 * ```
 */
export function useIsFeatureDeferred(feature: DeferredFeature): boolean {
  return useFeatureDeferral(feature) === 'deferred';
}

/**
 * The honest tooltips of SCOPE.md §4 rule 4.
 *
 * ★ Strings, not components — IU-24 owns no UI. IU-26/27/28 render them.
 * ★ Every one names **what to do instead**. "Not available" is a dead end; *"place
 *   GCPs manually"* is the product. SCOPE.md §2 is emphatic that manual mode is not a
 *   degraded substitute — it is the path with **no** homography risk, and the
 *   coordinate is a direct observation rather than an inference.
 */
export const DEFERRED_TOOLTIP: Readonly<Record<DeferredFeature, string>> = {
  matching: 'Automatic matching is not enabled in this build — place GCPs manually.',
  feature_extraction:
    'Automatic feature extraction is not enabled in this build — mark landmarks manually.',
  ransac:
    'Homography estimation is not enabled in this build — GCPs are placed by direct observation.',
  camera_pose: 'Camera pose estimation is not enabled in this build.',
  heatmap:
    'The confidence heatmap is not enabled in this build — it is produced by automatic matching.',
  semantic_segmentation:
    'Automatic feature detection is not enabled in this build — annotate manually.',
  landmark_suggestion:
    'Automatic landmark suggestions are not enabled in this build — mark landmarks manually.',
} as const;
