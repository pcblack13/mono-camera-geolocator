/**
 * `annotation/ToolRail.tsx` — the WIRED undo / redo / delete rail.
 *
 * ★ Extracted from `Workspace` so it can also be mounted inside the fullscreen `ImagePanel`
 *   (a floating rail on the maximised photo) WITHOUT a Workspace↔ImagePanel import cycle.
 *   Because it reads global stores, any number of instances stay in lock-step.
 *
 * ★★ IT DRIVES THE OPEN CORRESPONDENCE, NOT THE ANNOTATION STACK (1.2.6).
 *
 *    The rail is shown only while a GCP is being placed or adjusted, and in 1.2.6 it
 *    was still bound to `annotationStore`'s command stack — which holds LANDMARK
 *    edits. A GCP placed by clicking a bare pixel creates no landmark, so during the
 *    exact interaction the rail is visible for, all three buttons were permanently
 *    greyed out: present, explained by a tooltip, and useless.
 *
 *    So the binding follows the work: undo/redo step through the pairing's own
 *    endpoint history (`correspondenceStore`), and delete resets the marks to how
 *    this correspondence opened — empty when creating, the SAVED position when
 *    editing. Deleting the committed GCP is deliberately not on this rail; that is
 *    the GCP table's action, and a survey coordinate should not be destroyable by a
 *    small icon whose neighbours merely nudge a mark.
 *
 *    A landmark selected on the photograph still takes precedence for DELETE — that
 *    is an annotation, and the annotation stack remains its owner.
 */

import type { JSX } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { AnnotationToolbar } from './AnnotationToolbar';
import { createDeleteAnnotation } from '../../lib/commands';
import { useAnnotationStore } from '../../store/annotationStore';
import { useCorrespondenceStore } from '../../store/correspondenceStore';
import { useSelectionStore } from '../../store/selectionStore';

export interface ToolRailProps {
  orientation: 'vertical' | 'horizontal';
}

export function ToolRail({ orientation }: ToolRailProps): JSX.Element | null {
  const {
    canUndo,
    canRedo,
    undo,
    redo,
    peekUndoLabel,
    peekRedoLabel,
    execute,
    annotations,
    previewVersionId,
  } = useAnnotationStore(
    useShallow((s) => ({
      canUndo: s.canUndo,
      canRedo: s.canRedo,
      undo: s.undo,
      redo: s.redo,
      peekUndoLabel: s.peekUndoLabel,
      peekRedoLabel: s.peekRedoLabel,
      execute: s.execute,
      annotations: s.draft.annotations,
      previewVersionId: s.previewVersionId,
    })),
  );
  const selected = useSelectionStore((s) => s.selected);
  // ★ THE AUTHORITATIVE GATE (1.2.6): the rail exists only while a GCP
  //   correspondence is open — the mark-editing stage, where undo/redo/delete act on
  //   something. Enforced here (not only at mount sites) so every present and future
  //   mount inherits the rule.
  const gcpStageOpen = useCorrespondenceStore((s) => s.status !== 'idle');

  // ★ Called INSIDE the selector so zustand subscribes to the derived boolean —
  //   selecting the method reference alone would never re-render when it changes.
  const canUndoPoint = useCorrespondenceStore((s) => s.canUndoPoint());
  const canRedoPoint = useCorrespondenceStore((s) => s.canRedoPoint());
  const undoPointLabel = useCorrespondenceStore((s) => s.undoPointLabel());
  const redoPointLabel = useCorrespondenceStore((s) => s.redoPointLabel());
  const canResetPoints = useCorrespondenceStore((s) => s.canResetPoints());
  const undoPoint = useCorrespondenceStore((s) => s.undoPoint);
  const redoPoint = useCorrespondenceStore((s) => s.redoPoint);
  const resetPoints = useCorrespondenceStore((s) => s.resetPoints);

  const selectedAnnotationIds = selected.filter((r) => r.kind === 'annotation').map((r) => r.id);
  const readOnly = previewVersionId !== null;
  const hasSelectedAnnotation = !readOnly && selectedAnnotationIds.length > 0;

  const onDeleteAnnotation = (): void => {
    // Delete highest-index-first so earlier deletions do not shift later indices.
    const targets = selectedAnnotationIds
      .map((id) => {
        const index = annotations.findIndex((a) => a.id === id);
        return index >= 0 ? { annotation: annotations[index], index } : null;
      })
      .filter((t): t is { annotation: (typeof annotations)[number]; index: number } => t !== null)
      .sort((a, b) => b.index - a.index);
    for (const { annotation, index } of targets) {
      execute(createDeleteAnnotation(annotation, index));
    }
  };

  if (!gcpStageOpen) return null;

  // ★ A selected LANDMARK owns delete (it is an annotation, and the annotation stack
  //   is its history); otherwise delete resets the pairing's marks.
  const deleteTargetsAnnotation = hasSelectedAnnotation;

  return (
    <AnnotationToolbar
      orientation={orientation}
      // ★ Undo/redo prefer the pairing. Only once its history is exhausted do they
      //   fall through to the annotation stack, so undoing past the marks can still
      //   reverse a landmark edit made just before the GCP was started.
      canUndo={canUndoPoint || canUndo()}
      canRedo={canRedoPoint || canRedo()}
      undoLabel={canUndoPoint ? undoPointLabel : peekUndoLabel()}
      redoLabel={canRedoPoint ? redoPointLabel : peekRedoLabel()}
      onUndo={canUndoPoint ? undoPoint : undo}
      onRedo={canRedoPoint ? redoPoint : redo}
      canDelete={deleteTargetsAnnotation || canResetPoints}
      onDelete={deleteTargetsAnnotation ? onDeleteAnnotation : resetPoints}
      deleteLabel={
        deleteTargetsAnnotation
          ? 'Delete selection (Del)'
          : 'Clear the marks — back to how this point started'
      }
      disabled={readOnly}
    />
  );
}

export default ToolRail;
