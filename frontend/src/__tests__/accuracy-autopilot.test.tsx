/**
 * The accuracy loop runs itself — and must know when to stop.
 *
 * ★ WHY THIS IS WORTH TESTING. Every cycle downloads a satellite mosaic and re-solves a
 *   pose. The guards below are what stand between "the answer is ready before you ask"
 *   and a photograph that re-measures itself in a loop, or a failed attempt (no DEM, no
 *   camera) that retries forever. They are module-level and invisible on screen, so they
 *   are pinned here rather than discovered in a bill.
 *
 * ★ The cycle under test: measure → correct → suggest where the next point goes; then
 *   repeat once per point placed, until it converges.
 *
 * ★ IT IS OPT-IN (2026-08-20). The whole automatic cycle is gated on the workspace's
 *   `autoMeasure` preference, which is OFF by default — opening a project with four
 *   points used to spend a mosaic nobody asked for. These tests turn it ON to exercise
 *   the cycle, and the first two below pin the OFF behaviour, which is what a surveyor
 *   who never touches the switch actually gets.
 *
 * ★ IT MUST NOT ADOPT. Adopting installs the corrected pose as the base the next
 *   measurement starts from, so every later cycle would report a residual on a baseline
 *   that moved — falling numbers that mean less each time. That is pinned below,
 *   because it is invisible until someone compares two cycles and is misled by them.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const measureMutate = vi.fn();
const correctMutate = vi.fn();
const adoptMutate = vi.fn();
const suggestMutate = vi.fn();
let stateData: unknown;

vi.mock('../api/hooks/useAccuracy', () => ({
  useAccuracyState: () => ({ data: stateData }),
  useMeasureAccuracy: () => ({ mutate: measureMutate }),
  useCorrectAccuracy: () => ({ mutate: correctMutate }),
  useAdoptStage: () => ({ mutate: adoptMutate }),
  useSuggestGcps: () => ({ mutate: suggestMutate }),
}));

import {
  AUTO_MEASURE_MIN_GCPS,
  AUTO_SUGGEST_REGIONS,
  resetAccuracyAutopilot,
  useAccuracyAutopilot,
} from '../api/hooks/useAccuracyAutopilot';
import type { Uuid } from '../types/common';
import { useWorkspaceStore } from '../store/workspaceStore';

const IMAGE = 'image-1' as Uuid;

function state(over: Record<string, unknown> = {}): unknown {
  return {
    measurement: null,
    solutions: null,
    suggestions: null,
    adoption: null,
    active_run: null,
    ...over,
  };
}

const MEASURED = { measured_at: 'm1', median_error_m: 4.2 };
const COMPARED = { corrected_at: 'c1', best: 'pose' };

describe('the accuracy loop', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetAccuracyAutopilot(IMAGE);
    stateData = state();
    // The cycle is opt-in; these tests are about what it does once opted in.
    useWorkspaceStore.setState({ autoMeasure: true });
  });

  it('★ measures NOTHING while the switch is off — not even with points to spare', () => {
    // ★ THE DEFAULT, and the bug that earned it: opening a project that already had
    //   four points started a measurement immediately — a satellite mosaic and minutes
    //   of compute for a photograph the surveyor may have opened only to look at.
    useWorkspaceStore.setState({ autoMeasure: false });
    renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 9 }));
    expect(measureMutate).not.toHaveBeenCalled();
    expect(correctMutate).not.toHaveBeenCalled();
    expect(suggestMutate).not.toHaveBeenCalled();
  });

  it('★ still finishes a measurement the SURVEYOR asked for, switch or no switch', () => {
    // Pressing Measure produces a measurement; the correction and the suggestion that
    // make it useful still follow. The switch governs STARTING, not the chain.
    useWorkspaceStore.setState({ autoMeasure: false });
    stateData = state({ measurement: MEASURED });
    renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 6 }));
    expect(measureMutate).not.toHaveBeenCalled();
    expect(correctMutate).toHaveBeenCalledTimes(1);
  });

  it('★ does not re-measure results it already has for these points', () => {
    // The guards are module state, so a page RELOAD emptied them — and re-opening a
    // finished project spent a whole mosaic re-deriving what was already on screen.
    stateData = state({ measurement: { ...MEASURED, pose: { gcps_used: 6 } } });
    renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 6 }));
    expect(measureMutate).not.toHaveBeenCalled();
  });

  it('waits for the fourth point — three is not a pose', () => {
    renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: AUTO_MEASURE_MIN_GCPS - 1 }));
    expect(measureMutate).not.toHaveBeenCalled();
  });

  it('counts down to the fourth point so the surveyor knows it is coming', () => {
    const { result } = renderHook(() =>
      useAccuracyAutopilot(IMAGE, { gcpCount: AUTO_MEASURE_MIN_GCPS - 2 }),
    );
    expect(result.current.message).toContain('2 more point');
  });

  it('measures on its own once four points exist', () => {
    renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: AUTO_MEASURE_MIN_GCPS }));
    expect(measureMutate).toHaveBeenCalledWith({ image_id: IMAGE });
  });

  it('walks the cycle: correct, then ask where the next point goes', () => {
    // measure
    const { rerender } = renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 4 }));
    expect(measureMutate).toHaveBeenCalledTimes(1);

    // …the measurement lands → correct
    stateData = state({ measurement: MEASURED });
    rerender();
    expect(correctMutate).toHaveBeenCalledWith({ image_id: IMAGE });

    // …the comparison lands → ask where the next point goes. ONE region, not a menu.
    stateData = state({ measurement: MEASURED, solutions: COMPARED });
    rerender();
    expect(suggestMutate).toHaveBeenCalledWith({
      image_id: IMAGE,
      count: AUTO_SUGGEST_REGIONS,
    });
  });

  it('never adopts on its own — the baseline must not move under the readings', () => {
    const { rerender } = renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 4 }));
    stateData = state({ measurement: MEASURED });
    rerender();
    stateData = state({ measurement: MEASURED, solutions: COMPARED });
    rerender();
    rerender();
    // ★ Every cycle must keep measuring from the pose the CONTROL POINTS give, so a
    //   falling error across cycles means the points improved the solve — not that the
    //   baseline was replaced with the answer.
    expect(adoptMutate).not.toHaveBeenCalled();
  });

  it('never starts a second stage while one is running', () => {
    stateData = state({ active_run: { kind: 'measure', status: 'running', progress_pct: 40 } });
    renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 6 }));
    expect(measureMutate).not.toHaveBeenCalled();
    expect(correctMutate).not.toHaveBeenCalled();
  });

  it('runs one cycle per point placed — and exactly one', () => {
    const { rerender } = renderHook(
      (props: { n: number }) => useAccuracyAutopilot(IMAGE, { gcpCount: props.n }),
      { initialProps: { n: 4 } },
    );
    rerender({ n: 4 });
    expect(measureMutate).toHaveBeenCalledTimes(1);

    // ★ A fifth point invalidates the previous cycle's numbers and earns a new one.
    stateData = state();
    rerender({ n: 5 });
    expect(measureMutate).toHaveBeenCalledTimes(2);
  });

  it('stops re-measuring once the suggestion says the points are enough', () => {
    stateData = state({
      measurement: MEASURED,
      solutions: COMPARED,
      suggestions: { verdict: 'converged', best_cut_pct: 2, regions: [] },
    });
    const { result } = renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 9 }));
    expect(measureMutate).not.toHaveBeenCalled();
    expect(result.current.converged).toBe(true);
  });

  it('honours a point placed AFTER it said enough — the verdict is not a veto', () => {
    // First a normal cycle at 6, so the loop knows which count it last ran for.
    const { rerender } = renderHook(
      (props: { n: number }) => useAccuracyAutopilot(IMAGE, { gcpCount: props.n }),
      { initialProps: { n: 6 } },
    );
    expect(measureMutate).toHaveBeenCalledTimes(1);

    stateData = state({
      measurement: MEASURED,
      solutions: COMPARED,
      suggestions: { verdict: 'converged', best_cut_pct: 1, regions: [] },
    });
    rerender({ n: 6 });
    expect(measureMutate).toHaveBeenCalledTimes(1); // converged: no new cycle

    // The surveyor places one anyway — they may know something the score does not.
    rerender({ n: 7 });
    expect(measureMutate).toHaveBeenCalledTimes(2);
  });

  it('does nothing at all when disabled', () => {
    renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 6, enabled: false }));
    expect(measureMutate).not.toHaveBeenCalled();
    expect(correctMutate).not.toHaveBeenCalled();
    expect(suggestMutate).not.toHaveBeenCalled();
  });

  it('reports what it is doing while a stage runs', () => {
    stateData = state({
      active_run: { kind: 'correct', status: 'running', progress_pct: 62 },
    });
    const { result } = renderHook(() => useAccuracyAutopilot(IMAGE, { gcpCount: 6 }));
    expect(result.current.running).toBe(true);
    expect(result.current.message).toContain('correcting the pose');
    expect(result.current.message).toContain('62');
  });
});
