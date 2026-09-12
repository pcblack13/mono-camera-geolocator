/**
 * The accuracy loop, run for the surveyor instead of by them.
 *
 * ★ IT IS OPT-IN (2026-08-20). Measuring spends a satellite mosaic and minutes of
 *   compute. This loop used to start one the moment a project with four points was
 *   OPENED, and again whenever a setting changed — work nobody asked for, on a
 *   photograph the surveyor may have opened only to look at. Now the automatic cycle
 *   runs only while `autoMeasure` is on (Workspace preference, default OFF). With it
 *   off, nothing here measures: the Measure button is the only trigger, and the
 *   correction and suggestion still follow the measurement it produces.
 *
 * ★ THE WORKFLOW. Four points is the moment a pose exists — and the moment the error
 *   becomes measurable. From there — WHEN THE SWITCH IS ON — the whole cycle runs
 *   itself and repeats after every point placed:
 *
 *       measure → correct → suggest where the next point goes
 *
 *   The surveyor never opens a form. What they get on the picking page is the two
 *   things that change what they do next: a box on the photograph saying where to put
 *   the next point, and the error heat map on the satellite pane. The Accuracy tab
 *   stays available for anyone who wants the evidence behind either.
 *
 * ★ IT STOPS WHEN IT IS DONE, and says so. When the best remaining region would cut
 *   less than the threshold, the suggestion run reports `converged` — and the loop
 *   stops re-measuring. Continuing would spend a satellite mosaic per point to tell the
 *   surveyor something it already knows: that the points they have are enough.
 *
 * ★ IT DOES NOT ADOPT ANYTHING, and that is the point. Adopting would install the
 *   corrected pose as the base the NEXT measurement starts from — so every cycle would
 *   report what the previous correction left, on a baseline that moved underneath it.
 *   The numbers would fall reliably and mean less each time, and no two cycles would be
 *   comparable.
 *
 *   Holding the base at the pose the CONTROL POINTS give keeps every cycle asking the
 *   same question, so the error dropping across cycles means what a surveyor assumes it
 *   means: the points they added made the solve better. Adoption stays a deliberate act
 *   in the Accuracy tab, where the comparison that justifies it is on screen.
 *
 * ★ ONE CYCLE PER POINT COUNT. The guards are keyed by `image:gcpCount`, so placing a
 *   point starts exactly one new cycle and a failure (no DEM, no camera) costs one
 *   attempt rather than an endless retry.
 */

import { useEffect, useRef } from 'react';

import type { Uuid } from '../../types/common';
import { useWorkspaceStore } from '../../store/workspaceStore';
import {
  useAccuracyState,
  useCorrectAccuracy,
  useMeasureAccuracy,
  useSuggestGcps,
} from './useAccuracy';

/** Cycles already started, keyed `image:count` — one per point placed. */
const started = new Set<string>();
/** Corrections already requested, keyed by WHICH measurement they follow. */
const corrected = new Set<string>();
/** Suggestion runs already requested, keyed by WHICH comparison they follow. */
const suggested = new Set<string>();

/** The pose solver's threshold — the same four points Auto GCP needs. */
export const AUTO_MEASURE_MIN_GCPS = 4;

/**
 * ★ ONE region, not four. The loop's question is "where does the NEXT point go?", and
 *   four boxes on the photograph is a menu, not an instruction. The Accuracy tab can
 *   still ask for more.
 */
export const AUTO_SUGGEST_REGIONS = 1;

export interface AccuracyAutopilotOptions {
  /** How many committed GCPs the photograph has. */
  gcpCount: number;
  /** Off while the photograph is not ready (no id, still loading). */
  enabled?: boolean;
}

export interface AccuracyAutopilotStatus {
  /** A stage of the cycle is running right now. */
  running: boolean;
  /** The loop has decided more points would not pay — and will not re-measure. */
  converged: boolean;
  /** What the cycle is doing, in the surveyor's words. */
  message: string | null;
}

export function useAccuracyAutopilot(
  imageId: Uuid | null,
  { gcpCount, enabled = true }: AccuracyAutopilotOptions,
): AccuracyAutopilotStatus {
  // ★ The surveyor's own choice, from the photograph's suggestion control. Default 1:
  //   the loop's question is "where does the NEXT point go", and four boxes is a menu
  //   rather than an instruction — but a menu is what some surveys want.
  const suggestionLimit = useWorkspaceStore((s) => s.suggestionLimit);
  // ★ The switch. OFF by default — see the note at the top of this file.
  const autoMeasure = useWorkspaceStore((s) => s.autoMeasure);
  const stateQuery = useAccuracyState(enabled ? imageId : null);
  const measure = useMeasureAccuracy();
  const correct = useCorrectAccuracy();
  const suggest = useSuggestGcps();

  const state = stateQuery.data;
  const active = state?.active_run ?? null;
  const suggestions = state?.suggestions ?? null;
  const converged = suggestions?.verdict === 'converged';

  // The count the current results belong to. A new point makes them one cycle old.
  const lastCount = useRef<number>(-1);

  useEffect(() => {
    if (!enabled || imageId === null || state === undefined) return;
    if (gcpCount < AUTO_MEASURE_MIN_GCPS) return;
    if (active !== null) return; // one stage at a time — the server refuses overlap

    const cycle = `${imageId}:${gcpCount}`;

    // ── 1 · measure ──────────────────────────────────────────────────────────
    // A new point invalidates the previous cycle's numbers, so each count earns one
    // measurement — unless the loop has already concluded that more points do not pay.
    // ★ THE SWITCH GATES THE START, NOT THE CHAIN. With it off nothing measures on
    //   its own — not on open, not on a new point, not when a setting clears the
    //   results — but stages 2 and 3 still run, so a measurement the SURVEYOR asked
    //   for gets the correction and the suggestion that make it useful.
    if (autoMeasure && !started.has(cycle)) {
      // ★ Results already in hand for exactly these points are not re-measured. The
      //   guard set is module state, so a page reload emptied it and re-opening a
      //   finished project spent a whole mosaic re-deriving what was on screen.
      if (state.measurement?.pose?.gcps_used === gcpCount) {
        started.add(cycle);
        lastCount.current = gcpCount;
        return;
      }

      // ★ Converged means "more points will not pay", so the loop stops spending a
      //   satellite mosaic per point. It is a verdict, not a veto: if the surveyor
      //   places another anyway they may know something the score does not, and that
      //   point earns its cycle.
      const addedAnyway = lastCount.current >= 0 && gcpCount > lastCount.current;
      if (converged && !addedAnyway) return;
      started.add(cycle);
      lastCount.current = gcpCount;
      measure.mutate({ image_id: imageId });
      return;
    }

    const measurement = state.measurement;
    if (measurement === null) return;

    // ── 2 · correct ──────────────────────────────────────────────────────────
    const measureKey = `${imageId}:${measurement.measured_at}`;
    if (state.solutions === null) {
      if (corrected.has(measureKey)) return;
      corrected.add(measureKey);
      correct.mutate({ image_id: imageId });
      return;
    }

    // ── 3 · where the next point goes ────────────────────────────────────────
    // ★ No adoption step. See the note at the top: installing the corrected pose as the
    //   next measurement's base would move the baseline under every later reading.
    const solutionKey = `${imageId}:${state.solutions.corrected_at}`;
    if (!suggested.has(solutionKey)) {
      suggested.add(solutionKey);
      suggest.mutate({ image_id: imageId, count: suggestionLimit });
    }
    // Mutations are stable objects; listing them would re-run this on their own state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, imageId, gcpCount, state, active, converged, suggestionLimit, autoMeasure]);

  const message = ((): string | null => {
    if (active !== null) {
      const what =
        active.kind === 'measure'
          ? 'measuring the error'
          : active.kind === 'correct'
            ? 'correcting the pose'
            : 'finding where the next point helps most';
      return `${what} — ${active.progress_pct}%`;
    }
    if (!autoMeasure) return null; // the button says it; the status must not
    if (gcpCount < AUTO_MEASURE_MIN_GCPS) {
      return `${AUTO_MEASURE_MIN_GCPS - gcpCount} more point(s) and the error measures itself`;
    }
    return null;
  })();

  return { running: active !== null, converged, message };
}

/** Forget every guard for one photograph — a manual run re-arms the whole cycle. */
export function resetAccuracyAutopilot(imageId: Uuid): void {
  for (const set of [started, corrected, suggested]) {
    for (const key of set) {
      if (key.startsWith(`${imageId}:`)) set.delete(key);
    }
  }
}
