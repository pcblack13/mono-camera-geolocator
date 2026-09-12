/**
 * `components/ui` — the instrument primitives (Phase 2 of the redesign).
 *
 * Five components MUI does not provide, each carrying one of the system's rules:
 * StatReadout (numbers never reflow, nothing shown as zero), StatusPill
 * (lifecycle in shape, accuracy in colour), ErrorState (the server's verbatim
 * words + code + copy), EmptyState (one primary action at most), ProgressStage
 * (stages, not a lying percentage). Buttons, inputs, menus and dialogs stay
 * MUI — retuned through `theme/components.ts`, not wrapped.
 */

export { StatReadout } from './StatReadout';
export { StatusPill, type Lifecycle } from './StatusPill';
export { ErrorState } from './ErrorState';
// ★ Phase 5 correction: `common/EmptyState` predates this barrel and already
//   serves seven pages — Phase 2 duplicated it here by mistake, and two empty
//   states is exactly the drift this system forbids. The barrel now re-exports
//   the established one; the duplicate is deleted.
export { EmptyState } from '../common/EmptyState';
export { ProgressStage, type Stage } from './ProgressStage';
