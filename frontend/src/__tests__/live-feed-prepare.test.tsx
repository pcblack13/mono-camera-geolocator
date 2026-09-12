/**
 * A sender-backed feed ensures the server's reader before every attempt
 * (2026-09-10).
 *
 * ★ THE BUG THIS PINS: after a relaunch the API had forgotten the sender's
 *   reader, the monitor page showed "not connected to 10.10.10.1:5000", and the
 *   Reconnect arrow only re-fetched the same refused stream URL. The hook's
 *   `prepare` step now runs before the first open, before each press of the
 *   arrow and before each 10 s self-retry; its rejection is the refusal shown.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRef } from 'react';
import { act, renderHook } from '@testing-library/react';

import { useLiveFeed } from '../hooks/useLiveFeed';

const STREAM = 'http://127.0.0.1/api/v1/live/senders/10.10.10.1%3A5000/stream';

const refusal = (): Promise<Response> =>
  Promise.resolve(
    new Response(JSON.stringify({ error: { message: 'not connected to 10.10.10.1:5000.' } }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    }),
  );

describe('the live feed’s prepare step', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(refusal));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('★ a rejected prepare is the refusal shown, and the stream is not fetched', async () => {
    const canvas = createRef<HTMLCanvasElement>();
    const prepare = vi.fn(() =>
      Promise.reject(new Error('no camera is announcing itself as 10.10.10.1:5000 — check the cable')),
    );
    const { result } = renderHook(() => useLiveFeed(STREAM, canvas, { prepare }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(result.current.status).toBe('refused');
    expect(result.current.streamError).toContain('no camera is announcing itself');
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });

  it('★ runs again on the Reconnect arrow and on the 10 s self-retry', async () => {
    const canvas = createRef<HTMLCanvasElement>();
    const prepare = vi.fn(() => Promise.reject(new Error('still unplugged')));
    const { result } = renderHook(() => useLiveFeed(STREAM, canvas, { prepare }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(prepare).toHaveBeenCalledTimes(1);

    act(() => result.current.reconnect());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(prepare).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_100);
    });
    expect(prepare).toHaveBeenCalledTimes(3);
    expect(result.current.status).toBe('refused');
  });

  it('a resolved prepare lets the stream be fetched as before', async () => {
    const canvas = createRef<HTMLCanvasElement>();
    const prepare = vi.fn(() => Promise.resolve());
    const { result } = renderHook(() => useLiveFeed(STREAM, canvas, { prepare }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    // The server's own refusal still reads through, verbatim.
    expect(result.current.status).toBe('refused');
    expect(result.current.streamError).toBe('not connected to 10.10.10.1:5000.');
  });
});
