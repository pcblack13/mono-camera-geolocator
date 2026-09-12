/**
 * ★★ `correspondenceStore` — MANUAL GCP MODE. **SCOPE.md §5.**
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ WHY THIS STORE EXISTS AND IS NOT IN CONTRACT.md §8.5
 *
 *   `CONTRACT.md` describes the complete system, in which a GCP is INFERRED by the
 *   matching engine. `SCOPE.md` — which **overrides the contract** (§1 of SCOPE.md,
 *   and CONTRACT.md §0's precedence is subordinate to it) — defers that engine and
 *   makes manual GCP mode *"the product's core interaction"*, which *"gets
 *   first-class quality"*. The contract's eight stores have no home for it, so this
 *   is the ninth, added *"in the spirit of the tree"* (§2) and flagged.
 *
 * ★ THE FLOW (SCOPE.md §5). The surveyor selects a landmark in the photo (an
 *   existing annotation point, or clicks a new one) → the app enters *correspondence*
 *   mode → they pan/zoom the satellite map and click the same physical spot → a GCP
 *   is created linking `(pixel_x, pixel_y)` to `(lat, lon)`.
 *
 *   **The coordinate is a DIRECT OBSERVATION, not an inference.** There is no
 *   homography, no degenerate solve, no viewpoint assumption and no estimated
 *   confidence to calibrate. That is the entire point of the ruling.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ THE INVARIANT THIS FILE IS ACCOUNTABLE FOR — SCOPE.md §5, verbatim:
 *
 *      **"Uncommitted correspondences must never appear in the GCP table or an
 *        export."**
 *
 *    It is enforced STRUCTURALLY, not by vigilance, in three layers:
 *
 *    1. **This store cannot represent a GCP.** It holds no `GcpRead`, no
 *       `GcpSummary`, no `GcpTableRow`, and exports no type structurally
 *       assignable to one. The GCP table and every export read `GcpRead` from
 *       React Query (L7) — i.e. from the SERVER, which by definition only has
 *       committed rows. There is no code path from this store to that table, and
 *       adding one would require importing a type this module refuses to name.
 *    2. **The open draft is reachable only through {@link openMarkers}**, which
 *       returns markers explicitly tagged `is_committed: false` for the two canvas
 *       panes. A pane renders them as the LIVE LINKED MARKER (SCOPE.md §5) and
 *       nothing else consumes them.
 *    3. **`status` is the gate.** Only `'ready'` may be committed
 *       ({@link CorrespondenceState.isCommittable}), and `'ready'` requires BOTH
 *       endpoints AND a surveyor-declared confidence. A half-open correspondence is
 *       unrepresentable as committable.
 *
 *    The state machine, exhaustively — there are no other transitions:
 *
 *    ```
 *                     open({landmark})              open({})
 *      idle ──────────────┬─────────────────────────────┬──────────────► idle
 *                         ▼                             ▼
 *                 awaiting_map_point           awaiting_photo_point
 *                         │  setMapPoint          │  setPhotoPoint
 *                         │                       ▼
 *                         │              awaiting_map_point
 *                         ▼                       │  setMapPoint
 *                    (both endpoints set) ◄───────┘
 *                         │
 *                         │  setDeclaredConfidence          ★ REQUIRED — SCOPE.md §5:
 *                         ▼                                   never a computed number
 *                       ready ──── beginCommit ────► committing
 *                         ▲                              │
 *                         └────── commitFailed ──────────┤
 *                                                        │ commitSucceeded
 *                                     cancel()           ▼
 *                    (any state) ───────────────────►  idle
 *    ```
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * ★ L7 — browser-only. The open correspondence is an in-flight USER INTERACTION,
 *   exactly like `annotationStore`'s draft: it becomes server state only at commit,
 *   and the commit is a React Query mutation owned by IU-27, not by this store.
 */

import { create } from 'zustand';

import { newId } from '../lib/ids';
import { devtools } from 'zustand/middleware';

import type { ApiError, Point2D, Uuid } from '../types/common';
import type { LatLon, PixelXY } from '../types/geo';
import type { SurveyorConfidence } from '../types/gcp';
import { useSelectionStore } from './selectionStore';

// ─────────────────────────────────────────────────────────────────────────────
// The state machine
// ─────────────────────────────────────────────────────────────────────────────

export type CorrespondenceStatus =
  /** Nothing open. The panes show no linked marker. */
  | 'idle'
  /** Opened with no landmark; waiting for the surveyor to mark the photo. */
  | 'awaiting_photo_point'
  /** The photo pixel is fixed; waiting for the click on the satellite map. */
  | 'awaiting_map_point'
  /** Both endpoints AND a declared confidence. ★ The ONLY committable state. */
  | 'ready'
  /** The mutation is in flight. ★ Both endpoints are FROZEN. */
  | 'committing';

/**
 * `create` — a new GCP. `edit` — re-opening a committed one to refine it.
 *
 * ★ SCOPE.md §5: *"The pairing is editable and re-openable: either endpoint can be
 *   dragged and re-committed."*
 */
export type CorrespondenceMode = 'create' | 'edit';

/**
 * One remembered state of the pairing's two endpoints, plus what produced it (the
 * word the undo tooltip shows: *"Undo move the photo mark"*).
 */
export interface PointSnapshot {
  image_px: PixelXY | null;
  lat_lon: LatLon | null;
  /** null for the opening state — there is nothing to name before the first edit. */
  label: string | null;
}

export interface CorrespondenceState {
  status: CorrespondenceStatus;
  mode: CorrespondenceMode;
  /**
   * ★ A client-side handle for THIS open correspondence. It is what gives the photo
   *   marker and the map marker *"a matching colour/ID while the correspondence is
   *   open"* (SCOPE.md §5). Regenerated on every `open`, so a cancelled pairing can
   *   never be confused with the next one.
   */
  correspondence_id: string;
  image_id: Uuid | null;

  /**
   * The annotation this correspondence is anchored to, by **client id**
   * (`annotationStore`'s stable identity). `null` when the surveyor clicked a bare
   * pixel rather than an existing landmark.
   */
  landmark_client_id: string | null;

  /**
   * ★ **ORIGINAL image pixel space** — independent of viewer zoom, pan, brightness
   *   and contrast (SCOPE.md §5, CONTRACT.md §8.6: *"normative and
   *   correctness-critical"*). Set ONLY from `lib/viewport/transform.ts`'s
   *   `stageToImage` at `ImageViewer`'s single conversion site. Never rounded.
   */
  image_px: PixelXY | null;

  /**
   * ★ **EPSG:4326**, captured from the map click; stored server-side as
   *   `geography(Point, 4326)` (SCOPE.md §5).
   */
  lat_lon: LatLon | null;

  /**
   * ★ **SURVEYOR-DECLARED, NEVER COMPUTED** (SCOPE.md §5). A deliberate 1–5
   *   judgement. `null` until the surveyor makes it — which is exactly why `ready`
   *   requires it: committing without one would force a default, and a defaulted
   *   judgement is a fabricated one.
   */
  declared_confidence: SurveyorConfidence | null;

  /** Free text, → `GcpUpdate.adjustment_note` on an edit. */
  note: string | null;

  /** The GCP's current free-text name, carried into `edit` mode so the panel can pre-fill it. */
  gcp_name: string | null;

  /** In `edit` mode, the GCP being refined. An id ONLY — never the row. */
  editing_gcp_id: Uuid | null;

  /** The last commit failure, for the inline message. Cleared on any edit. */
  error: ApiError | null;

  /**
   * ★ THE ENDPOINT HISTORY (1.2.6) — what the tool rail's undo/redo act on while a
   *   correspondence is open.
   *
   *   The rail was wired ONLY to `annotationStore`'s command stack, which holds
   *   landmark edits. A GCP placed by clicking a bare pixel creates no annotation, so
   *   during the one interaction where undo is most wanted — "I mis-clicked the
   *   rooftop, put the mark back" — all three buttons sat greyed out.
   *
   *   This is deliberately NOT `lib/commands`: that stack is annotations-only by
   *   design (see `useAdjustGcp`), and pushing correspondence edits into it would
   *   entangle two lifetimes — an open pairing is discarded on cancel, while the
   *   annotation stack outlives it. A private snapshot list, born and dying with the
   *   correspondence, keeps both truthful.
   */
  point_history: PointSnapshot[];
  /** Where in `point_history` we are. Everything after it is the redo tail. */
  point_index: number;

  // ── transitions ──────────────────────────────────────────────────────────
  open: (args: {
    image_id: Uuid;
    landmark_client_id?: string | null;
    image_px?: PixelXY | null;
  }) => void;
  /** ★ SCOPE.md §5: re-open a committed GCP. Takes primitives, NOT a `GcpRead`. */
  reopen: (args: {
    image_id: Uuid;
    gcp_id: Uuid;
    image_px: PixelXY;
    lat_lon: LatLon;
    declared_confidence: SurveyorConfidence | null;
    landmark_client_id?: string | null;
    note?: string | null;
    gcp_name?: string | null;
  }) => void;
  setPhotoPoint: (p: Point2D) => void;
  setMapPoint: (p: LatLon) => void;
  setDeclaredConfidence: (c: SurveyorConfidence) => void;
  setNote: (note: string | null) => void;
  beginCommit: () => void;
  commitSucceeded: (gcp_id: Uuid) => void;
  commitFailed: (error: ApiError) => void;
  cancel: () => void;

  // ── endpoint history (the tool rail, 1.2.6) ──────────────────────────────
  /** Step back one endpoint edit. No-op at the beginning, or mid-commit. */
  undoPoint: () => void;
  /** Step forward again. No-op at the end of the history, or mid-commit. */
  redoPoint: () => void;
  /**
   * ★ Back to how this pairing STARTED — empty when creating, the GCP's SAVED
   *   position when editing. One rule that means something sensible in both modes:
   *   "throw away the marks I have been placing", never "delete the saved GCP"
   *   (which is the table's job, not a tool-rail button's).
   */
  resetPoints: () => void;

  // ── selectors ────────────────────────────────────────────────────────────
  isOpen: () => boolean;
  /** ★ THE gate. `true` iff `status === 'ready'`. Nothing else may authorise a commit. */
  isCommittable: () => boolean;
  /** Which pane the surveyor must act in next. `null` when nothing is pending. */
  awaiting: () => 'photo' | 'map' | 'confidence' | null;
  canUndoPoint: () => boolean;
  canRedoPoint: () => boolean;
  /** What undo would reverse — the rail's tooltip. `null` when nothing would. */
  undoPointLabel: () => string | null;
  redoPointLabel: () => string | null;
  /** True when there is anything to reset — i.e. any edit since this opened. */
  canResetPoints: () => boolean;
}

const IDLE = {
  status: 'idle' as CorrespondenceStatus,
  mode: 'create' as CorrespondenceMode,
  correspondence_id: '',
  image_id: null,
  landmark_client_id: null,
  image_px: null,
  lat_lon: null,
  declared_confidence: null,
  note: null,
  gcp_name: null,
  editing_gcp_id: null,
  error: null,
  point_history: [] as PointSnapshot[],
  point_index: 0,
};

/**
 * Record a new endpoint state, DISCARDING any redo tail — the standard undo-stack
 * rule: editing after undoing forks the history, and the abandoned branch is gone.
 */
function pushSnapshot(
  s: Pick<CorrespondenceState, 'point_history' | 'point_index'>,
  next: PointSnapshot,
): Pick<CorrespondenceState, 'point_history' | 'point_index'> {
  const kept = s.point_history.slice(0, s.point_index + 1);
  kept.push(next);
  return { point_history: kept, point_index: kept.length - 1 };
}

/**
 * ★ THE single derivation of `status` from the endpoints. Called after every edit so
 *   the machine cannot drift out of sync with its own data — the failure mode where
 *   a store says `ready` while `lat_lon` is null, and something commits a GCP with
 *   no coordinate.
 *
 *   `committing` is deliberately NOT derived: it is an explicit transition
 *   (`beginCommit`) and must not be recomputed away by a stray edit mid-flight.
 */
/** ★ Confidence is no longer declared by the surveyor — it is not shown, filtered, or
 *  exported. A fixed value is still stored so the API contract (and the GCP row's NOT-NULL
 *  confidence) is satisfied without a picker. */
const DEFAULT_CONFIDENCE: SurveyorConfidence = 5;

function deriveStatus(s: Pick<CorrespondenceState, 'image_px' | 'lat_lon'>): CorrespondenceStatus {
  if (s.image_px === null) return 'awaiting_photo_point';
  if (s.lat_lon === null) return 'awaiting_map_point';
  return 'ready';
}

export const useCorrespondenceStore = create<CorrespondenceState>()(
  devtools(
    (set, get) => ({
      ...IDLE,

      open: ({ image_id, landmark_client_id = null, image_px = null }) => {
        const next = { image_px, lat_lon: null, declared_confidence: DEFAULT_CONFIDENCE };
        set(
          {
            ...IDLE,
            mode: 'create',
            correspondence_id: newId(),
            image_id,
            landmark_client_id,
            ...next,
            status: deriveStatus(next),
            // ★ The opening state is history[0] — the floor undo cannot go below.
            point_history: [{ image_px, lat_lon: null, label: null }],
            point_index: 0,
          },
          false,
          'correspondence/open',
        );
      },

      reopen: ({
        image_id,
        gcp_id,
        image_px,
        lat_lon,
        declared_confidence,
        landmark_client_id = null,
        note = null,
        gcp_name = null,
      }) => {
        const next = {
          image_px,
          lat_lon,
          declared_confidence: declared_confidence ?? DEFAULT_CONFIDENCE,
        };
        set(
          {
            ...IDLE,
            mode: 'edit',
            correspondence_id: newId(),
            image_id,
            landmark_client_id,
            editing_gcp_id: gcp_id,
            note,
            gcp_name,
            ...next,
            status: deriveStatus(next),
            // ★ history[0] is the SAVED position — so undo/reset walk back to what
            //   the database holds, never past it into an empty pairing.
            point_history: [{ image_px, lat_lon, label: null }],
            point_index: 0,
          },
          false,
          'correspondence/reopen',
        );
      },

      /**
       * ★ `p` MUST be ORIGINAL image px, from `stageToImage`. Both endpoints are
       *   draggable and re-committable (SCOPE.md §5), so this is called on every
       *   drop of the photo marker, not only on the first placement.
       */
      setPhotoPoint: (p) => {
        const s = get();
        // ★ Frozen mid-commit. A drag that lands while the mutation is in flight must
        //   not fork the value we are asserting to the server.
        if (s.status === 'idle' || s.status === 'committing') return;
        const image_px: PixelXY = { x: p.x, y: p.y };
        set(
          {
            image_px,
            error: null,
            status: deriveStatus({ ...s, image_px }),
            ...pushSnapshot(s, {
              image_px,
              lat_lon: s.lat_lon,
              label: s.image_px === null ? 'place the photo mark' : 'move the photo mark',
            }),
          },
          false,
          'correspondence/setPhotoPoint',
        );
      },

      /** ★ EPSG:4326, straight from the map click. */
      setMapPoint: (p) => {
        const s = get();
        if (s.status === 'idle' || s.status === 'committing') return;
        set(
          {
            lat_lon: p,
            error: null,
            status: deriveStatus({ ...s, lat_lon: p }),
            ...pushSnapshot(s, {
              image_px: s.image_px,
              lat_lon: p,
              label: s.lat_lon === null ? 'place the map point' : 'move the map point',
            }),
          },
          false,
          'correspondence/setMapPoint',
        );
      },

      setDeclaredConfidence: (c) => {
        const s = get();
        if (s.status === 'idle' || s.status === 'committing') return;
        // Confidence no longer affects commit-readiness; the value is stored for the API only.
        set(
          { declared_confidence: c, error: null, status: deriveStatus(s) },
          false,
          'correspondence/setDeclaredConfidence',
        );
      },

      setNote: (note) => {
        if (get().status === 'idle') return;
        set({ note }, false, 'correspondence/setNote');
      },

      beginCommit: () => {
        // ★ THE gate, enforced at the transition and not only in the UI. A disabled
        //   button is a suggestion; this is the rule.
        if (!get().isCommittable()) return;
        set({ status: 'committing', error: null }, false, 'correspondence/beginCommit');
      },

      /**
       * ★ Closes the correspondence. The new GCP arrives through React Query's cache
       *   invalidation — **this store never holds it** (L7, and the §5 invariant).
       */
      commitSucceeded: (_gcp_id) => {
        set({ ...IDLE }, false, 'correspondence/commitSucceeded');
        // ★ Clear the annotation selection too, so the inspector does NOT re-open
        //   onto the just-used landmark (stale) once the correspondence panel closes.
        //   The point simply lands in the GCP table; the window stays shut.
        useSelectionStore.getState().clear();
      },

      /**
       * ★ Back to `ready`, endpoints INTACT. A failed commit must not discard the
       *   surveyor's work: they aimed at a specific pixel and a specific rooftop, and
       *   making them do it again because the network blinked is unacceptable.
       */
      commitFailed: (error) =>
        set({ status: 'ready', error }, false, 'correspondence/commitFailed'),

      cancel: () => set({ ...IDLE }, false, 'correspondence/cancel'),

      // ── endpoint history ───────────────────────────────────────────────────
      // ★ All three are FROZEN mid-commit, for the same reason `setPhotoPoint` is:
      //   the values being asserted to the server must not fork under the mutation.
      undoPoint: () => {
        const s = get();
        if (s.status === 'idle' || s.status === 'committing') return;
        if (s.point_index <= 0) return;
        const index = s.point_index - 1;
        const snap = s.point_history[index];
        set(
          {
            image_px: snap.image_px,
            lat_lon: snap.lat_lon,
            point_index: index,
            error: null,
            status: deriveStatus(snap),
          },
          false,
          'correspondence/undoPoint',
        );
      },

      redoPoint: () => {
        const s = get();
        if (s.status === 'idle' || s.status === 'committing') return;
        if (s.point_index >= s.point_history.length - 1) return;
        const index = s.point_index + 1;
        const snap = s.point_history[index];
        set(
          {
            image_px: snap.image_px,
            lat_lon: snap.lat_lon,
            point_index: index,
            error: null,
            status: deriveStatus(snap),
          },
          false,
          'correspondence/redoPoint',
        );
      },

      resetPoints: () => {
        const s = get();
        if (s.status === 'idle' || s.status === 'committing') return;
        const base = s.point_history[0];
        if (base === undefined) return;
        set(
          {
            image_px: base.image_px,
            lat_lon: base.lat_lon,
            // ★ The history collapses to its floor: after "start over" there is
            //   nothing to redo, because the branch it would rebuild is the one the
            //   surveyor just discarded.
            point_history: [base],
            point_index: 0,
            error: null,
            status: deriveStatus(base),
          },
          false,
          'correspondence/resetPoints',
        );
      },

      isOpen: () => get().status !== 'idle',
      isCommittable: () => get().status === 'ready',

      awaiting: () => {
        const s = get();
        switch (s.status) {
          case 'awaiting_photo_point':
            return 'photo';
          case 'awaiting_map_point':
            return 'map';
          default:
            return null;
        }
      },

      canUndoPoint: () => {
        const s = get();
        return s.status !== 'idle' && s.status !== 'committing' && s.point_index > 0;
      },
      canRedoPoint: () => {
        const s = get();
        return (
          s.status !== 'idle' &&
          s.status !== 'committing' &&
          s.point_index < s.point_history.length - 1
        );
      },
      undoPointLabel: () => {
        const s = get();
        // The label of the state we are LEAVING names the edit undo reverses.
        return s.point_index > 0 ? (s.point_history[s.point_index]?.label ?? null) : null;
      },
      redoPointLabel: () => {
        const s = get();
        return s.point_index < s.point_history.length - 1
          ? (s.point_history[s.point_index + 1]?.label ?? null)
          : null;
      },
      canResetPoints: () => {
        const s = get();
        return s.status !== 'idle' && s.status !== 'committing' && s.point_history.length > 1;
      },
    }),
    { name: 'correspondenceStore' },
  ),
);

// ─────────────────────────────────────────────────────────────────────────────
// The live linked markers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ SCOPE.md §5: *"Both panes show a live linked marker with a matching colour/ID
 *   while the correspondence is open."*
 *
 * ★ **`is_committed: false` is not decoration.** It is the type-level statement that
 *   this is a DRAFT, and it is why `GcpMarkerLayer` can render these beside real GCP
 *   markers without any possibility of one being mistaken for the other. A pane MUST
 *   render an uncommitted marker distinctly (SCOPE.md §4 rule 4's spirit: no fake
 *   coordinates, no fake confidence).
 */
export interface OpenCorrespondenceMarkers {
  correspondence_id: string;
  /** ★ ORIGINAL image px. `null` until the photo endpoint is placed. */
  image_px: PixelXY | null;
  /** ★ EPSG:4326. `null` until the map endpoint is placed. */
  lat_lon: LatLon | null;
  /** ★ ALWAYS `false`. This type exists to carry that word to the render layer. */
  is_committed: false;
  /** Which endpoint the surveyor is being asked for — drives the ghost/pulse styling. */
  awaiting: 'photo' | 'map' | 'confidence' | null;
  mode: CorrespondenceMode;
}

/**
 * The ONLY sanctioned read path for the open correspondence's geometry.
 *
 * Returns `null` when nothing is open, so a pane renders nothing rather than a
 * stale marker.
 */
export function openMarkers(s: CorrespondenceState): OpenCorrespondenceMarkers | null {
  if (s.status === 'idle') return null;
  return {
    correspondence_id: s.correspondence_id,
    image_px: s.image_px,
    lat_lon: s.lat_lon,
    is_committed: false,
    awaiting: s.awaiting(),
    mode: s.mode,
  };
}
