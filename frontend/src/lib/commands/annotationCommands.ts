/**
 * ★ THE UNDO/REDO COMMAND FACTORIES — CONTRACT.md §8.2 (`commands.ts`) /
 *   50-frontend.md §4.1–§4.4.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ WHICH `Command` INTERFACE IS LAW, recorded so nobody "restores" the other one:
 *
 *   `50-frontend.md §4.1` specifies `apply(draft, ctx)` / `revert(draft, ctx)`
 *   mutating an **immer draft**, plus `mergeKey` + `canMerge` + `merge` +
 *   `serialize`, over an `AnnotationDraftState { byId, order }`, with dotted
 *   `CommandType`s (`'annotation.add'`).
 *
 *   `src/types/commands.ts` (IU-23, mandated by CONTRACT.md §8.2) specifies
 *   `apply(state: AnnotationRead[]): AnnotationRead[]` / `invert(...)` — **pure and
 *   immutable, over a flat array** — with `coalesceWith?(next)` and snake_case
 *   `CommandType`s (`'add_annotation'`).
 *
 *   **CONTRACT.md > 50-frontend.md** (§0, precedence, absolute). The contract's
 *   interface wins, this file implements it, and `annotationStore` is built on it.
 *   The three consequences are deliberate:
 *     1. **No immer.** `immer` is not in `package.json` (IU-23 owns that file and did
 *        not add it), so `zustand/middleware/immer` is unavailable. The pure
 *        `state => state` signature needs neither. This is a happy accident of the
 *        contract being stricter than the specialist doc.
 *     2. **`mergeKey`/`canMerge`/`merge` collapse into `coalesceWith`**, which
 *        returns the merged command or `null`. The merge-key comparison, the 600 ms
 *        window and the merge itself are all inside it — one function, one place,
 *        same semantics as §4.4. Callers cannot forget to check the key.
 *     3. **`serialize()` is not a method.** `SerializedCommand` is structural
 *        (`{id, type, payload, label, timestamp}`), so {@link serializeCommand} is a
 *        free function. A command is data; making it serialise itself added nothing.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * ★ **EVERY `Point2D` IN EVERY PAYLOAD IS AN ORIGINAL IMAGE PIXEL** (§8.6). A
 *   command never sees a stage coordinate: the conversion happens once, at the event
 *   boundary in `ImageViewer`, via `lib/viewport/transform.ts` and nowhere else.
 *
 * ★ **`apply`/`invert` over `apply`/`inverse-by-inspection`.** Each command carries
 *   BOTH the before- and after-fragments it needs in its payload, so `invert` is
 *   exact and self-contained — it never reconstructs prior state by inspecting
 *   current state. That makes every command independently testable (`invert(apply(s))
 *   === s` is a property IU-29 asserts for all ten types) and immune to the classic
 *   bug where reverting depends on state a later command changed.
 */

import type { AnnotationKind, AnnotationRead } from '../../types/annotation';
import { newId } from '../ids';
import type {
  AddAnnotationPayload,
  AddVertexPayload,
  AnnotationCommand,
  Command,
  DeleteAnnotationPayload,
  DeleteVertexPayload,
  MoveAnnotationPayload,
  MoveVertexPayload,
  ReorderAnnotationPayload,
  SerializedCommand,
  SetConfidencePayload,
  SetKindPayload,
  SetLabelPayload,
} from '../../types/commands';
import type { Point2D, Uuid } from '../../types/common';
import type { GeoJsonGeometry } from '../../types/geo';

// ─────────────────────────────────────────────────────────────────────────────
// Infrastructure
// ─────────────────────────────────────────────────────────────────────────────

/**
 * §4.4 — two commands on the same target coalesce only inside this window. Pausing
 * for longer starts a new undo entry, which matches the user's mental model of a
 * "gesture": twenty `ArrowLeft` nudges are one undo; nudge, think, nudge is two.
 */
export const COALESCE_WINDOW_MS = 600;

/**
 * ★ `nanoid` is NOT a dependency (IU-23 owns `package.json`; it lists neither
 *   `nanoid` nor `immer`). `crypto.randomUUID()` is native in every browser this app
 *   targets and in Node ≥ 19 (so vitest/jsdom is fine), needs no bundle, and is a
 *   strictly stronger id. These ids are client-only correlation handles
 *   (`client_op_id`, the change log) — never a resource id — so the extra length
 *   costs nothing.
 */
const newCommandId = (): string => newId();

/** A command is data. See the header note on `serialize()`. */
export function serializeCommand(cmd: Command): SerializedCommand {
  return {
    id: cmd.id,
    type: cmd.type,
    payload: cmd.payload,
    label: cmd.label,
    timestamp: cmd.timestamp,
  };
}

const now = (): number => Date.now();

/**
 * ★ THE COALESCE WINDOW, in one place.
 *
 *   §4.4 rule 3: merge when the key matches **and** `next.timestamp - this.timestamp
 *   < 600 ms`, where `this` is the command currently on the stack. The window is
 *   therefore **SLIDING**, measured from the most recent merged command — which is
 *   what makes "twenty nudges collapse to one undo of the whole gesture; pausing for
 *   a second starts a new undo entry" true. A continuous gesture stays one entry for
 *   as long as it is continuous; that is the user's mental model of a gesture, and a
 *   fixed window anchored at the gesture's start would chop a slow, careful drag into
 *   arbitrary undo steps at 600 ms boundaries.
 *
 * ★ Every coalescing factory takes an explicit `timestamp` so a merged command is
 *   CONSTRUCTED with the newer time rather than having it patched on afterwards.
 *   Patching (`{...merged, timestamp}`) does not work and is a trap worth naming:
 *   `coalesceWith` is a closure over its factory's own `self`, so an overridden
 *   `timestamp` PROPERTY is invisible to the comparison inside it — the window would
 *   silently slide off the un-patched value and coalesce forever, collapsing an
 *   unbounded edit into a single undo. Constructing with the right value keeps the
 *   object and its closure in agreement by construction.
 */
const inWindow = (selfTs: number, nextTs: number): boolean => nextTs - selfTs < COALESCE_WINDOW_MS;

/** For labels: `P4` if labelled, else a short id. Never `undefined` in a live region. */
const nameOf = (a: Pick<AnnotationRead, 'id' | 'label'>): string =>
  a.label ?? `#${a.id.slice(0, 8)}`;

/** Display-only rounding (§8.6: round for display, NEVER for storage). */
const fmt = (p: Point2D): string => `${p.x.toFixed(1)}, ${p.y.toFixed(1)}`;

const indexOfId = (state: AnnotationRead[], id: Uuid): number =>
  state.findIndex((a) => a.id === id);

/** Immutable single-item replace. Returns `state` untouched if the id is absent. */
function withAnnotation(
  state: AnnotationRead[],
  id: Uuid,
  update: (a: AnnotationRead) => AnnotationRead,
): AnnotationRead[] {
  const i = indexOfId(state, id);
  if (i === -1) return state;
  const next = state.slice();
  next[i] = update(state[i]!);
  return next;
}

const insertAt = <T>(xs: readonly T[], index: number, x: T): T[] => {
  const i = Math.max(0, Math.min(index, xs.length));
  return [...xs.slice(0, i), x, ...xs.slice(i)];
};

// ─────────────────────────────────────────────────────────────────────────────
// Geometry surgery — ORIGINAL image px, `[x, y]`, y-down, SRID 0
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ `AnnotationRead.geometry` is GeoJSON-**shaped** but is NOT geographic: its
 *   coordinates are IMAGE PIXELS, `[x, y]`, y-down (`types/geo.ts`, "THE TRAP").
 *   Nothing in this file may hand one of these to Leaflet.
 */
type Ring = [number, number][];

/** The rings of a geometry, in a uniform shape, so the vertex ops have one code path. */
function ringsOf(g: GeoJsonGeometry): Ring[] {
  switch (g.type) {
    case 'Point':
      return [[g.coordinates]];
    case 'LineString':
      return [g.coordinates];
    case 'Polygon':
      return g.coordinates;
    case 'MultiPolygon':
      return g.coordinates.flat();
  }
}

/** Rebuild a geometry of the same type from edited rings. Structure is preserved exactly. */
function withRings(g: GeoJsonGeometry, rings: Ring[]): GeoJsonGeometry {
  switch (g.type) {
    case 'Point':
      return { type: 'Point', coordinates: rings[0]![0]! };
    case 'LineString':
      return { type: 'LineString', coordinates: rings[0]! };
    case 'Polygon':
      return { type: 'Polygon', coordinates: rings };
    case 'MultiPolygon': {
      // Re-nest by the ORIGINAL ring counts — a MultiPolygon's shape is not
      // recoverable from a flat list, and guessing it would silently merge polygons.
      const out: Ring[][] = [];
      let k = 0;
      for (const poly of g.coordinates) {
        out.push(rings.slice(k, k + poly.length));
        k += poly.length;
      }
      return { type: 'MultiPolygon', coordinates: out };
    }
  }
}

function mapRing(g: GeoJsonGeometry, ringIndex: number, f: (r: Ring) => Ring): GeoJsonGeometry {
  const rings = ringsOf(g);
  if (ringIndex < 0 || ringIndex >= rings.length) return g;
  const next = rings.slice();
  next[ringIndex] = f(rings[ringIndex]!);
  return withRings(g, next);
}

const setVertex = (g: GeoJsonGeometry, ring: number, i: number, p: Point2D): GeoJsonGeometry =>
  mapRing(g, ring, (r) => {
    if (i < 0 || i >= r.length) return r;
    const out = r.slice() as Ring;
    out[i] = [p.x, p.y];
    return out;
  });

const spliceVertexIn = (g: GeoJsonGeometry, ring: number, i: number, p: Point2D): GeoJsonGeometry =>
  mapRing(g, ring, (r) => insertAt(r, i, [p.x, p.y]) as Ring);

const spliceVertexOut = (g: GeoJsonGeometry, ring: number, i: number): GeoJsonGeometry =>
  mapRing(g, ring, (r) =>
    i < 0 || i >= r.length ? r : ([...r.slice(0, i), ...r.slice(i + 1)] as Ring),
  );

/**
 * ★ A polygon ring must stay CLOSED (`first === last`, ≥ 4 positions) or the API
 *   returns `422 ANNOTATION_GEOMETRY_INVALID` (`types/annotation.ts`). The vertex
 *   commands splice **literally at the index given** — they do not silently rewrite
 *   the caller's intent, because a command that quietly relocates a surveyor's
 *   vertex is exactly the class of bug this layer exists to prevent.
 *
 *   `IU-26` is therefore responsible for supplying an INTERIOR index on a polygon
 *   ring (`1 … ring.length - 1`) and may call this to assert it. Exported for that
 *   reason, and used by IU-29's property tests.
 */
export function isRingClosed(ring: readonly [number, number][]): boolean {
  if (ring.length < 4) return false;
  const a = ring[0]!;
  const b = ring[ring.length - 1]!;
  return a[0] === b[0] && a[1] === b[1];
}

// ─────────────────────────────────────────────────────────────────────────────
// add_annotation / delete_annotation
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Emitted by `commitShape`, never per-vertex. Undo after a completed polygon
 *   removes THE WHOLE POLYGON — the half-drawn shape lived in
 *   `annotationStore.inProgress`, outside the command system (§4.3).
 */
export function createAddAnnotation(annotation: AnnotationRead, index: number): AnnotationCommand {
  const payload: AddAnnotationPayload = { annotation, index };
  return {
    id: newCommandId(),
    type: 'add_annotation',
    payload,
    label: `Add ${annotation.geom_type} ${nameOf(annotation)}`,
    timestamp: now(),
    apply: (state) => insertAt(state, index, annotation),
    invert: (state) => state.filter((a) => a.id !== annotation.id),
  };
}

/**
 * ★ `index` is captured at creation so undo puts the annotation back **where it
 *   was** in z-order, not appended to the end (§4.2).
 */
export function createDeleteAnnotation(
  annotation: AnnotationRead,
  index: number,
): AnnotationCommand {
  const payload: DeleteAnnotationPayload = { annotation, index };
  return {
    id: newCommandId(),
    type: 'delete_annotation',
    payload,
    label: `Delete ${annotation.geom_type} ${nameOf(annotation)}`,
    timestamp: now(),
    apply: (state) => state.filter((a) => a.id !== annotation.id),
    invert: (state) => insertAt(state, index, annotation),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// move_annotation
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Move a whole annotation. `from`/`to` are the REPRESENTATIVE point; the full
 * before/after geometries ride along so `invert` is exact for polygons too.
 *
 * ★ §4.4 rule 2 — **the drag emits exactly ONE command, at `pointerup`.** During the
 *   drag `ImageViewer` mutates the Konva node directly: no store write, no command.
 *   That, not `coalesceWith`, is the primary mechanism; a command per `pointermove`
 *   at 120 Hz would make one drag take 400 undos to reverse.
 *
 * ★ `coalesceWith` handles what remains: keyboard nudges (`ArrowLeft` ×20) and
 *   Inspector numeric typing, which genuinely arrive as discrete commands. Origin
 *   from the FIRST, destination from the LAST.
 */
export function createMoveAnnotation(
  annotation_id: Uuid,
  from: Point2D,
  to: Point2D,
  geometry_before: GeoJsonGeometry,
  geometry_after: GeoJsonGeometry,
  /** ★ Internal / tests. See {@link inWindow}: a merged command is CONSTRUCTED with the newer time. */
  timestamp: number = now(),
): AnnotationCommand {
  const payload: MoveAnnotationPayload = {
    annotation_id,
    from,
    to,
    geometry_before,
    geometry_after,
  };
  const self: AnnotationCommand = {
    id: newCommandId(),
    type: 'move_annotation',
    payload,
    label: `Move to ${fmt(to)}`,
    timestamp,
    apply: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: geometry_after,
        pixel_x: to.x,
        pixel_y: to.y,
      })),
    invert: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: geometry_before,
        pixel_x: from.x,
        pixel_y: from.y,
      })),
    coalesceWith: (next) => {
      if (next.type !== 'move_annotation') return null;
      const p = next.payload as MoveAnnotationPayload;
      if (p.annotation_id !== annotation_id) return null;
      if (!inWindow(self.timestamp, next.timestamp)) return null;
      // ★ Origin from the FIRST, destination from the LAST (§4.4 rule 3).
      return createMoveAnnotation(
        annotation_id,
        from,
        p.to,
        geometry_before,
        p.geometry_after,
        next.timestamp,
      );
    },
  };
  return self;
}

// ─────────────────────────────────────────────────────────────────────────────
// move_vertex / add_vertex / delete_vertex
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Vertex ops touch `geometry` ONLY — never `pixel_x`/`pixel_y`. The representative
 *   point is the server's to derive (`AnnotationCreate.pixel_x` is optional for
 *   exactly this reason), and a client guessing a polygon's representative point
 *   would fork `gcps.pixel_x` from `annotations.pixel_x`. Moving a *point*
 *   annotation is `move_annotation`, which does update both.
 */
export function createMoveVertex(
  annotation_id: Uuid,
  ring_index: number,
  vertex_index: number,
  from: Point2D,
  to: Point2D,
  /** ★ Internal / tests. See {@link inWindow}. */
  timestamp: number = now(),
): AnnotationCommand {
  const payload: MoveVertexPayload = { annotation_id, ring_index, vertex_index, from, to };
  const self: AnnotationCommand = {
    id: newCommandId(),
    type: 'move_vertex',
    payload,
    label: `Move vertex ${vertex_index + 1} to ${fmt(to)}`,
    timestamp,
    apply: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: setVertex(a.geometry, ring_index, vertex_index, to),
      })),
    invert: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: setVertex(a.geometry, ring_index, vertex_index, from),
      })),
    coalesceWith: (next) => {
      if (next.type !== 'move_vertex') return null;
      const p = next.payload as MoveVertexPayload;
      // ★ The merge key: `vertex:${id}:${ring}:${index}`. Different targets NEVER merge.
      if (p.annotation_id !== annotation_id || p.ring_index !== ring_index) return null;
      if (p.vertex_index !== vertex_index) return null;
      if (!inWindow(self.timestamp, next.timestamp)) return null;
      return createMoveVertex(annotation_id, ring_index, vertex_index, from, p.to, next.timestamp);
    },
  };
  return self;
}

/** ★ See {@link isRingClosed}: on a polygon ring the caller must pass an INTERIOR index. */
export function createAddVertex(
  annotation_id: Uuid,
  ring_index: number,
  vertex_index: number,
  point: Point2D,
): AnnotationCommand {
  const payload: AddVertexPayload = { annotation_id, ring_index, vertex_index, point };
  return {
    id: newCommandId(),
    type: 'add_vertex',
    payload,
    label: `Add vertex at ${fmt(point)}`,
    timestamp: now(),
    apply: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: spliceVertexIn(a.geometry, ring_index, vertex_index, point),
      })),
    invert: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: spliceVertexOut(a.geometry, ring_index, vertex_index),
      })),
  };
}

export function createDeleteVertex(
  annotation_id: Uuid,
  ring_index: number,
  vertex_index: number,
  point: Point2D,
): AnnotationCommand {
  const payload: DeleteVertexPayload = { annotation_id, ring_index, vertex_index, point };
  return {
    id: newCommandId(),
    type: 'delete_vertex',
    payload,
    label: `Delete vertex ${vertex_index + 1}`,
    timestamp: now(),
    apply: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: spliceVertexOut(a.geometry, ring_index, vertex_index),
      })),
    invert: (state) =>
      withAnnotation(state, annotation_id, (a) => ({
        ...a,
        geometry: spliceVertexIn(a.geometry, ring_index, vertex_index, point),
      })),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// set_label / set_kind / set_confidence
// ─────────────────────────────────────────────────────────────────────────────

/** ★ §4.4 rule 5 — typing a label is ONE undo, not one-per-keystroke. */
export function createSetLabel(
  annotation_id: Uuid,
  before: string | null,
  after: string | null,
  /** ★ Internal / tests. See {@link inWindow}. */
  timestamp: number = now(),
): AnnotationCommand {
  const payload: SetLabelPayload = { annotation_id, before, after };
  const self: AnnotationCommand = {
    id: newCommandId(),
    type: 'set_label',
    payload,
    label: after === null ? 'Clear label' : `Rename to ${after}`,
    timestamp,
    apply: (state) => withAnnotation(state, annotation_id, (a) => ({ ...a, label: after })),
    invert: (state) => withAnnotation(state, annotation_id, (a) => ({ ...a, label: before })),
    coalesceWith: (next) => {
      if (next.type !== 'set_label') return null;
      const p = next.payload as SetLabelPayload;
      if (p.annotation_id !== annotation_id) return null;
      if (!inWindow(self.timestamp, next.timestamp)) return null;
      return createSetLabel(annotation_id, before, p.after, next.timestamp);
    },
  };
  return self;
}

/**
 * ★ Deliberately NOT coalescing. `kind` is a discrete choice from a select — each
 *   change is one deliberate act, and collapsing two of them would lose an
 *   intermediate the surveyor may want back. Coalescing is for gestures (a drag, a
 *   nudge run, a burst of typing); a dropdown is not a gesture.
 */
export function createSetKind(
  annotation_id: Uuid,
  before: AnnotationKind,
  after: AnnotationKind,
): AnnotationCommand {
  const payload: SetKindPayload = { annotation_id, before, after };
  return {
    id: newCommandId(),
    type: 'set_kind',
    payload,
    label: `Set kind to ${after}`,
    timestamp: now(),
    apply: (state) => withAnnotation(state, annotation_id, (a) => ({ ...a, kind: after })),
    invert: (state) => withAnnotation(state, annotation_id, (a) => ({ ...a, kind: before })),
  };
}

/**
 * ★ **0–1** — the surveyor's own certainty on the ANNOTATION (`types/commands.ts`).
 *   NOT `GcpRead.confidence`'s 0–100 scale, and NOT `declared_confidence`'s 1–5.
 *   The three scales are deliberate and must not be unified (§6.1).
 *
 * Coalesces: a slider drag or a numeric field arrives as a burst.
 */
export function createSetConfidence(
  annotation_id: Uuid,
  before: number,
  after: number,
  /** ★ Internal / tests. See {@link inWindow}. */
  timestamp: number = now(),
): AnnotationCommand {
  const payload: SetConfidencePayload = { annotation_id, before, after };
  const self: AnnotationCommand = {
    id: newCommandId(),
    type: 'set_confidence',
    payload,
    label: `Set confidence to ${after.toFixed(2)}`,
    timestamp,
    apply: (state) => withAnnotation(state, annotation_id, (a) => ({ ...a, confidence: after })),
    invert: (state) => withAnnotation(state, annotation_id, (a) => ({ ...a, confidence: before })),
    coalesceWith: (next) => {
      if (next.type !== 'set_confidence') return null;
      const p = next.payload as SetConfidencePayload;
      if (p.annotation_id !== annotation_id) return null;
      if (!inWindow(self.timestamp, next.timestamp)) return null;
      return createSetConfidence(annotation_id, before, p.after, next.timestamp);
    },
  };
  return self;
}

// ─────────────────────────────────────────────────────────────────────────────
// reorder_annotation
// ─────────────────────────────────────────────────────────────────────────────

/** `before`/`after` are INDICES into the annotation array (= z-order). */
export function createReorderAnnotation(
  annotation_id: Uuid,
  before: number,
  after: number,
): AnnotationCommand {
  const payload: ReorderAnnotationPayload = { annotation_id, before, after };

  const move = (state: AnnotationRead[], from: number, to: number): AnnotationRead[] => {
    const i = indexOfId(state, annotation_id);
    if (i === -1 || from < 0 || from >= state.length) return state;
    const rest = state.filter((a) => a.id !== annotation_id);
    return insertAt(rest, to, state[i]!);
  };

  return {
    id: newCommandId(),
    type: 'reorder_annotation',
    payload,
    label: `Reorder to position ${after + 1}`,
    timestamp: now(),
    apply: (state) => move(state, before, after),
    invert: (state) => move(state, after, before),
  };
}
