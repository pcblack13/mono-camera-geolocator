/**
 * Live predict on the monitoring page (2026-09-10): the cursor asks the lookup
 * table, throttled; the newest answer wins; a click pins; Copy writes
 * "lat, lon, elevation".
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { formatPrediction, PREDICT_THROTTLE_MS, useLivePredict } from '../hooks/useLivePredict';
import { lutApi } from '../api/lut';

vi.mock('../api/lut', () => ({ lutApi: { lookup: vi.fn() } }));

const answer = (lat: number, lon: number, z: number | null = 1312.4) => ({
  site_name: 'roof',
  u: 0,
  v: 0,
  lut_u: 0,
  lut_v: 0,
  placed: true,
  lat,
  lon,
  elevation_m: z,
  elevation_source: z === null ? null : 'project_dem',
  reason: null,
});

describe('useLivePredict', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(lutApi.lookup).mockReset();
    vi.mocked(lutApi.lookup).mockResolvedValue(answer(34.1, 36.0));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('★ asks the TABLE for the pixel, with the media size and the project, throttled', async () => {
    const { result } = renderHook(() =>
      useLivePredict({ enabled: true, lutSite: 'roof', projectId: 'p1' }),
    );
    act(() => result.current.cursor({ u: 10, v: 20, w: 1280, h: 720 }));
    act(() => result.current.cursor({ u: 11, v: 21, w: 1280, h: 720 }));
    expect(lutApi.lookup).toHaveBeenCalledTimes(1);
    expect(lutApi.lookup).toHaveBeenCalledWith('roof', { u: 10, v: 20, w: 1280, h: 720, projectId: 'p1' });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PREDICT_THROTTLE_MS + 5);
    });
    // the throttled second move fires once the gap has passed — with the LATEST pixel
    expect(lutApi.lookup).toHaveBeenCalledTimes(2);
    expect(vi.mocked(lutApi.lookup).mock.calls[1][1]).toMatchObject({ u: 11, v: 21 });
    expect(result.current.prediction).toMatchObject({ lat: 34.1, lon: 36.0, elevationM: 1312.4 });
    expect(result.current.copyText).toBe('34.100000, 36.000000, 1312.4');
  });

  it('leaving the picture drops the reading and a late answer for it', async () => {
    let resolve: (v: ReturnType<typeof answer>) => void = () => undefined;
    vi.mocked(lutApi.lookup).mockImplementation(
      () => new Promise((r) => { resolve = r; }),
    );
    const { result } = renderHook(() =>
      useLivePredict({ enabled: true, lutSite: 'roof', projectId: null }),
    );
    act(() => result.current.cursor({ u: 1, v: 1, w: 10, h: 10 }));
    act(() => result.current.leave());
    await act(async () => {
      resolve(answer(1, 2));
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(result.current.prediction).toBeNull();
    expect(result.current.pending).toBe(false);
  });

  it('★ a click pins the reading — the cursor no longer moves it — and Copy writes lat, lon, z', async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const { result } = renderHook(() =>
      useLivePredict({ enabled: true, lutSite: 'roof', projectId: 'p1' }),
    );
    act(() => result.current.pin({ u: 5, v: 6, w: 10, h: 10 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(result.current.pinned).toBe(true);
    const calls = vi.mocked(lutApi.lookup).mock.calls.length;
    act(() => result.current.cursor({ u: 7, v: 8, w: 10, h: 10 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PREDICT_THROTTLE_MS * 2);
    });
    expect(vi.mocked(lutApi.lookup).mock.calls.length).toBe(calls);
    let copied: string | null = null;
    await act(async () => {
      copied = await result.current.copy();
    });
    expect(copied).toBe('34.100000, 36.000000, 1312.4');
    expect(writeText).toHaveBeenCalledWith('34.100000, 36.000000, 1312.4');
    act(() => result.current.unpin());
    expect(result.current.pinned).toBe(false);
    vi.unstubAllGlobals();
  });

  it('switching the tool off clears everything; no elevation means no third number', () => {
    expect(formatPrediction({ u: 0, v: 0, placed: true, lat: 1, lon: 2, elevationM: null, reason: null })).toBe(
      '1.000000, 2.000000',
    );
    expect(formatPrediction({ u: 0, v: 0, placed: false, lat: null, lon: null, elevationM: null, reason: 'no_terrain' })).toBeNull();
    const { result, rerender } = renderHook(
      ({ enabled }) => useLivePredict({ enabled, lutSite: 'roof', projectId: null }),
      { initialProps: { enabled: true } },
    );
    act(() => result.current.pin({ u: 1, v: 1, w: 10, h: 10 }));
    rerender({ enabled: false });
    expect(result.current.pinned).toBe(false);
    expect(result.current.prediction).toBeNull();
    act(() => result.current.cursor({ u: 1, v: 1, w: 10, h: 10 }));
    expect(lutApi.lookup).toHaveBeenCalledTimes(1); // only the pin, before it was switched off
  });
});
