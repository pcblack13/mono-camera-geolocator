/**
 * Videos — the frame-source hooks. Mirrors `useImages.ts`.
 *
 * ★ Server state ⇒ React Query (L7). A `Video` is server state; nothing about it lives
 *   in Zustand. The `<video>` element's transient `currentTime` is browser-only and
 *   stays local to `VideoPlayer` — it never becomes a query or a store.
 *
 * ★ DEGRADE GRACEFULLY: these endpoints may 404/501 until the backend lands. The
 *   queries surface that as `isError` (the pages render an honest empty/again state,
 *   never an infinite spinner); the mutations reject and the callers `notify`.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type { ImageRead } from '../../types/image';
import type { FrameCaptureRequest, Video, VideoCreate, VideoSummary } from '../../types/video';
import { videosApi } from '../videos';
import { qk } from '../queryKeys';

export function useVideos(projectId: Uuid | null): UseQueryResult<Page<VideoSummary>> {
  return useQuery({
    queryKey: qk.videos.list(projectId!),
    queryFn: ({ signal }) => videosApi.list(projectId!, signal),
    enabled: projectId !== null,
    // ★ The backend is built concurrently — a missing endpoint is a transient absence,
    //   not a bug to hammer. One retry, then show the honest empty state.
    retry: 1,
  });
}

/** Every video across every project — the Workspace's Video editor tab. */
export function useAllVideos(): UseQueryResult<Page<VideoSummary>> {
  return useQuery({
    queryKey: qk.videos.listAll(),
    queryFn: ({ signal }) => videosApi.listAll(signal),
    retry: 1,
  });
}

export function useVideo(videoId: Uuid | null): UseQueryResult<Video> {
  return useQuery({
    queryKey: qk.videos.detail(videoId!),
    queryFn: ({ signal }) => videosApi.get(videoId!, signal),
    enabled: videoId !== null,
    retry: 1,
    // ★ An HEVC upload grows a browser-playable H.264 preview in the background
    //   (`app.tasks.transcoding`). Poll until it exists so the player switches from
    //   the server-frame scrubber to real playback WITHOUT a manual refresh — then
    //   stop: a ready video never needs the interval again.
    refetchInterval: (query) => {
      const v = query.state.data;
      if (!v || v.preview_available) return false;
      return /hevc|h265|hvc1|hev1/i.test(v.codec ?? '') ? 5000 : false;
    },
  });
}

export interface UploadVideoVariables {
  form: VideoCreate;
  onProgress?: (bytesSent: number, bytesTotal: number) => void;
  signal?: AbortSignal;
}

export function useUploadVideo(): UseMutationResult<Video, unknown, UploadVideoVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ form, onProgress, signal }: UploadVideoVariables) =>
      videosApi.upload(form, { onProgress, signal }),
    onSuccess: (video) => {
      queryClient.setQueryData(qk.videos.detail(video.id), video);
      void queryClient.invalidateQueries({ queryKey: qk.videos.lists() });
    },
  });
}

export interface CaptureFrameVariables {
  videoId: Uuid;
  /** The project the photograph lands in — the clip's own, or the one chosen at capture. */
  projectId: Uuid | null;
  body: FrameCaptureRequest;
}

/**
 * Capture a frame → a new IMAGE appears in the project. So this invalidates the
 * project's images list (and the project counts) and seeds the new image's cache so
 * the workspace it navigates into renders without a refetch.
 */
export function useCaptureFrame(): UseMutationResult<ImageRead, unknown, CaptureFrameVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ videoId, body }: CaptureFrameVariables) => videosApi.captureFrame(videoId, body),
    onSuccess: (image, { projectId }) => {
      queryClient.setQueryData(qk.images.detail(image.id), image);
      void queryClient.invalidateQueries({ queryKey: qk.images.lists() });
      if (projectId !== null)
        void queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) });
    },
  });
}

export interface DeleteVideoVariables {
  videoId: Uuid;
  projectId: Uuid;
}

export function useDeleteVideo(): UseMutationResult<void, unknown, DeleteVideoVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ videoId }: DeleteVideoVariables) => videosApi.remove(videoId),
    onSuccess: (_void, { videoId }) => {
      queryClient.removeQueries({ queryKey: qk.videos.detail(videoId) });
      void queryClient.invalidateQueries({ queryKey: qk.videos.lists() });
    },
  });
}
