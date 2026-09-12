/**
 * ★★ `annotationStore` — the heart of the client state.
 *    CONTRACT.md §8.5 / 50-frontend.md §3.4, §4.
 *
 * Owns: `draft` · `inProgress` · `undoStack` · `redoStack` · `dirty` · `lastSavedAt`
 * · `previewVersionId`.
 *
 * ★ **NOT persisted to `localStorage`** (§8.5) — autosave to the server is the only
 *   draft truth. A `localStorage` copy would be a second, conflicting source of
 *   truth for a survey input. Instead a `beforeunload` guard fires while `dirty`
 *   (wired by IU-28; this store exposes `dirty`).
 *
 * ★ All coordinates in the draft are **ORIGINAL image pixels** (§8.6). The only
 *   conversion site is `ImageViewer`'s pointer handler.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ THE DECISION THIS FILE MAKES, AND WHY — **STABLE CLIENT IDENTITY**
 *
 *   A new annotation is created client-side before the server has ever seen it, so
 *   it needs an id immediately. After the first autosave the server assigns the REAL
 *   UUID. The obvious move — swap `tmp-…` → the real UUID in the draft, as §8.5's
 *   "swap `tmp-17` → the real UUID" suggests — **silently breaks the undo stack**:
 *   every command already on it captured the temp id, so `undo()` after a save
 *   finds no annotation with that id and no-ops. The stack looks fine and does
 *   nothing. §4.3 is explicit that this must work: *"Undo/redo are NOT invalidated
 *   by an autosave. Saving a version is a checkpoint, not a barrier; a surveyor may
 *   save and then undo."*
 *
 *   So: **`AnnotationRead.id` in the draft is the STABLE CLIENT IDENTITY for the
 *   whole session.** The server's UUID is learned via `client_ref` and kept beside
 *   it in {@link AnnotationDraftState.server_id_by_client_id}. The server's
 *   authoritative FIELDS are merged in on save; only the `id` is held stable.
 *
 *   This is not a workaround, it is what the contract already assumes elsewhere:
 *   `selectionStore.SelectionRef.id` is documented as *"annotation clientId or gcp
 *   Uuid"* (§3.4) — the cross-pane bus is specified in terms of client ids.
 *
 *   ★ **CONSEQUENCE FOR IU-24 / IU-26 / IU-27 — please read.** When addressing the
 *     API for an annotation, resolve through {@link serverIdOf} /
 *     {@link toBulkUpsertItems}. `draft.annotations[i].id` is a CLIENT id and is not
 *     guaranteed to be a server resource id. For an annotation hydrated from the
 *     server the two are identical, so only newly-drawn shapes are affected.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { create } from 'zustand';

import { newId } from '../lib/ids';
import { devtools } from 'zustand/middleware';

import type {
  AnnotationBulkUpsertItem,
  AnnotationBulkUpsertResponse,
  AnnotationGeomType,
  AnnotationKind,
  AnnotationRead,
} from '../types/annotation';
import type { AnnotationCommand, SerializedCommand } from '../types/commands';
import type { Point2D, Uuid } from '../types/common';
import type { GeoJsonGeometry } from '../types/geo';
import {
  canRedo as stacksCanRedo,
  canUndo as stacksCanUndo,
  createAddAnnotation,
  executeCommand,
  peekRedoLabel as stacksPeekRedo,
  peekUndoLabel as stacksPeekUndo,
  redoCommand,
  serializeCommand,
  undoCommand,
  type CommandStacks,
} from '../lib/commands';

// ─────────────────────────────────────────────────────────────────────────────
// Client identity
// ─────────────────────────────────────────────────────────────────────────────

const TEMP_PREFIX = 'tmp-';

/** A client-side identity for an annotation the server has never seen. */
export const newClientId = (): Uuid => `${TEMP_PREFIX}${newId()}` as Uuid;

/** Has this annotation ever been persisted? Drives `op: 'create'` vs `'update'`. */
export const isTempId = (id: string): boolean => id.startsWith(TEMP_PREFIX);

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────

export interface AnnotationDraftState {
  image_id: Uuid | null;
  /**
   * ★ The revision this draft descends from, for optimistic concurrency
   *   (`AnnotationBulkUpsertRequest.base_revision_seq`).
   *
   * ★ 50-frontend's `baseVersionId: Uuid` is **void**: the wire field is
   *   `base_revision_seq`, a NUMBER (`types/annotation.ts`), and `RevisionSummary`
   *   carries `seq`. There is no `baseVersionId` on any schema.
   */
  base_revision_seq: number | null;
  /** ★ Array order IS z-order / creation order. Commands are pure over this array. */
  annotations: AnnotationRead[];
  /** For auto-labelling `P1`, `P2`, … */
  next_ordinal: number;
  /** ★ See the header. Client identity → the server's real UUID, once known. */
  server_id_by_client_id: Record<string, Uuid>;
}

/** The polygon/polyline being drawn. ★ OUTSIDE the command system — see below. */
export interface InProgressShape {
  kind: 'polygon' | 'polyline';
  /** ★ ORIGINAL image px. */
  vertices: Point2D[];
  /** Rubber-band to the cursor. */
  previewVertex: Point2D | null;
}

export interface AnnotationState {
  draft: AnnotationDraftState;
  inProgress: InProgressShape | null;
  undoStack: AnnotationCommand[];
  redoStack: AnnotationCommand[];
  dirty: boolean;
  lastSavedAt: number | null;
  /**
   * ★ Non-null = viewing history; the draft is FROZEN and read-only (§4.3 step 1).
   *   An annotation VERSION id is a JSON number (`annotation_versions.id` is BIGSERIAL),
   *   NOT a Uuid — a project revision id is the Uuid (see `VersionHistoryDrawer`).
   */
  previewVersionId: number | null;
  /**
   * ★ Human-readable provenance since the last save — what powers the version
   *   drawer's "Added 3 points, moved P2" summary (§4.5).
   *
   * ★ **NOT sent to the server.** `AnnotationBulkUpsertRequest` has no change-log
   *   field (`mode`, `base_revision_seq`, `revision_label`, `client_op_id`, `items`
   *   — that is all of it). 50-frontend §4.6's POST body carrying `changeLog` +
   *   `clientCommandCursor` describes an endpoint that does not exist. The server
   *   derives `annotation_versions.change_log` from the diff it applies; it must
   *   never have to replay frontend command semantics to know what an annotation set
   *   is (§4.5, and it is right).
   */
  changeLog: SerializedCommand[];

  // lifecycle
  hydrate: (
    image_id: Uuid,
    annotations: AnnotationRead[],
    base_revision_seq: number | null,
  ) => void;
  reset: () => void;

  // ★ THE ONLY mutation path (§4)
  execute: (cmd: AnnotationCommand) => void;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
  peekUndoLabel: () => string | null;
  peekRedoLabel: () => string | null;

  // in-progress shape building
  beginShape: (kind: 'polygon' | 'polyline', at: Point2D) => void;
  extendShape: (at: Point2D) => void;
  updatePreview: (at: Point2D | null) => void;
  commitShape: (close: boolean) => void;
  cancelShape: () => void;

  // history preview
  setPreviewVersion: (id: number | null) => void;

  // persistence
  markSaved: (response: AnnotationBulkUpsertResponse) => void;
  /** Build the bulk-upsert body. ★ Resolves client ids → server ids. */
  toBulkUpsertItems: () => AnnotationBulkUpsertItem[];
  serverIdOf: (client_id: string) => Uuid | null;
  /** Look up a draft annotation by its client id. */
  byId: (client_id: string) => AnnotationRead | null;
  /**
   * ★ Reserve the next auto-label ordinal (`P1`, `P2`, …) and advance the counter.
   *   Points created in `ImageViewer` share this monotonic counter with `commitShape`
   *   so labels stay UNIQUE across the whole session — including after a delete
   *   (which would let `annotations.length + 1` reuse a number) and across a mix of
   *   points and shapes (which used two separate counters and could collide).
   */
  allocateOrdinal: () => number;
}

const emptyDraft = (): AnnotationDraftState => ({
  image_id: null,
  base_revision_seq: null,
  annotations: [],
  next_ordinal: 1,
  server_id_by_client_id: {},
});

// ─────────────────────────────────────────────────────────────────────────────
// Factory for a brand-new annotation (the draft's own shape)
// ─────────────────────────────────────────────────────────────────────────────

const nowIso = (): string => new Date().toISOString();

/**
 * A client-side `AnnotationRead` for a shape the surveyor just drew.
 *
 * ★ The server-owned fields are filled with the HONEST empty value, never a guess:
 *   `version_no: 0` (never persisted), `gcp_ids: []`, `gcp_id: null`,
 *   `is_gcp_candidate` derived by the SAME rule the server uses. On the first save
 *   the server's authoritative values replace all of them ({@link markSaved}).
 */
function draftAnnotation(args: {
  image_id: Uuid;
  kind: AnnotationKind;
  geom_type: AnnotationGeomType;
  geometry: GeoJsonGeometry;
  representative: Point2D;
  label: string | null;
  ordering: number;
}): AnnotationRead {
  const ts = nowIso();
  return {
    id: newClientId(),
    image_id: args.image_id,
    kind: args.kind,
    geom_type: args.geom_type,
    pixel_x: args.representative.x,
    pixel_y: args.representative.y,
    geometry: args.geometry,
    label: args.label,
    description: null,
    // ★ 0–1, the surveyor's own certainty about the ANNOTATION. Defaults to 1: the
    //   surveyor just pointed at it. NOT `GcpRead.confidence` (0–100) and NOT
    //   `declared_confidence` (1–5) — three scales, deliberately not unified (§6.1).
    confidence: 1,
    ordering: args.ordering,
    style: {},
    attributes: {},
    version_no: 0,
    revision_seq: 0,
    is_deleted: false,
    is_gcp_candidate: isGcpCandidateKind(args.kind),
    gcp_ids: [],
    gcp_id: null,
    created_by: null,
    updated_by: null,
    created_at: ts as AnnotationRead['created_at'],
    updated_at: ts as AnnotationRead['updated_at'],
  };
}

/**
 * ★ Mirrors the server's derivation exactly (`types/annotation.ts`):
 *   `kind ∈ {field_corner, road_intersection, building_corner}`.
 *
 * ★ There is deliberately NO `geom_type === 'point'` clause: the representative
 *   point IS the candidate location for any geometry type — that is what it is for —
 *   so "a polygon corner can be a GCP" works.
 */
export function isGcpCandidateKind(kind: AnnotationKind): boolean {
  return kind === 'field_corner' || kind === 'road_intersection' || kind === 'building_corner';
}

/** The centroid of a ring — the client's provisional representative point. */
const centroid = (pts: readonly Point2D[]): Point2D => {
  if (pts.length === 0) return { x: 0, y: 0 };
  const sum = pts.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }), { x: 0, y: 0 });
  return { x: sum.x / pts.length, y: sum.y / pts.length };
};

// ─────────────────────────────────────────────────────────────────────────────
// The store
// ─────────────────────────────────────────────────────────────────────────────

export const useAnnotationStore = create<AnnotationState>()(
  devtools(
    (set, get) => {
      const stacksOf = (): CommandStacks => ({
        undoStack: get().undoStack,
        redoStack: get().redoStack,
      });

      return {
        draft: emptyDraft(),
        inProgress: null,
        undoStack: [],
        redoStack: [],
        dirty: false,
        lastSavedAt: null,
        previewVersionId: null,
        changeLog: [],

        // ── lifecycle ────────────────────────────────────────────────────────
        /**
         * ★ **Stacks are CLEARED on hydrate** (§4.3). An image change or a version
         *   restore establishes a new baseline; carrying a stack across images would
         *   let an undo apply a command to an annotation that does not exist.
         */
        hydrate: (image_id, annotations, base_revision_seq) =>
          set(
            {
              draft: {
                image_id,
                base_revision_seq,
                annotations,
                next_ordinal: annotations.length + 1,
                // Server-hydrated annotations already carry their real id.
                server_id_by_client_id: Object.fromEntries(annotations.map((a) => [a.id, a.id])),
              },
              inProgress: null,
              undoStack: [],
              redoStack: [],
              dirty: false,
              lastSavedAt: null,
              previewVersionId: null,
              changeLog: [],
            },
            false,
            'annotation/hydrate',
          ),

        reset: () =>
          set(
            {
              draft: emptyDraft(),
              inProgress: null,
              undoStack: [],
              redoStack: [],
              dirty: false,
              lastSavedAt: null,
              previewVersionId: null,
              changeLog: [],
            },
            false,
            'annotation/reset',
          ),

        // ── the command path (§4.3) ──────────────────────────────────────────
        execute: (cmd) => {
          const s = get();
          // ★ Step 1 — history preview is READ-ONLY. Silently editing a version the
          //   surveyor is only LOOKING at would write to the live draft behind a UI
          //   that says they are in the past.
          if (s.previewVersionId !== null) return;

          const r = executeCommand(s.draft.annotations, stacksOf(), cmd);
          set(
            {
              draft: { ...s.draft, annotations: r.annotations },
              undoStack: r.stacks.undoStack,
              redoStack: r.stacks.redoStack,
              dirty: true,
              // Mirror the stack's coalescing: a merged command REPLACES the last
              // log entry, so the drawer says "moved P2" once, not forty times.
              changeLog:
                r.command && r.command.id !== cmd.id
                  ? [...s.changeLog.slice(0, -1), serializeCommand(r.command)]
                  : [...s.changeLog, serializeCommand(cmd)],
            },
            false,
            `annotation/execute:${cmd.type}`,
          );
        },

        undo: () => {
          const s = get();
          if (s.previewVersionId !== null) return;
          const r = undoCommand(s.draft.annotations, stacksOf());
          if (!r.changed) return;
          set(
            {
              draft: { ...s.draft, annotations: r.annotations },
              undoStack: r.stacks.undoStack,
              redoStack: r.stacks.redoStack,
              dirty: true,
            },
            false,
            'annotation/undo',
          );
        },

        redo: () => {
          const s = get();
          if (s.previewVersionId !== null) return;
          const r = redoCommand(s.draft.annotations, stacksOf());
          if (!r.changed) return;
          set(
            {
              draft: { ...s.draft, annotations: r.annotations },
              undoStack: r.stacks.undoStack,
              redoStack: r.stacks.redoStack,
              dirty: true,
            },
            false,
            'annotation/redo',
          );
        },

        canUndo: () => get().previewVersionId === null && stacksCanUndo(stacksOf()),
        canRedo: () => get().previewVersionId === null && stacksCanRedo(stacksOf()),
        peekUndoLabel: () => stacksPeekUndo(stacksOf()),
        peekRedoLabel: () => stacksPeekRedo(stacksOf()),

        // ── in-progress shape (§4.3) ─────────────────────────────────────────
        /**
         * ★ `inProgress` is deliberately OUTSIDE the command system. A half-drawn
         *   polygon is not an edit. That is why `Escape` cancels a drawing WITHOUT
         *   polluting the undo stack, and why undo after a completed polygon removes
         *   the whole polygon rather than one vertex — which is what users expect.
         */
        beginShape: (kind, at) =>
          set(
            { inProgress: { kind, vertices: [at], previewVertex: null } },
            false,
            'annotation/beginShape',
          ),

        extendShape: (at) =>
          set(
            (s) =>
              s.inProgress
                ? { inProgress: { ...s.inProgress, vertices: [...s.inProgress.vertices, at] } }
                : s,
            false,
            'annotation/extendShape',
          ),

        updatePreview: (at) =>
          set(
            (s) => (s.inProgress ? { inProgress: { ...s.inProgress, previewVertex: at } } : s),
            false,
            'annotation/updatePreview',
          ),

        cancelShape: () => set({ inProgress: null }, false, 'annotation/cancelShape'),

        /** ★ The ONE place a drawn shape becomes an undoable `add_annotation`. */
        commitShape: (close) => {
          const s = get();
          const ip = s.inProgress;
          const image_id = s.draft.image_id;
          if (!ip || !image_id) return;

          const pts = ip.vertices;
          // ★ Refuse rather than commit a degenerate shape (L12): a polyline needs
          //   ≥ 2 points and a polygon ≥ 3 distinct ones, or the API returns
          //   `422 ANNOTATION_GEOMETRY_INVALID`. Dropping the half-drawn shape here
          //   is honest; sending it and surfacing a 422 blames the surveyor.
          const min = ip.kind === 'polygon' ? 3 : 2;
          if (pts.length < min) {
            set({ inProgress: null }, false, 'annotation/commitShape:discard');
            return;
          }

          const geom_type: AnnotationGeomType = ip.kind;
          let geometry: GeoJsonGeometry;
          if (ip.kind === 'polygon') {
            // ★ Close the ring: first === last, ≥ 4 positions (`types/annotation.ts`).
            const ring: [number, number][] = pts.map((p) => [p.x, p.y]);
            ring.push([pts[0]!.x, pts[0]!.y]);
            geometry = { type: 'Polygon', coordinates: [ring] };
          } else {
            geometry = { type: 'LineString', coordinates: pts.map((p) => [p.x, p.y]) };
          }
          // `close` is meaningful only for a polygon; a polyline commits open. The
          // parameter is kept because §3.4 mandates the signature.
          if (ip.kind === 'polyline' && close) {
            geometry = {
              type: 'LineString',
              coordinates: [...pts, pts[0]!].map((p) => [p.x, p.y]),
            };
          }

          const ordinal = s.draft.next_ordinal;
          const annotation = draftAnnotation({
            image_id,
            kind: 'generic',
            geom_type,
            geometry,
            representative: centroid(pts),
            label: `P${ordinal}`,
            ordering: ordinal,
          });

          set(
            { inProgress: null, draft: { ...s.draft, next_ordinal: ordinal + 1 } },
            false,
            'annotation/commitShape',
          );
          get().execute(createAddAnnotation(annotation, get().draft.annotations.length));
        },

        // ── history preview ──────────────────────────────────────────────────
        setPreviewVersion: (id) =>
          set({ previewVersionId: id }, false, 'annotation/setPreviewVersion'),

        // ── persistence ──────────────────────────────────────────────────────
        /**
         * ★ **The server response is AUTHORITATIVE** (§8.5). `response.annotations`
         *   is THE FULL RESULTING LIVE SET, so we replace the field data wholesale
         *   rather than reconciling deltas — one query on the server, and an entire
         *   class of desync gone.
         *
         * ★ The ONE thing we do not take from the server is the `id`. See the header:
         *   the client identity stays stable so the undo stack survives the save
         *   (§4.3), and the real UUID is recorded alongside it.
         *
         * ★ The stacks are UNTOUCHED. A save is a checkpoint, not a barrier.
         */
        markSaved: (response) => {
          const s = get();

          // client_ref → the server's real id, for everything created in this save.
          const clientRefToServerId = new Map<string, Uuid>();
          for (const item of response.items) {
            if (item.client_ref) clientRefToServerId.set(item.client_ref, item.id);
          }

          // Server id → client id, from the prior map PLUS this save's created refs — used
          // only to map the response's live set back onto stable client identities.
          const combined: Record<string, Uuid> = { ...s.draft.server_id_by_client_id };
          for (const [clientId, serverId] of clientRefToServerId) {
            combined[clientId] = serverId;
          }
          const clientIdByServerId = new Map<string, string>();
          for (const [clientId, serverId] of Object.entries(combined)) {
            clientIdByServerId.set(serverId, clientId);
          }

          const annotations = response.annotations.map((a) => {
            const clientId = clientIdByServerId.get(a.id);
            // Take every authoritative field; keep the stable client identity.
            return clientId && clientId !== a.id ? { ...a, id: clientId as Uuid } : a;
          });

          // ★ Rebuild the id map from ONLY the live set the server just returned, so a
          //   deleted annotation's mapping is PRUNED. Otherwise, undoing a delete (which
          //   re-adds the annotation) would emit an ``update`` against a now-soft-deleted
          //   server row → AnnotationNotFound → the whole autosave 4xxs. Pruned, the
          //   re-added annotation has no server id and saves as a fresh ``create``.
          const server_id_by_client_id: Record<string, Uuid> = {};
          for (const a of response.annotations) {
            const clientId = clientIdByServerId.get(a.id) ?? a.id;
            server_id_by_client_id[clientId] = a.id as Uuid;
          }

          set(
            {
              draft: {
                ...s.draft,
                annotations,
                base_revision_seq: response.revision.seq,
                next_ordinal: Math.max(s.draft.next_ordinal, annotations.length + 1),
                server_id_by_client_id,
              },
              dirty: false,
              lastSavedAt: Date.now(),
              changeLog: [],
            },
            false,
            'annotation/markSaved',
          );
        },

        serverIdOf: (client_id) => get().draft.server_id_by_client_id[client_id] ?? null,

        byId: (client_id) => get().draft.annotations.find((a) => a.id === client_id) ?? null,

        allocateOrdinal: () => {
          const n = get().draft.next_ordinal;
          set(
            (s) => ({ draft: { ...s.draft, next_ordinal: n + 1 } }),
            false,
            'annotation/allocateOrdinal',
          );
          return n;
        },

        /**
         * ★ The bulk-upsert body (§6.2). `PUT` on the collection declares the DESIRED
         *   STATE of the image's annotation set and is idempotent — six separate
         *   PATCHes would produce six revisions (making undo useless), six round
         *   trips, and a partially-saved canvas if the fourth fails.
         */
        toBulkUpsertItems: () => {
          const { annotations, server_id_by_client_id } = get().draft;
          return annotations.map((a) => {
            const serverId = server_id_by_client_id[a.id] ?? null;
            const isNew = serverId === null;
            return {
              // ★ Must be null for `create` (`types/annotation.ts`).
              id: isNew ? null : serverId,
              op: isNew ? 'create' : 'update',
              // ★ Required for update — optimistic locking.
              version_no: isNew ? null : a.version_no,
              // ★ Echoed back so we can learn the real UUID.
              client_ref: a.id,
              kind: a.kind,
              geom_type: a.geom_type,
              geometry: a.geometry,
              // ★ NO pixel_x/pixel_y: the server derives the representative point from
              //   `geometry` and its bulk-upsert item schema is extra="forbid" — sending
              //   them 422s the whole save (which is why autosave silently failed).
              label: a.label,
              description: a.description,
              confidence: a.confidence,
              ordering: a.ordering,
              style: a.style,
              attributes: a.attributes,
            } satisfies AnnotationBulkUpsertItem;
          });
        },
      };
    },
    { name: 'annotationStore' },
  ),
);
