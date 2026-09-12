/**
 * A refused live source heals itself (2026-09-02).
 *
 * ★ THE BUG THIS PINS: an unplugged camera put the feed in "refused" and it
 *   STAYED there after the camera came back — the page had to be left and
 *   re-entered. The hook now retries every 10 s while refused, and the refused
 *   panel carries a Reconnect button (the "lost" panel always had one).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRef } from 'react';
import { act, renderHook } from '@testing-library/react';

import { useLiveFeed } from '../hooks/useLiveFeed';

const refusal = (): Promise<Response> =>
  Promise.resolve(
    new Response(JSON.stringify({ error: { message: 'could not open capture device' } }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    }),
  );

describe('the live feed’s refused state', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(refusal));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('★ retries by itself every 10 s while refused — a replug heals the page', async () => {
    const canvas = createRef<HTMLCanvasElement>();
    const { result } = renderHook(() =>
      useLiveFeed('http://127.0.0.1/api/v1/live/stream?src=%2Fdev%2Fvideo0', canvas),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(result.current.status).toBe('refused');
    const callsAfterFirst = vi.mocked(fetch).mock.calls.length;
    expect(callsAfterFirst).toBeGreaterThan(0);

    // 10 s later the hook tries again, unprompted…
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_100);
    });
    expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(callsAfterFirst);
    // …and keeps trying (the timer re-arms even on an identical failure).
    const callsAfterSecond = vi.mocked(fetch).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_100);
    });
    expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(callsAfterSecond);
  });

  it('stops retrying once the URL is withdrawn (a run took the device on purpose)', async () => {
    const canvas = createRef<HTMLCanvasElement>();
    const { result, rerender } = renderHook(({ url }) => useLiveFeed(url, canvas), {
      initialProps: { url: 'http://127.0.0.1/api/v1/live/stream?src=%2Fdev%2Fvideo0' as string | null },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(result.current.status).toBe('refused');
    rerender({ url: null });
    const calls = vi.mocked(fetch).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(25_000);
    });
    expect(vi.mocked(fetch).mock.calls.length).toBe(calls);
  });
});
