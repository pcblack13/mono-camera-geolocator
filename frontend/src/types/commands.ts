/**
 * The undo/redo command system — ★ CLIENT-ONLY. **No server mirror.**
 *
 * ★ Because there is no wire here, these types may use TS-idiomatic naming. They do
 *   not: the payloads carry annotation FIELD names, and those are wire names (L9).
 *   Renaming them at the command boundary would reintroduce the mapping layer §8.1
 *   deletes. Only the command MACHINERY (`Command<T>`, `type`, `label`) is
 *   camelCase, because none of it ever leaves the browser.
 *
 * ★ `AdjustGcpCommand` is deliberately NOT here (§8.5). GCP adjustment routes
 *   through `useAdjustGcp`'s optimistic mutation → `PATCH /gcps/{id}` with
 *   `If-Match`. It is a server-authoritative edit with a re-estimate behind it; the
 *   undo stack cannot honestly own it.
 *
 * ★ `inProgress` (a half-drawn polygon) is OUTSIDE the command system — a
 *   half-drawn polygon isn't an edit. Escape cancels without polluting the stack;
 *   undo after a COMPLETED polygon removes the whole polygon.
 */

import type { Point2D, Uuid } from './common';
import type { AnnotationKind, AnnotationRead } from './annotation';
import type { GeoJsonGeometry } from './geo';

export type CommandType =
  | 'add_annotation'
  | 'delete_annotation'
  | 'move_annotation'
  | 'move_vertex'
  | 'add_vertex'
  | 'delete_vertex'
  | 'set_label'
  | 'set_kind'
  | 'set_confidence'
  | 'reorder_annotation';

/**
 * The command pattern's core. `apply`/`invert` are PURE over the draft set: given
 * the same state they produce the same state, which is what makes the stack
 * replayable and the autosave diffable.
 */
export interface Command<T = unknown> {
  readonly id: string;
  readonly type: CommandType;
  readonly payload: T;
  /** For the `LiveRegion` announcement: "Added point P4 at 3902, 3011". */
  readonly label: string;
  readonly timestamp: number;
  apply(state: AnnotationRead[]): AnnotationRead[];
  invert(state: AnnotationRead[]): AnnotationRead[];
  /** ★ Coalescing drags: a 60fps drag must be ONE undo step, not 400 (§4.4). */
  coalesceWith?(next: Command): Command | null;
}

/** What goes over the wire in `client_op_id` correlation and into `localStorage`. */
export interface SerializedCommand {
  id: string;
  type: CommandType;
  payload: unknown;
  label: string;
  timestamp: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// The ten payloads
// ─────────────────────────────────────────────────────────────────────────────

/** ★ `pixel_*` and `geometry` are ORIGINAL image pixels (§8.6), never display px. */
export interface AddAnnotationPayload {
  annotation: AnnotationRead;
  index: number;
}

export interface DeleteAnnotationPayload {
  annotation: AnnotationRead;
  index: number;
}

export interface MoveAnnotationPayload {
  annotation_id: Uuid;
  from: Point2D;
  to: Point2D;
  geometry_before: GeoJsonGeometry;
  geometry_after: GeoJsonGeometry;
}

export interface MoveVertexPayload {
  annotation_id: Uuid;
  ring_index: number;
  vertex_index: number;
  from: Point2D;
  to: Point2D;
}

export interface AddVertexPayload {
  annotation_id: Uuid;
  ring_index: number;
  vertex_index: number;
  point: Point2D;
}

export interface DeleteVertexPayload {
  annotation_id: Uuid;
  ring_index: number;
  vertex_index: number;
  point: Point2D;
}

export interface SetLabelPayload {
  annotation_id: Uuid;
  before: string | null;
  after: string | null;
}

export interface SetKindPayload {
  annotation_id: Uuid;
  before: AnnotationKind;
  after: AnnotationKind;
}

/** ★ 0–1 — the surveyor's own certainty on the ANNOTATION (§6.1). Not the GCP scale. */
export interface SetConfidencePayload {
  annotation_id: Uuid;
  before: number;
  after: number;
}

export interface ReorderAnnotationPayload {
  annotation_id: Uuid;
  before: number;
  after: number;
}

export type AnnotationCommandPayload =
  | AddAnnotationPayload
  | DeleteAnnotationPayload
  | MoveAnnotationPayload
  | MoveVertexPayload
  | AddVertexPayload
  | DeleteVertexPayload
  | SetLabelPayload
  | SetKindPayload
  | SetConfidencePayload
  | ReorderAnnotationPayload;

/**
 * ★ An annotation command narrows the base `coalesceWith` return to the domain union:
 *   coalescing two annotation commands yields another `AnnotationCommand`, never a
 *   loose `Command<unknown>` (that is what the factories actually return). Expressed as
 *   an interface so the self-reference sits behind a deferred function return — a
 *   mapped-type (`Omit`) version would circularly reference itself. This keeps the undo
 *   stack — `AnnotationCommand[]` — typed end to end (`lib/commands/stack.ts`).
 */
export interface AnnotationCommandBase<T> extends Command<T> {
  coalesceWith?(next: Command): AnnotationCommand | null;
}

/** The discriminated union the reducer switches on. */
export type AnnotationCommand =
  | (AnnotationCommandBase<AddAnnotationPayload> & { type: 'add_annotation' })
  | (AnnotationCommandBase<DeleteAnnotationPayload> & { type: 'delete_annotation' })
  | (AnnotationCommandBase<MoveAnnotationPayload> & { type: 'move_annotation' })
  | (AnnotationCommandBase<MoveVertexPayload> & { type: 'move_vertex' })
  | (AnnotationCommandBase<AddVertexPayload> & { type: 'add_vertex' })
  | (AnnotationCommandBase<DeleteVertexPayload> & { type: 'delete_vertex' })
  | (AnnotationCommandBase<SetLabelPayload> & { type: 'set_label' })
  | (AnnotationCommandBase<SetKindPayload> & { type: 'set_kind' })
  | (AnnotationCommandBase<SetConfidencePayload> & { type: 'set_confidence' })
  | (AnnotationCommandBase<ReorderAnnotationPayload> & { type: 'reorder_annotation' });
