/**
 * `useLiveFeed` — the live state machine, exercised directly.
 *
 * ★ The four truths, told apart: a rejected read falls back to `img` (CORS), a
 *   server REFUSAL surfaces the envelope's `error.message` verbatim and is not a
 *   disconnect, frames that stop trip the 6 s watchdog into `lost`, and no URL is
 *   `idle`. jsdom cannot decode JPEGs or draw on a canvas, so `createImageBitmap`
 *   is stubbed and the canvas draw is a no-op — what is under test is the machine,
 *   not the pixels.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { createRef } from 'react';

const fetchStream = vi.hoisted(() => vi.fn());
vi.mock('../api/client', async (importOriginal) => {
  const mod = (await importOriginal()) as Record<string, unknown>;
  return { ...mod, fetchStream };
});

import {
  STALL_MS,
  canPreviewInBrowser,
  previewSrcForSource,
  useLiveFeed,
} from '../hooks/useLiveFeed';

function canvasRef(): React.RefObject<HTMLCanvasElement> {
  const ref = createRef<HTMLCanvasElement>();
  const canvas = document.createElement('canvas');
  // jsdom has no 2D context; the hook only draws, so a null context is fine.
  canvas.getContext = (() => null) as unknown as typeof canvas.getContext;
  (ref as { current: HTMLCanvasElement | null }).current = canvas;
  return ref;
}

/** A body whose reader yields `chunks`, then either ends or hangs. */
function bodyOf(chunks: Uint8Array[], thenHang = false): { getReader: () => unknown } {
  let i = 0;
  return {
    getReader: () => ({
      read: (): Promise<{ done: boolean; value?: Uint8Array }> => {
        if (i < chunks.length) return Promise.resolve({ done: false, value: chunks[i++] });
        return thenHang ? new Promise(() => undefined) : Promise.resolve({ done: true });
      },
    }),
  };
}

function response(contentType: string, chunks: Uint8Array[], thenHang = false): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': contentType }),
    body: bodyOf(chunks, thenHang),
  } as unknown as Response;
}

const MJPEG = 'multipart/x-mixed-replace; boundary=x';
const JPEG = new Uint8Array([0xff, 0xd8, 0x00, 0x01, 0xff, 0xd9]);

beforeEach(() => {
  fetchStream.mockReset();
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn().mockResolvedValue({ width: 640, height: 480, close: () => undefined }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('source rules', () => {
  it('previews http(s) directly and everything else through the re-stream', () => {
    expect(canPreviewInBrowser('http://pi:8080/stream')).toBe(true);
    expect(canPreviewInBrowser('rtsp://cam/s1')).toBe(false);
    expect(previewSrcForSource('http://pi:8080/stream')).toBe('http://pi:8080/stream');
    expect(previewSrcForSource('/dev/video0')).toContain('/live/stream?src=');
  });
});

describe('useLiveFeed', () => {
  it('is idle with no url', () => {
    const ref = canvasRef();
    const { result } = renderHook(() => useLiveFeed(null, ref));
    expect(result.current.status).toBe('idle');
    expect(fetchStream).not.toHaveBeenCalled();
  });

  it('★ a rejected read (CORS) falls back to img mode — live, not lost', async () => {
    fetchStream.mockRejectedValue(new Error('no CORS'));
    const ref = canvasRef();
    const { result } = renderHook(() => useLiveFeed('http://cam/s', ref));
    await waitFor(() => expect(result.current.mode).toBe('img'));
    expect(result.current.status).toBe('live');
    expect(result.current.streamError).toBeNull();
  });

  it('★ a server refusal carries error.error.message verbatim, and is REFUSED, not lost', async () => {
    fetchStream.mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        error: { code: 'X', message: 'the device only offers uncompressed YUYV' },
      }),
      headers: new Headers(),
    } as unknown as Response);
    const ref = canvasRef();
    const { result } = renderHook(() => useLiveFeed('/api/v1/live/stream?src=/dev/video9', ref));
    await waitFor(() =>
      expect(result.current.streamError).toBe('the device only offers uncompressed YUYV'),
    );
    expect(result.current.status).toBe('refused');
  });

  it('★ frames that flowed and then stopped trip the 6 s watchdog into LOST', async () => {
    // ★ The whole clock is fake — including `performance`, which the watchdog reads.
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'],
    });
    // One frame, then a read that never returns — a yanked cable.
    fetchStream.mockResolvedValue(response(MJPEG, [JPEG], true));
    const ref = canvasRef();
    const { result } = renderHook(() => useLiveFeed('http://cam/s', ref));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(result.current.mode).toBe('canvas');
    expect(result.current.status).toBe('live');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(STALL_MS + 1000);
    });
    expect(result.current.status).toBe('lost');
  });

  it('a continuous stream that ENDS after frames is a disconnect; a snapshot that ends is not', async () => {
    fetchStream.mockResolvedValueOnce(response(MJPEG, [JPEG]));
    const refA = canvasRef();
    const a = renderHook(() => useLiveFeed('http://cam/a', refA));
    await waitFor(() => expect(a.result.current.status).toBe('lost'));

    fetchStream.mockResolvedValueOnce(response('image/jpeg', [JPEG]));
    const refB = canvasRef();
    const b = renderHook(() => useLiveFeed('http://cam/b', refB));
    await waitFor(() => expect(b.result.current.mode).toBe('canvas'));
    expect(b.result.current.status).toBe('live');
  });
});
