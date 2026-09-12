/**
 * ★ `gcp/gcpRows.ts` — the GCP table's view-model. Referenced by `selectionStore`'s
 *   header (*"`linkedId` … populated by `useGcpRows` from `GcpRead.landmark_id`"*), so
 *   this hook is the contract's own assumed assembler; it lives with the table (IU-27).
 *
 * ★ It assembles `GcpTableRow` (a VIEW-MODEL, `types/gcp.ts`) from the SERVER's
 *   `GcpRead`, computing only `display_decimals` (§8.7 — a decimal digit is a claim
 *   about accuracy, so the count is a function of `accuracy.total_ce90_m` and the
 *   band). Every other field is a straight wire field (L9).
 *
 * ★ THE §5 INVARIANT lives here too: rows come from React Query (`useGcps`), i.e. from
 *   the server, which holds only COMMITTED GCPs. An open correspondence is never a row.
 */

import { useMemo } from 'react';

import { useGcps } from '../../api/hooks';
import { gcpConfidenceBand } from '../../theme';
import { displayDecimals } from '../../lib/geo/format';
import { useAnnotationStore } from '../../store/annotationStore';
import type { Uuid } from '../../types/common';
import type { GcpFilters, GcpRead, GcpTableRow } from '../../types/gcp';

/**
 * Project one `GcpRead` to its table row. Pure.
 *
 * ★ `landmark_name` is the linked landmark's label, resolved by the CALLER (which
 *   knows the loaded annotations) and passed in — this stays a pure projection.
 */
export function toGcpTableRow(gcp: GcpRead, landmarkName: string | null = null): GcpTableRow {
  const band = gcpConfidenceBand(gcp);
  return {
    id: gcp.id,
    code: gcp.code,
    image_px: gcp.image_px,
    lat: gcp.lat,
    lon: gcp.lon,
    source: gcp.source,
    confidence: gcp.confidence,
    declared_confidence: gcp.declared_confidence,
    total_ce90_m: gcp.accuracy.total_ce90_m,
    elevation_m: gcp.elevation_m,
    manually_adjusted: gcp.manually_adjusted,
    is_stale: gcp.is_stale,
    pixel_accuracy_within_ceiling: gcp.pixel_accuracy_within_ceiling,
    pixel_accuracy_ceiling_px: gcp.pixel_accuracy_ceiling_px,
    residual_px: gcp.residual_px,
    linked_annotation_id: gcp.landmark_id,
    // ★ The "Name" column: the GCP's own free-text name wins; otherwise the linked
    //   landmark's label (a landmark-placed GCP inherits its name).
    landmark_name: gcp.name ?? landmarkName,
    display_decimals: displayDecimals(gcp.accuracy.total_ce90_m, band),
  };
}

export interface UseGcpRowsResult {
  rows: GcpTableRow[];
  /** Exact filtered count from the server, independent of limit/offset. */
  total: number;
  isLoading: boolean;
  isError: boolean;
  isEmpty: boolean;
}

export function useGcpRows(imageId: Uuid | null, filters?: GcpFilters): UseGcpRowsResult {
  const q = useGcps(imageId, filters);

  // ★ Resolve the linked landmark's name from the loaded annotations. `landmark_id`
  //   is a SERVER id, so map each annotation through its learned server id (a hydrated
  //   annotation's client id already equals its server id — annotationStore header).
  const annotations = useAnnotationStore((s) => s.draft.annotations);
  const serverIdByClientId = useAnnotationStore((s) => s.draft.server_id_by_client_id);

  const nameByLandmarkId = useMemo(() => {
    const map = new Map<string, string | null>();
    for (const a of annotations) {
      const serverId = serverIdByClientId[a.id] ?? a.id;
      map.set(serverId, a.label);
    }
    return map;
  }, [annotations, serverIdByClientId]);

  const rows = useMemo(
    () =>
      (q.data?.items ?? []).map((g) =>
        toGcpTableRow(g, g.landmark_id ? (nameByLandmarkId.get(g.landmark_id) ?? null) : null),
      ),
    [q.data, nameByLandmarkId],
  );

  return {
    rows,
    total: q.data?.total ?? rows.length,
    isLoading: q.isLoading,
    isError: q.isError,
    isEmpty: !q.isLoading && rows.length === 0,
  };
}
