/**
 * `image/unlinkedGcps.ts` — which committed GCPs must the photo draw DIRECTLY?
 *
 * ★ An annotation-linked GCP is drawn by its annotation (`AnnotationLayer` colours the
 *   shape by the GCP's confidence). A BARE-CLICK GCP has no annotation, so unless the
 *   layer draws it from the GCP's own pixel, its only photo marker was the open
 *   correspondence's — which rightly disappears on commit. The observed bug: commit a
 *   bare-click GCP and the point vanishes from the photograph it was placed on, while
 *   sitting plainly in the table and on the map.
 *
 * ★ A separate module, deliberately: `AnnotationLayer` imports react-konva, whose Node
 *   entry requires the native `canvas` package — so PURE logic living there is untestable
 *   in jsdom. Data-only selection lives here; Konva stays in the component.
 */

import { linkedGcpId } from '../../lib/gcpLink';
import type { AnnotationRead } from '../../types/annotation';
import type { GcpSummary } from '../../types/gcp';

export function unlinkedGcps(
  annotations: readonly AnnotationRead[],
  gcps: readonly GcpSummary[],
): GcpSummary[] {
  const linked = new Set<string>();
  for (const a of annotations) {
    // A DELETED annotation no longer draws, so its GCP must fall through to the
    // direct marker rather than being counted as represented.
    const gcpId = linkedGcpId(a);
    if (!a.is_deleted && gcpId !== null) linked.add(gcpId);
  }
  return gcps.filter((g) => !linked.has(g.id));
}
