/**
 * The command system barrel — `src/lib/commands/` (CONTRACT.md §2.5).
 *
 * The `Command` / `AnnotationCommand` / payload TYPES live in `src/types/commands.ts`
 * (IU-23, mandated by §8.2). This directory holds the BEHAVIOUR: the ten factories
 * and the stack semantics. Same Protocol/implementation split as `WindowSource` and
 * `JobQueue` on the Python side (§3): the side that declares the interface owns the
 * interface.
 */

export {
  COALESCE_WINDOW_MS,
  createAddAnnotation,
  createAddVertex,
  createDeleteAnnotation,
  createDeleteVertex,
  createMoveAnnotation,
  createMoveVertex,
  createReorderAnnotation,
  createSetConfidence,
  createSetKind,
  createSetLabel,
  isRingClosed,
  serializeCommand,
} from './annotationCommands';

export type { CommandStacks, StackResult } from './stack';

export {
  MAX_UNDO,
  canRedo,
  canUndo,
  emptyStacks,
  executeCommand,
  peekRedoLabel,
  peekUndoLabel,
  redoCommand,
  undoCommand,
} from './stack';
