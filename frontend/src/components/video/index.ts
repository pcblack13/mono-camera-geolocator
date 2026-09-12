/**
 * `components/video/` barrel — the VIDEO frame-capture surface.
 *
 * A video is a FRAME SOURCE: scrub to a second, capture that frame, and it becomes a
 * normal image the existing GCP tools annotate. Not a video-timeline annotator.
 */

export { VideoPlayer, type VideoPlayerProps } from './VideoPlayer';
export { VideoUploadDialog, type VideoUploadDialogProps } from './VideoUploadDialog';
