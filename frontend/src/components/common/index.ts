/**
 * `common/` barrel — the shared, pure UI primitives (50-frontend §2.26).
 *
 * ★ These are the single source of truth for confidence rendering (`ConfidenceChip`
 *   / `ConfidenceBar` / `UncertaintyBadge`), the app's empty/error/confirm surfaces,
 *   the a11y live region, and the toast channel. Every other component composes
 *   these rather than re-styling confidence inline (§8.6).
 */

export { ConfidenceBar, type ConfidenceBarProps } from './ConfidenceBar';
export { ConfidenceChip, type ConfidenceChipProps } from './ConfidenceChip';
export { ConfirmDialog, type ConfirmDialogProps } from './ConfirmDialog';
export { EmptyState, type EmptyStateAction, type EmptyStateProps } from './EmptyState';
export { ErrorBoundary, type ErrorBoundaryProps } from './ErrorBoundary';
export {
  LiveAnnounceProvider,
  LiveRegion,
  useAnnounce,
  visuallyHiddenSx,
  type Announce,
  type LiveRegionProps,
} from './LiveRegion';
export {
  NotificationsProvider,
  useNotify,
  type NotificationsContextValue,
  type NotifyOptions,
  type NotifySeverity,
} from './Notifications';
export { UncertaintyBadge, type UncertaintyBadgeProps } from './UncertaintyBadge';
