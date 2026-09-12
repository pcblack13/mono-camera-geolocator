/**
 * `hooks/useCameraDrift.ts` — the camera's drift watch, frozen on its frame.
 *
 * ★ THE FRAME WITH THE CONTROL POINTS IS THE FROZEN FRAME (2026-09-08, owner
 *   decision). The camera settings freeze — when the lookup table is built from
 *   the frame, and whenever a new frame is chosen — and the server watches the
 *   reference in the background from then on. The monitoring page only READS the
 *   verdict; it has no freeze of its own any more.
 *
 * ★ `freeze()` never throws: it resolves to the outcome, or to the server's
 *   verbatim refusal, so a caller can chain a notice without try/catch. The
 *   registry row is patched with the new watch so every page reads it at once.
 */

import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { camerasApi, type CameraDriftRead } from '../api/cameras';
import { qk } from '../api/queryKeys';
import { useCameraRegistryStore } from '../store/cameraRegistryStore';
import { ApiError, asUuid } from '../types/common';

export interface CameraDriftFreezeOutcome {
  outcome: CameraDriftRead | null;
  /** The server's verbatim refusal, when `outcome` is null. */
  error: string | null;
}

export interface CameraDriftFreeze {
  /** Freeze on the camera's frame and start the watch. `id` overrides the bound one. */
  freeze: (id?: string | null) => Promise<CameraDriftFreezeOutcome>;
  busy: boolean;
  /** The last successful freeze from here. */
  result: CameraDriftRead | null;
  /** The server's verbatim refusal, or null. */
  error: string | null;
}

export function useCameraDriftFreeze(cameraId: string | null): CameraDriftFreeze {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CameraDriftRead | null>(null);
  const [error, setError] = useState<string | null>(null);

  const freeze = useCallback(
    async (id?: string | null): Promise<CameraDriftFreezeOutcome> => {
      const target = id ?? cameraId;
      if (target === null || target === undefined || target === '')
        return { outcome: null, error: null };
      setBusy(true);
      setError(null);
      try {
        const outcome = await camerasApi.freezeDrift(asUuid(target));
        setResult(outcome);
        // The row's desired watch is what the monitor page reads the verdict by.
        useCameraRegistryStore.setState(
          (s) => ({
            cameras: s.cameras.map((c) =>
              c.id === target
                ? {
                    ...c,
                    desired: {
                      watch: { ref_id: outcome.ref_id, interval_s: outcome.interval_s },
                      detect: c.desired?.detect ?? null,
                      feed: c.desired?.feed ?? false,
                    },
                  }
                : c,
            ),
          }),
          false,
        );
        void queryClient.invalidateQueries({ queryKey: qk.drift.all() });
        return { outcome, error: null };
      } catch (err) {
        const message =
          err instanceof ApiError || err instanceof Error ? err.message : String(err);
        setError(message);
        return { outcome: null, error: message };
      } finally {
        setBusy(false);
      }
    },
    [cameraId, queryClient],
  );

  return { freeze, busy, result, error };
}
