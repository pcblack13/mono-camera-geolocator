/**
 * `useSaveAnnotationsNow` — flush the annotation draft this instant.
 *
 * ★ The debounced autosave (`useAutosaveAnnotations`) already persists every edit ~1 s
 *   after the surveyor stops. What it cannot give is a MOMENT: "it is saved NOW, I can
 *   close the laptop". The Save button provides that moment — it runs the SAME bulk
 *   upsert with the SAME body construction, immediately. Two spellings of one save, so
 *   they cannot diverge in behaviour, only in timing.
 *
 * Safe to call when clean: it no-ops rather than issuing an empty write.
 */

import { useCallback } from 'react';

import type { AnnotationBulkUpsertRequest } from '../../types/annotation';
import type { Uuid } from '../../types/common';
import { useAnnotationStore } from '../../store/annotationStore';
import { useBulkUpsertAnnotations } from './useAnnotations';

export interface SaveNow {
  /** Persist the draft immediately. Resolves when the server has it. */
  save: () => void;
  /** A save is in flight. */
  saving: boolean;
  /** There are edits the server does not have yet. */
  dirty: boolean;
  /** Epoch ms of the last successful save, or null before the first. */
  lastSavedAt: number | null;
}

export function useSaveAnnotationsNow(imageId: Uuid | null, projectId?: Uuid): SaveNow {
  const dirty = useAnnotationStore((s) => s.dirty);
  const lastSavedAt = useAnnotationStore((s) => s.lastSavedAt);
  const bulkUpsert = useBulkUpsertAnnotations();
  const { mutate: mutateBulkUpsert } = bulkUpsert;

  const save = useCallback(() => {
    // Read the store ONCE, at click time — the same pattern the autosave timer uses, so
    // a save started mid-edit persists exactly what was on screen when it was pressed.
    const store = useAnnotationStore.getState();
    if (imageId === null || !store.dirty || store.draft.image_id !== imageId) return;
    const items = store.toBulkUpsertItems();
    if (items.length === 0) return; // delete-all travels via bulk_delete, not here

    const body: AnnotationBulkUpsertRequest = {
      mode: 'replace',
      base_revision_seq: store.draft.base_revision_seq,
      items,
    };
    mutateBulkUpsert(
      { imageId, projectId, body },
      { onSuccess: (response) => useAnnotationStore.getState().markSaved(response) },
    );
  }, [mutateBulkUpsert, imageId, projectId]);

  return { save, saving: bulkUpsert.isPending, dirty, lastSavedAt };
}
