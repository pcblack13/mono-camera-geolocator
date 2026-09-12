/**
 * `lib/gcpLink.ts` — which GCP (if any) an annotation is linked to.
 *
 * ★ THE WIRE SENDS `gcp_ids`, NOT `gcp_id`. The annotation presenter attaches the
 *   batched `gcp_ids` list and leaves the legacy scalar `gcp_id` null, so every
 *   consumer that read `annotation.gcp_id` saw "unlinked" for a landmark that had
 *   just been committed as a control point. This is the one place that decides.
 */

import type { AnnotationRead } from '../types/annotation';
import type { Uuid } from '../types/common';

export function linkedGcpId(
  annotation: Pick<AnnotationRead, 'gcp_id'> & { gcp_ids?: readonly Uuid[] | null },
): Uuid | null {
  return annotation.gcp_ids?.[0] ?? annotation.gcp_id ?? null;
}
