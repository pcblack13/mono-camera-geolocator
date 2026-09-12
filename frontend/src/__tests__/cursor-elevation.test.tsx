/**
 * The cursor elevation readout — the four states, and the stale-response guard.
 *
 * ★ **The out-of-order test is the one that matters.** Two samples can be in flight at
 *   once and the network does not promise to return them in order. A readout that showed
 *   a late answer would attach a real elevation to the wrong place — a plausible wrong
 *   number, which is the failure mode this whole codebase is shaped to avoid. It cannot
 *   be caught by inspection, so it is pinned here.
 *
 * ★ The `no_dem` / `no_data` split is tested because collapsing them is the easy mistake:
 *   both are "null elevation", but one is a setup step the surveyor can take and the
 *   other is the terrain. A UI that showed the same thing for both would send someone
 *   hunting a coverage problem they do not have.
 */

import { act, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CursorElevationReadout } from '../components/map/CursorElevationReadout';
import { useCursorElevation } from '../components/map/useCursorElevation';
import type { CursorElevation } from '../types/elevation';
import { asUuid } from '../types/common';

const sample = vi.hoisted(() => vi.fn());
vi.mock('../api/elevation', () => ({ elevationApi: { sample } }));

const PROJECT = asUuid('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee');
const HERE = { lat: 34.0, lon: 36.0 };

function reply(elevation_m: number | null, source: string | null, dem_attached = true) {
  return {
    results: [{ elevation_m, source, vertical_ce90_m: elevation_m === null ? null : 3.2 }],
    dem_attached,
    with_elevation_count: elevation_m === null ? 0 : 1,
  };
}

// ── the readout, as a pure component ─────────────────────────────────────────

describe('CursorElevationReadout', () => {
  it('renders nothing when idle — no chip, not an empty one', () => {
    const { container } = render(<CursorElevationReadout elevation={{ kind: 'idle' }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [{ kind: 'no_dem' } as CursorElevation, 'no DEM'],
    [{ kind: 'no_data' } as CursorElevation, 'no data'],
  ])('distinguishes %o from the other null case', (elevation, expected) => {
    render(<CursorElevationReadout elevation={elevation} />);
    expect(screen.getByText(new RegExp(expected))).toBeInTheDocument();
  });

  it('always shows the vertical error bar beside the height', () => {
    render(
      <CursorElevationReadout
        elevation={{
          kind: 'value',
          elevation_m: 412.53,
          source: 'copernicus_dem',
          vertical_ce90_m: 3.2,
        }}
      />,
    );
    expect(screen.getByText('Z 412.5 m ± 3.2 m')).toBeInTheDocument();
  });

  it('says "± unknown" rather than omitting an absent CE90', () => {
    // ★ A height with no ± reads as exact. "Unknown" is a statement; a missing term is not.
    render(
      <CursorElevationReadout
        elevation={{
          kind: 'value',
          elevation_m: 100,
          source: 'manual',
          vertical_ce90_m: null,
        }}
      />,
    );
    expect(screen.getByText('Z 100.0 m ± unknown')).toBeInTheDocument();
  });
});

// ── the hook ─────────────────────────────────────────────────────────────────

describe('useCursorElevation', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    sample.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not sample until the pointer settles', async () => {
    const { result } = renderHook(() => useCursorElevation(PROJECT));
    sample.mockResolvedValue(reply(412.5, 'copernicus_dem'));

    act(() => result.current.onCursorMove(HERE));
    expect(sample).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(sample).toHaveBeenCalledTimes(1);
  });

  it('collapses a burst of movement into ONE request', async () => {
    // ★ mousemove fires tens of times a second; one raster read per pixel of travel
    //   would saturate the API for a figure nobody can read mid-motion.
    const { result } = renderHook(() => useCursorElevation(PROJECT));
    sample.mockResolvedValue(reply(412.5, 'copernicus_dem'));

    act(() => {
      for (let i = 0; i < 40; i += 1) {
        result.current.onCursorMove({ lat: 34 + i * 0.001, lon: 36 });
        vi.advanceTimersByTime(10);
      }
    });
    expect(sample).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(sample).toHaveBeenCalledTimes(1);
  });

  it('★ discards a stale response that lands after a newer one', async () => {
    const { result } = renderHook(() => useCursorElevation(PROJECT));

    let resolveFirst: (v: unknown) => void = () => {};
    sample
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce(reply(900, 'copernicus_dem'));

    // First hover fires and stays in flight.
    act(() => result.current.onCursorMove(HERE));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    // Pointer moves; the second sample resolves immediately.
    act(() => result.current.onCursorMove({ lat: 35, lon: 37 }));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current.elevation).toEqual({
      kind: 'value',
      elevation_m: 900,
      source: 'copernicus_dem',
      vertical_ce90_m: 3.2,
    });

    // The FIRST request now returns — late, and about a place the cursor has left.
    await act(async () => {
      resolveFirst(reply(100, 'copernicus_dem'));
    });

    expect(result.current.elevation).toEqual({
      kind: 'value',
      elevation_m: 900,
      source: 'copernicus_dem',
      vertical_ce90_m: 3.2,
    });
  });

  it('reports no_dem when the project has no elevation source', async () => {
    const { result } = renderHook(() => useCursorElevation(PROJECT));
    sample.mockResolvedValue(reply(null, null, false));

    act(() => result.current.onCursorMove(HERE));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current.elevation).toEqual({ kind: 'no_dem' });
  });

  it('reports no_data when a DEM is attached but answers null here', async () => {
    const { result } = renderHook(() => useCursorElevation(PROJECT));
    sample.mockResolvedValue(reply(null, null, true));

    act(() => result.current.onCursorMove(HERE));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current.elevation).toEqual({ kind: 'no_data' });
  });

  it('goes idle and samples nothing when the pointer leaves the map', () => {
    const { result } = renderHook(() => useCursorElevation(PROJECT));
    act(() => result.current.onCursorMove(null));
    act(() => vi.advanceTimersByTime(300));

    expect(sample).not.toHaveBeenCalled();
    expect(result.current.elevation).toEqual({ kind: 'idle' });
  });

  it('never samples without a project', () => {
    const { result } = renderHook(() => useCursorElevation(null));
    act(() => result.current.onCursorMove(HERE));
    act(() => vi.advanceTimersByTime(300));

    expect(sample).not.toHaveBeenCalled();
    expect(result.current.elevation).toEqual({ kind: 'idle' });
  });

  it('falls back to no_data rather than a number when the sample fails', async () => {
    const { result } = renderHook(() => useCursorElevation(PROJECT));
    sample.mockRejectedValue(new Error('network'));

    act(() => result.current.onCursorMove(HERE));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current.elevation).toEqual({ kind: 'no_data' });
  });
});
