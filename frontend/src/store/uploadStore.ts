/**
 * `uploadStore` — CONTRACT.md §8.5 / 50-frontend.md §3.4.
 *
 * Owns: `items: UploadItem[]` · `concurrency` (3). Not persisted.
 *
 * ★ **This store owns the QUEUE, not the transport.** It holds the file handles, the
 *   ordering, the concurrency budget and the per-item progress. The actual `PUT`/
 *   `POST` is IU-24's (`api/images.ts`, `useImageUpload`), registered here through
 *   {@link UploadState.setUploader}. §2.5 is explicit that `src/api/` is the ONLY
 *   `fetch()` in the app, and an upload is no exception — an `XMLHttpRequest` opened
 *   from a store would be a second, unauthenticated API client with no
 *   `ErrorEnvelope` parsing and no request id.
 *
 * ★ 50-frontend's `UploadItem.xhr?: XMLHttpRequest` is therefore replaced by an
 *   `AbortController`: it is transport-agnostic (works for `fetch` and XHR alike),
 *   it is what IU-24's client already speaks, and it keeps an XHR object — a live
 *   network handle — out of a Zustand store that devtools serialises.
 *
 * ★ L7 — `UploadItem` is client state: a `File`, an object URL, a progress number.
 *   `imageId` is the only server-derived field and it is an id, not a row; the
 *   `ImageRead` arrives through React Query.
 */

import { create } from 'zustand';

import { newId } from '../lib/ids';
import { devtools } from 'zustand/middleware';

import type { ApiError, Uuid } from '../types/common';
import type { LatLon } from '../types/geo';

export type UploadStatus = 'queued' | 'uploading' | 'processing' | 'done' | 'error' | 'cancelled';

export interface UploadItem {
  clientId: string;
  file: File;
  /** ★ An object URL. Revoked on removal — see {@link UploadState.remove}. */
  previewUrl: string;
  status: UploadStatus;
  /** 0..1. */
  progress: number;
  bytesSent: number;
  imageId: Uuid | null;
  error: ApiError | null;
  /** From a client-side EXIF peek, for the map's initial hint. `null` when absent. */
  exifHint: LatLon | null;
  /** Cancels the in-flight request. See the header note on `xhr`. */
  abort: AbortController | null;
}

/**
 * What the store calls to actually move bytes. Supplied by IU-24.
 *
 * Resolves with the new image's id; rejects with an `ApiError`. The store never
 * inspects the response beyond that.
 */
export type Uploader = (
  item: UploadItem,
  onProgress: (bytesSent: number, bytesTotal: number) => void,
  signal: AbortSignal,
) => Promise<Uuid>;

export interface UploadState {
  items: UploadItem[];
  /** ★ Default 3 (§8.5). More saturates a field tablet's uplink and starves the
   *  interactive requests the surveyor is waiting on. */
  concurrency: number;
  uploader: Uploader | null;

  setUploader: (u: Uploader | null) => void;
  enqueue: (files: File[]) => void;
  start: () => void;
  cancel: (clientId: string) => void;
  retry: (clientId: string) => void;
  remove: (clientId: string) => void;
  clearCompleted: () => void;
  setConcurrency: (n: number) => void;
  /** Marked by IU-24 when the server's post-upload job finishes. */
  markProcessed: (clientId: string) => void;
}

const TERMINAL: readonly UploadStatus[] = ['done', 'error', 'cancelled'];

export const useUploadStore = create<UploadState>()(
  devtools(
    (set, get) => {
      const patch = (clientId: string, p: Partial<UploadItem>, action: string): void =>
        set(
          (s) => ({ items: s.items.map((i) => (i.clientId === clientId ? { ...i, ...p } : i)) }),
          false,
          action,
        );

      /** Fill the concurrency budget from the head of the queue. Idempotent. */
      const pump = (): void => {
        const s = get();
        if (!s.uploader) return;

        const inFlight = s.items.filter((i) => i.status === 'uploading').length;
        const free = Math.max(0, s.concurrency - inFlight);
        if (free === 0) return;

        for (const item of s.items.filter((i) => i.status === 'queued').slice(0, free)) {
          void run(item.clientId);
        }
      };

      const run = async (clientId: string): Promise<void> => {
        const uploader = get().uploader;
        const item = get().items.find((i) => i.clientId === clientId);
        if (!uploader || !item || item.status !== 'queued') return;

        const abort = new AbortController();
        patch(
          clientId,
          { status: 'uploading', abort, error: null, progress: 0, bytesSent: 0 },
          'upload/start',
        );

        try {
          const imageId = await uploader(
            item,
            (bytesSent, bytesTotal) =>
              patch(
                clientId,
                { bytesSent, progress: bytesTotal > 0 ? Math.min(1, bytesSent / bytesTotal) : 0 },
                'upload/progress',
              ),
            abort.signal,
          );
          // ★ `processing`, not `done`: the bytes are up but the server's metadata /
          //   thumbnail / EXIF job is still running (§8.4). Saying `done` here would
          //   promise an image the surveyor cannot yet open.
          patch(
            clientId,
            { status: 'processing', progress: 1, imageId, abort: null },
            'upload/uploaded',
          );
        } catch (e) {
          // ★ An abort is a CANCELLATION, not a failure. Rendering the user's own
          //   cancel as a red error is both wrong and alarming.
          if (abort.signal.aborted) {
            patch(clientId, { status: 'cancelled', abort: null }, 'upload/cancelled');
          } else {
            patch(clientId, { status: 'error', error: e as ApiError, abort: null }, 'upload/error');
          }
        } finally {
          pump();
        }
      };

      return {
        items: [],
        concurrency: 3,
        uploader: null,

        setUploader: (u) => {
          set({ uploader: u }, false, 'upload/setUploader');
          pump();
        },

        enqueue: (files) =>
          set(
            (s) => ({
              items: [
                ...s.items,
                ...files.map<UploadItem>((file) => ({
                  clientId: newId(),
                  file,
                  previewUrl: URL.createObjectURL(file),
                  status: 'queued',
                  progress: 0,
                  bytesSent: 0,
                  imageId: null,
                  error: null,
                  exifHint: null,
                  abort: null,
                })),
              ],
            }),
            false,
            'upload/enqueue',
          ),

        start: () => pump(),

        cancel: (clientId) => {
          const item = get().items.find((i) => i.clientId === clientId);
          if (!item) return;
          item.abort?.abort();
          // A queued item has no request to abort; mark it directly.
          if (item.status === 'queued') patch(clientId, { status: 'cancelled' }, 'upload/cancel');
          pump();
        },

        retry: (clientId) => {
          patch(
            clientId,
            { status: 'queued', error: null, progress: 0, bytesSent: 0 },
            'upload/retry',
          );
          pump();
        },

        remove: (clientId) => {
          const item = get().items.find((i) => i.clientId === clientId);
          if (!item) return;
          item.abort?.abort();
          // ★ Revoke the object URL. A leaked one pins the whole File in memory for
          //   the document's lifetime, and a batch of 40 field photos is ~800 MB.
          URL.revokeObjectURL(item.previewUrl);
          set(
            (s) => ({ items: s.items.filter((i) => i.clientId !== clientId) }),
            false,
            'upload/remove',
          );
          pump();
        },

        clearCompleted: () => {
          const { items } = get();
          for (const i of items) {
            if (TERMINAL.includes(i.status)) URL.revokeObjectURL(i.previewUrl);
          }
          set(
            { items: items.filter((i) => !TERMINAL.includes(i.status)) },
            false,
            'upload/clearCompleted',
          );
        },

        setConcurrency: (n) => {
          set({ concurrency: Math.max(1, Math.min(8, n)) }, false, 'upload/setConcurrency');
          pump();
        },

        markProcessed: (clientId) =>
          patch(clientId, { status: 'done', progress: 1 }, 'upload/markProcessed'),
      };
    },
    { name: 'uploadStore' },
  ),
);
