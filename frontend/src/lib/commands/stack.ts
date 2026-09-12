/**
 * ★ THE UNDO/REDO STACK SEMANTICS — 50-frontend.md §4.3 / §4.4.
 *
 * **Pure.** No zustand, no React. `annotationStore` is a thin wiring layer over
 * these functions, which is what makes the stack semantics testable without a store
 * and without a component (IU-29).
 *
 * The reference algorithm (§4.3), implemented exactly:
 *
 * ```
 * execute(cmd):
 *   1. if previewVersionId !== null -> reject (history preview is read-only)
 *   2. cmd.apply(state)
 *   3. top = undoStack.at(-1)
 *      if top && top.coalesceWith?.(cmd) -> undoStack[len-1] = merged   // do NOT push
 *      else                              -> undoStack.push(cmd)
 *                                           if length > MAX_UNDO: shift()
 *   4. redoStack = []                                                   // a new action forks the future
 *   5. dirty = true; scheduleAutosave()
 *
 * undo():  cmd = undoStack.pop(); cmd.invert(state); redoStack.push(cmd)
 * redo():  cmd = redoStack.pop(); cmd.apply(state);  undoStack.push(cmd)
 * ```
 *
 * Step 1 and step 5 belong to the store (they touch `previewVersionId`, `dirty` and
 * the autosave timer); steps 2–4 are here.
 */

import type { AnnotationCommand } from '../../types/commands';
import type { AnnotationRead } from '../../types/annotation';

/**
 * §4.3 — FIFO eviction at 200.
 *
 * Commands hold small payloads (a polygon's vertices at worst), so 200 is bounded
 * memory and about two orders of magnitude more than any real editing session needs
 * to reach back through.
 */
export const MAX_UNDO = 200;

export interface CommandStacks {
  undoStack: AnnotationCommand[];
  redoStack: AnnotationCommand[];
}

export interface StackResult {
  annotations: AnnotationRead[];
  stacks: CommandStacks;
  /** The command that moved. `null` when the operation was a no-op (empty stack). */
  command: AnnotationCommand | null;
  /** Did anything change? The store uses this to decide whether to mark `dirty`. */
  changed: boolean;
}

export const emptyStacks = (): CommandStacks => ({ undoStack: [], redoStack: [] });

/**
 * §4.3 steps 2–4.
 *
 * ★ **Coalescing is only ever attempted against `undoStack.at(-1)`. Never scan
 *   deeper** (§4.4 rule 4). Scanning deeper would let a nudge on P1 merge into a
 *   move of P1 that happened five edits ago, silently swallowing the four edits in
 *   between on undo.
 *
 * ★ The command is applied to the state EITHER WAY. Coalescing changes what sits on
 *   the stack, never what the canvas shows.
 */
export function executeCommand(
  annotations: AnnotationRead[],
  stacks: CommandStacks,
  cmd: AnnotationCommand,
): StackResult {
  const next = cmd.apply(annotations);

  const top = stacks.undoStack[stacks.undoStack.length - 1];
  const merged = top?.coalesceWith?.(cmd) ?? null;

  const undoStack = merged
    ? // Replace the top in place: the gesture is still ONE undo entry.
      [...stacks.undoStack.slice(0, -1), merged]
    : [...stacks.undoStack, cmd];

  // FIFO eviction — drop the OLDEST, keep the most recent 200.
  const capped =
    undoStack.length > MAX_UNDO ? undoStack.slice(undoStack.length - MAX_UNDO) : undoStack;

  return {
    annotations: next,
    // ★ A new action forks the future: the redo branch is unreachable and is dropped.
    stacks: { undoStack: capped, redoStack: [] },
    command: merged ?? cmd,
    changed: true,
  };
}

export function undoCommand(annotations: AnnotationRead[], stacks: CommandStacks): StackResult {
  const cmd = stacks.undoStack[stacks.undoStack.length - 1];
  if (!cmd) return { annotations, stacks, command: null, changed: false };

  return {
    annotations: cmd.invert(annotations),
    stacks: { undoStack: stacks.undoStack.slice(0, -1), redoStack: [...stacks.redoStack, cmd] },
    command: cmd,
    changed: true,
  };
}

export function redoCommand(annotations: AnnotationRead[], stacks: CommandStacks): StackResult {
  const cmd = stacks.redoStack[stacks.redoStack.length - 1];
  if (!cmd) return { annotations, stacks, command: null, changed: false };

  return {
    annotations: cmd.apply(annotations),
    stacks: { undoStack: [...stacks.undoStack, cmd], redoStack: stacks.redoStack.slice(0, -1) },
    command: cmd,
    changed: true,
  };
}

export const canUndo = (s: CommandStacks): boolean => s.undoStack.length > 0;
export const canRedo = (s: CommandStacks): boolean => s.redoStack.length > 0;

/** For the Edit menu's "Undo Move P2" / the `LiveRegion` announcement. */
export const peekUndoLabel = (s: CommandStacks): string | null =>
  s.undoStack[s.undoStack.length - 1]?.label ?? null;

export const peekRedoLabel = (s: CommandStacks): string | null =>
  s.redoStack[s.redoStack.length - 1]?.label ?? null;
