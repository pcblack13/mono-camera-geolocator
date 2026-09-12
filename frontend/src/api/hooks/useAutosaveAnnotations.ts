/**
 * ★ Autosave the annotation draft to the server, debounced.
 *
 * Without this, landmarks live ONLY in `annotationStore`'s browser-side draft: they
 * render on the photo and set `dirty`, but nothing ever `PUT`s them, so a reload hydrates
 * the server's (empty) set and every mark vanishes — while committed GCPs survive, because
 * their commit writes straight to the database. The VersionHistoryDrawer already promises
 * "Edits are autosaved"; this is what makes that true.
 *
 * Design (matches the store's existing machinery, which was built for exactly this):
 *   - fires `AUTOSAVE_DELAY_MS` after the last edit (debounced, so a drag or a burst of
 *     clicks is one request, not one per pixel);
 *   - `mode: 'replace'` — the draft IS the full live set, so replace makes the server match
 *     it exactly: adds, edits AND deletions in one call;
 *   - `base_revision_seq` carries optimistic-concurrency (the server 409s a stale base);
 *   - `markSaved(response)` applies the authoritative response (real UUIDs, `dirty=false`).
 *
 * A delete-EVERY-landmark is the one case this can't express (`items` must be ≥1, §6.2);
 * that path goes through `DELETE /annotations` (bulk_delete) in the toolbar, not here.
 */

import { useEffect } from 'react';

import { useAnnotationStore } from '../../store/annotationStore';
import type { AnnotationBulkUpsertRequest } from '../../types/annotation';
import type { Uuid } from '../../types/common';
import { useBulkUpsertAnnotations } from './useAnnotations';

const AUTOSAVE_DELAY_MS = 1000;

export function useAutosaveAnnotations(imageId: Uuid | null, projectId?: Uuid): void {
  const dirty = useAnnotationStore((s) => s.dirty);
  const draftImageId = useAnnotationStore((s) => s.draft.image_id);
  const bulkUpsert = useBulkUpsertAnnotations();
  // ★ `mutate` is referentially stable; the mutation OBJECT is new every render, and
  //   having it in the deps restarted the 1 s debounce on every host re-render.
  const { mutate: mutateBulkUpsert } = bulkUpsert;
  const pending = bulkUpsert.isPending;

  useEffect(() => {
    // Only save the draft that belongs to THIS image, only when there are unsaved edits,
    // and never while a save is already in flight (its onSuccess re-clears dirty).
    if (imageId === null || draftImageId !== imageId || !dirty || pending) return;

    const timer = setTimeout(() => {
      const store = useAnnotationStore.getState();
      if (!store.dirty || store.draft.image_id !== imageId) return;

      const items = store.toBulkUpsertItems();
      if (items.length === 0) return; // delete-all goes through bulk_delete, not here

      const body: AnnotationBulkUpsertRequest = {
        mode: 'replace',
        base_revision_seq: store.draft.base_revision_seq,
        items,
      };

      mutateBulkUpsert(
        { imageId, projectId, body },
        { onSuccess: (response) => useAnnotationStore.getState().markSaved(response) },
      );
    }, AUTOSAVE_DELAY_MS);

    return () => clearTimeout(timer);
  }, [imageId, draftImageId, dirty, pending, projectId, mutateBulkUpsert]);
}
