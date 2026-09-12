/**
 * `selectionStore` — the cross-pane sync bus. CONTRACT.md §8.5 / 50-frontend.md §3.5.
 *
 * ★ **Small on purpose.** It is read by three panes and must not cause wide
 *   re-renders. Every pane subscribes with a NARROW BOOLEAN selector:
 *
 *   ```ts
 *   const selected = useSelectionStore(s => s.selected.some(r => r.id === myId || r.linkedId === myId));
 *   ```
 *
 *   Zustand's default `Object.is` equality on a boolean means a row/marker/shape
 *   re-renders only when *its own* selected-ness flips — **selecting P3 does not
 *   re-render P1's marker.** {@link isSelectedSelector} is provided so no component
 *   has to get that right by hand.
 *
 * ★ **Selection changes are NOT commands** and never enter the undo stack (§4.4
 *   rule 6). Undo must not "undo" a click.
 *
 * ★ L7 — ids only. No `GcpRead`, no `AnnotationRead`.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

export type EntityKind = 'annotation' | 'gcp';
export type SelectionMode = 'replace' | 'add' | 'range';

/** Who initiated the selection. ★ Reveal is gated on it — see {@link SelectionState.focusOrigin}. */
export type FocusOrigin = 'image' | 'map' | 'table' | null;

export interface SelectionRef {
  kind: EntityKind;
  /**
   * ★ An annotation **client id** (`annotationStore`'s stable identity) or a GCP
   *   `Uuid`. Documented as exactly that in §3.4 — which is what makes the stable
   *   client identity the contract's own assumption, not this unit's invention.
   */
  id: string;
  /** The gcp↔annotation counterpart. Populated by `useGcpRows` from `GcpRead.landmark_id`. */
  linkedId: string | null;
}

export interface SelectionState {
  selected: SelectionRef[];
  hovered: SelectionRef | null;
  /** For shift-range selection in the GCP table. */
  anchorId: string | null;
  /**
   * ★ **A pane never auto-scrolls in response to its own action.**
   *
   *   `if (selected && focusOrigin !== 'map') flyToGcp()` — a selection made in the
   *   table brings the point into view in both other panes; a selection made by
   *   clicking the map does not yank the map. This is what prevents "the map fights
   *   me when I click it."
   */
  focusOrigin: FocusOrigin;

  select: (ref: SelectionRef, mode: SelectionMode, origin: FocusOrigin) => void;
  selectMany: (refs: SelectionRef[], origin: FocusOrigin) => void;
  clear: () => void;
  setHovered: (ref: SelectionRef | null) => void;
  isSelected: (id: string) => boolean;
}

/** Does `ref` refer to `id`, on either side of the link? */
const refMatches = (r: SelectionRef, id: string): boolean => r.id === id || r.linkedId === id;

export const useSelectionStore = create<SelectionState>()(
  devtools(
    (set, get) => ({
      selected: [],
      hovered: null,
      anchorId: null,
      focusOrigin: null,

      /**
       * ★ `'range'` is resolved by the CALLER (`GcpTable`), which is the only thing
       *   that knows the row order, and it calls {@link selectMany}. Treating it as
       *   `replace` here would make a shift-click silently drop the range — worse
       *   than not supporting it.
       */
      select: (ref, mode, origin) =>
        set(
          (s) => {
            if (mode === 'add') {
              const already = s.selected.some((r) => r.id === ref.id);
              return {
                selected: already
                  ? s.selected.filter((r) => r.id !== ref.id)
                  : [...s.selected, ref],
                anchorId: ref.id,
                focusOrigin: origin,
              };
            }
            return { selected: [ref], anchorId: ref.id, focusOrigin: origin };
          },
          false,
          `selection/select:${mode}`,
        ),

      selectMany: (refs, origin) =>
        set(
          { selected: refs, anchorId: refs[refs.length - 1]?.id ?? null, focusOrigin: origin },
          false,
          'selection/selectMany',
        ),

      clear: () =>
        set({ selected: [], anchorId: null, focusOrigin: null }, false, 'selection/clear'),

      /**
       * ★ Hover NEVER triggers reveal (§3.5) — it produces a pulse in the counterpart
       *   panes and nothing more. Throttling to one rAF is the CALLER's job; doing it
       *   here would add a timer to a store three panes subscribe to.
       */
      setHovered: (ref) => set({ hovered: ref }, false, 'selection/setHovered'),

      isSelected: (id) => get().selected.some((r) => refMatches(r, id)),
    }),
    { name: 'selectionStore' },
  ),
);

/**
 * ★ **THE selector every pane should use.** Returns a BOOLEAN, so Zustand's default
 *   `Object.is` equality re-renders the subscriber only when its own selected-ness
 *   flips (§3.5). Building this inline per component is how a `useShallow`-less array
 *   selector sneaks in and re-renders every marker on every click.
 *
 * ```ts
 * const selected = useSelectionStore(isSelectedSelector(myId));
 * const hovered  = useSelectionStore(isHoveredSelector(myId));
 * ```
 */
export const isSelectedSelector =
  (id: string) =>
  (s: SelectionState): boolean =>
    s.selected.some((r) => refMatches(r, id));

export const isHoveredSelector =
  (id: string) =>
  (s: SelectionState): boolean =>
    s.hovered !== null && refMatches(s.hovered, id);
