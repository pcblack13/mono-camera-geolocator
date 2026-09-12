/**
 * `hooks/useCameraLutBuild.ts` — build a camera's lookup table, and hand it to the camera.
 *
 * ★ THE LUT BUNDLE JUMPS WITH THE OPERATOR (2026-09-04, owner ask). The camera
 *   settings pipeline sends the operator into the GCP editor to place control
 *   points; from there (or back on the settings page) one press builds the table
 *   for the camera's frame, and the moment the build succeeds the bundle's site
 *   name is written onto the camera row on the server (`lut_site`). Returning to
 *   the settings page then finds the table already listed as the camera's own,
 *   and the monitoring page opens it with its marks placed.
 *
 * ★ Polls the ACTIVE build only while it runs; the terminal state stops the timer
 *   (the LUT generator's own rule). The registry write happens once per build.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { lutApi, type LutBuildStatus } from '../api/lut';
import { qk } from '../api/queryKeys';
import { useCameraRegistryStore } from '../store/cameraRegistryStore';
import { ApiError, type Uuid } from '../types/common';

export interface CameraLutBuildOptions {
  cameraId: string | null;
  imageId: string | null;
  /** The bundle's site name — the camera's name; the server sanitises it. */
  siteName: string;
  onBuilt?: (siteName: string) => void;
}

export interface CameraLutBuild {
  /** Ask the server to build; refused with `error` when a prerequisite is missing. */
  start: () => void;
  /** A build was requested and has not reached a terminal state. */
  building: boolean;
  status: LutBuildStatus | null;
  /** The server's verbatim refusal (it names the exact missing prerequisite). */
  error: string | null;
  /** The site name the last successful build here produced. */
  builtSite: string | null;
}

export function useCameraLutBuild({
  cameraId,
  imageId,
  siteName,
  onBuilt,
}: CameraLutBuildOptions): CameraLutBuild {
  const queryClient = useQueryClient();
  const [activeBuildId, setActiveBuildId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [builtSite, setBuiltSite] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () =>
      lutApi.create({
        image_id: imageId as Uuid,
        site_name: siteName.trim() === '' ? undefined : siteName.trim(),
        coord_dtype: 'float64',
      }),
    onSuccess: (build) => {
      setError(null);
      setActiveBuildId(build.build_id);
      void queryClient.invalidateQueries({ queryKey: qk.lut.all() });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : String(err));
    },
  });

  const buildQuery = useQuery({
    queryKey: qk.lut.build(activeBuildId ?? 'none'),
    queryFn: ({ signal }) => lutApi.get(activeBuildId!, signal),
    enabled: activeBuildId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'queued' || s === 'running' ? 1200 : false;
    },
  });

  // ★ Once per build: the bundle exists on disk → it becomes the camera's own.
  const handled = useRef<string | null>(null);
  const status = buildQuery.data ?? null;
  const onBuiltRef = useRef(onBuilt);
  onBuiltRef.current = onBuilt;
  useEffect(() => {
    if (status === null || status.status !== 'succeeded') return;
    if (handled.current === status.build_id) return;
    handled.current = status.build_id;
    setBuiltSite(status.site_name);
    void queryClient.invalidateQueries({ queryKey: qk.lut.library() });
    if (cameraId !== null) {
      // ★ `onBuilt` fires AFTER the row carries the table (2026-09-08): the
      //   settings page freezes the drift reference from it, and the server
      //   refuses a freeze on a camera whose lookup table it has not seen yet.
      useCameraRegistryStore
        .getState()
        .update(cameraId, { lut_site: status.site_name })
        .then(() => onBuiltRef.current?.(status.site_name))
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : String(err));
        });
      return;
    }
    onBuiltRef.current?.(status.site_name);
  }, [status, cameraId, queryClient]);

  useEffect(() => {
    if (status?.status === 'failed') setError(status.error ?? 'The build failed.');
  }, [status]);

  const building =
    create.isPending ||
    (activeBuildId !== null &&
      (status === null || status.status === 'queued' || status.status === 'running'));

  return {
    start: () => {
      if (imageId === null || building) return;
      setError(null);
      create.mutate();
    },
    building,
    status,
    error,
    builtSite,
  };
}
