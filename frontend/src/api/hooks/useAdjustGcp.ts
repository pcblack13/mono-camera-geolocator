/**
 * ★★ `useAdjustGcp` / `useResetGcp` — refine a placed GCP, or put it back.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ §8.5 IS NORMATIVE HERE, AND IT VOIDS 50-frontend's DESIGN IN FIVE PARTS:
 *
 *   - **`POST /gcps/{id}/adjust` does not exist.** Endpoint 40 is
 *     `PATCH /gcps/{gcp_id}` with **`If-Match` REQUIRED**.
 *   - **`imagePixel` is forbidden there.** Moving the point on the photograph is
 *     `PATCH /annotations/{id}`. Two endpoints, two meanings: *"the coordinate is in
 *     the wrong place"* vs *"I marked the wrong pixel"*. `GcpUpdate` has no
 *     `image_px`, so this is enforced by the type, not by review.
 *   - **`pinned` exists on neither `GcpUpdate` nor the `gcps` table.**
 *   - **Adjusted confidence is NOT rendered as "manual"** and a manual adjustment does
 *     **not** set `confidence = 100`. Overwriting it destroys the only record of how
 *     well the algorithm did and asserts a certainty the human never claimed. Human
 *     certainty is carried by `manually_adjusted` + `adjustment_offset_m` +
 *     `adjusted_by` + the note.
 *   - **There is no `AdjustGcpCommand`.** GCP adjustment is not in the undo stack
 *     (`commands.ts` is annotations only); it routes through this optimistic mutation.
 *
 * ★ SCOPE.md §5 adds the manual-mode reading: *"The pairing is editable and
 *   re-openable: either endpoint can be dragged and re-committed"*, and
 *   `declared_confidence` — the surveyor's own judgement — is revisable through the
 *   same PATCH.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type { GcpRead, GcpResetRequest, GcpUpdate } from '../../types/gcp';
import { gcpsApi } from '../gcps';
import { qk } from '../queryKeys';

export interface AdjustGcpVariables {
  gcpId: Uuid;
  body: GcpUpdate;
  /**
   * ★ The `If-Match` value. **Optional only because the client keeps a registry** of
   *   the last `ETag` seen per path (see `client.ts`), which `useGcp(id)` populates.
   *   Pass it explicitly when you have a fresher one.
   *
   *   With neither, the server answers `428 PRECONDITION_REQUIRED` — loudly, which is
   *   correct: a silent unconditional write is a lost update, and this row is a survey
   *   coordinate.
   */
  etag?: string;
}

interface AdjustContext {
  previousDetail: GcpRead | undefined;
  previousLists: [readonly unknown[], unknown][];
}

/** Apply a partial GCP change to a cached row. Mirrors only what `GcpUpdate` may set. */
function applyOptimistic(gcp: GcpRead, body: GcpUpdate): GcpRead {
  return {
    ...gcp,
    ...(body.lat !== undefined ? { lat: body.lat } : {}),
    ...(body.lon !== undefined ? { lon: body.lon } : {}),
    ...(body.satellite_px !== undefined ? { satellite_px: body.satellite_px } : {}),
    ...(body.image_px !== undefined ? { image_px: body.image_px } : {}),
    ...(body.code !== undefined ? { code: body.code } : {}),
    ...(body.declared_confidence !== undefined
      ? { declared_confidence: body.declared_confidence }
      : {}),
    ...(body.is_included_in_export !== undefined
      ? { is_included_in_export: body.is_included_in_export }
      : {}),
    ...(body.adjustment_note !== undefined ? { adjustment_note: body.adjustment_note } : {}),
    // ★ NOT optimistically set: `confidence`, `accuracy`, `adjustment_offset_m`,
    //   `manually_adjusted`, `original`, `adjusted_at`. Every one of them is the
    //   SERVER'S to compute — `adjustment_offset_m` is a geodesic `ST_Distance`, and
    //   `accuracy` comes from the imagery's GSD at the new location. Guessing them
    //   would render a fabricated survey figure for the length of a round trip, and
    //   §8.7 would derive the displayed decimal count from the guess.
  };
}

/** `true` for a cached `Page<GcpRead>`; `false` for the geojson variant or anything else. */
function isGcpPage(value: unknown): value is Page<GcpRead> {
  return (
    typeof value === 'object' && value !== null && Array.isArray((value as Page<GcpRead>).items)
  );
}

/**
 * ★ Endpoint 40 — `PATCH /gcps/{id}`, `If-Match` REQUIRED.
 *
 * ★ OPTIMISTIC, with rollback. §8.5: *"`useAdjustGcp` moves the dragged point
 *   optimistically but **dims** its neighbours rather than showing stale-but-confident
 *   coordinates — we cannot predict a server-side homography re-estimate."*
 *
 * ★★ **In this build there are no neighbours to dim**, and that is a consequence of
 *    the ruling worth stating: with the matching engine deferred, every GCP is an
 *    independent direct observation (SCOPE.md §2 — *"There is no homography, so there
 *    are no degenerate solves"*). Moving one cannot move another, because no shared
 *    fit connects them. The dimming affordance is IU-27's to render **if and when the
 *    engine lands**; this hook touches only the row being adjusted, which is exactly
 *    correct now and remains correct then (the server's response is authoritative and
 *    `onSettled` re-reads the list either way).
 *
 * @param imageId Scopes list invalidation. Pass `null` when the image is not known;
 *                the detail cache is still updated and the lists are left to refetch.
 */
export function useAdjustGcp(
  imageId: Uuid | null,
): UseMutationResult<GcpRead, unknown, AdjustGcpVariables, AdjustContext> {
  const queryClient = useQueryClient();

  return useMutation<GcpRead, unknown, AdjustGcpVariables, AdjustContext>({
    mutationFn: ({ gcpId, body, etag }) => gcpsApi.update(gcpId, body, etag),

    onMutate: async ({ gcpId, body }) => {
      // Stop in-flight reads from landing on top of the optimistic value.
      await queryClient.cancelQueries({ queryKey: qk.gcps.detail(gcpId) });
      if (imageId !== null)
        await queryClient.cancelQueries({ queryKey: qk.gcps.forImage(imageId) });

      const previousDetail = queryClient.getQueryData<GcpRead>(qk.gcps.detail(gcpId));
      const previousLists: [readonly unknown[], unknown][] = [];

      if (previousDetail !== undefined) {
        queryClient.setQueryData(qk.gcps.detail(gcpId), applyOptimistic(previousDetail, body));
      }

      if (imageId !== null) {
        // Every filtered variant of this image's list may hold the row.
        for (const [key, data] of queryClient.getQueriesData({
          queryKey: qk.gcps.forImage(imageId),
        })) {
          previousLists.push([key, data]);
          if (!isGcpPage(data)) continue; // the geojson variant — left to refetch
          queryClient.setQueryData(key, {
            ...data,
            items: data.items.map((g) => (g.id === gcpId ? applyOptimistic(g, body) : g)),
          });
        }
      }

      return { previousDetail, previousLists };
    },

    onError: (_error, { gcpId }, context) => {
      // ★ ROLL BACK. A failed adjustment that left the optimistic coordinate on screen
      //   would show a number the server rejected — the worst possible outcome for a
      //   field that gets pasted into a legal document. A `412` in particular means
      //   someone else moved it, so our value is doubly wrong.
      if (context?.previousDetail !== undefined) {
        queryClient.setQueryData(qk.gcps.detail(gcpId), context.previousDetail);
      }
      for (const [key, data] of context?.previousLists ?? []) {
        queryClient.setQueryData(key, data);
      }
    },

    onSuccess: (gcp) => {
      // ★ The server's row is authoritative — it carries the recomputed `accuracy`,
      //   `adjustment_offset_m` and `manually_adjusted` that `applyOptimistic`
      //   deliberately refused to guess.
      queryClient.setQueryData(qk.gcps.detail(gcp.id), gcp);
    },

    onSettled: (_data, _error, { gcpId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.gcps.detail(gcpId) });
      void queryClient.invalidateQueries({ queryKey: qk.gcps.overviews() });
      if (imageId !== null)
        void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
    },
  });
}

export interface ResetGcpVariables {
  gcpId: Uuid;
  body?: GcpResetRequest;
}

/**
 * Endpoint 41 — `POST /gcps/{id}/reset` → `200 GcpRead`. **Idempotent.**
 *
 * ★ Restores `original` — the pre-adjustment answer, written once and kept forever so
 *   the record of what was originally produced survives every later edit.
 *   `422 GCP_ORIGINAL_UNAVAILABLE` when the GCP was never adjusted.
 *
 * ★ NOT OPTIMISTIC. The point of a reset is to get the *server's* stored `original`
 *   back; predicting it client-side would mean the client already had it, and if the
 *   client's copy were stale the reset would appear to restore the wrong coordinate.
 *   One round trip, and the answer is the truth.
 */
export function useResetGcp(
  imageId: Uuid | null,
): UseMutationResult<GcpRead, unknown, ResetGcpVariables> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ gcpId, body }: ResetGcpVariables) =>
      gcpsApi.reset(gcpId, body ?? { confirm: true }),
    onSuccess: (gcp) => {
      queryClient.setQueryData(qk.gcps.detail(gcp.id), gcp);
      if (imageId !== null)
        void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
    },
  });
}
