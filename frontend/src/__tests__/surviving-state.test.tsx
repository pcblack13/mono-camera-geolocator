/**
 * Work that survives the language remount.
 *
 * ★ Switching the language remounts the whole tree (`main.tsx`). Before this, a
 *   detection run being watched was STOPPED by the unmount and its marks thrown
 *   away — the surveyor's work, gone for a change of words (2026-08-28). Two things
 *   fix it, and both are pinned here: a keyed state slot that outlives its component,
 *   and a stop that waits a grace period a remount beats.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';

import {
  __resetSurvivingState,
  peekSurvivingState,
  useSurvivingState,
} from '../lib/survivingState';

const api = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  get: vi.fn(),
  marks: vi.fn(),
  pause: vi.fn(),
}));
vi.mock('../api/detection', async (importOriginal) => {
  const mod = (await importOriginal()) as Record<string, unknown>;
  return { ...mod, detectionApi: api };
});

import { useLiveDetection } from '../api/hooks/useDetection';

function Counter({ slot }: { slot: string }): JSX.Element {
  const [n, setN] = useSurvivingState(slot, 0);
  return (
    <button type="button" onClick={() => setN((v) => v + 1)}>
      count {n}
    </button>
  );
}

beforeEach(() => {
  __resetSurvivingState();
  api.stop.mockReset().mockResolvedValue(undefined);
  api.start.mockReset().mockResolvedValue({
    session_id: 'abc',
    status: 'running',
    marks_total: 0,
    started_at: '2026-08-28T10:00:00Z',
  });
  api.get.mockReset().mockResolvedValue({ session_id: 'abc', status: 'running', marks_total: 0 });
});
afterEach(() => vi.useRealTimers());

describe('useSurvivingState', () => {
  it('★ a remount finds the value where it was left', () => {
    const first = render(<Counter slot="t.count" />);
    act(() => first.getByRole('button').click());
    act(() => first.getByRole('button').click());
    expect(first.getByRole('button').textContent).toBe('count 2');
    first.unmount();

    const again = render(<Counter slot="t.count" />);
    expect(again.getByRole('button').textContent).toBe('count 2');
  });

  it('keeps slots apart by key, and a reset forgets them', () => {
    const a = render(<Counter slot="t.a" />);
    act(() => a.getByRole('button').click());
    expect(peekSurvivingState('t.a', 0)).toBe(1);
    expect(peekSurvivingState('t.b', 0)).toBe(0);
    __resetSurvivingState();
    expect(peekSurvivingState('t.a', 0)).toBe(0);
  });
});

describe('useLiveDetection across a remount', () => {
  function wrapper({ children }: { children: ReactNode }): JSX.Element {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }

  it('★ a remount inside the grace reclaims the run instead of stopping it', async () => {
    vi.useFakeTimers();
    const first = renderHook(() => useLiveDetection('video'), { wrapper });
    await act(async () => {
      first.result.current.start({ source: 'video:clip1' });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(first.result.current.session?.session_id).toBe('abc');

    first.unmount(); // the language switch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    const again = renderHook(() => useLiveDetection('video'), { wrapper });
    // the run is still there, and the stop never fires
    expect(again.result.current.session?.session_id).toBe('abc');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(api.stop).not.toHaveBeenCalled();
    again.unmount();
  });

  it('navigating away for real still stops the run, after the grace', async () => {
    vi.useFakeTimers();
    const hook = renderHook(() => useLiveDetection('live'), { wrapper });
    await act(async () => {
      hook.result.current.start({ source: 'device:0' });
      await vi.advanceTimersByTimeAsync(0);
    });
    hook.unmount();
    expect(api.stop).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(api.stop).toHaveBeenCalledWith('abc');
  });
});
