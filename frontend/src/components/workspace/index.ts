/**
 * `workspace/` barrel — the mandated 3-pane + dock shell (50-frontend §1 / §2.4–2.7).
 */

// ★ COMPARE REMOVED (1.2.6). Its Linked and Swipe modes were produced by automatic
//   matching, which this build defers, leaving one working option that was simply the
//   normal side-by-side layout. `CompareView.tsx` and `compareStore.ts` went with it.
export { PaneHeader, type PaneHeaderProps } from './PaneHeader';
export { Splitter, type SplitterProps } from './Splitter';
export { Workspace, type WorkspaceProps } from './Workspace';
export { WorkspaceGrid, type WorkspaceGridProps } from './WorkspaceGrid';
export { WorkspaceTabs, type WorkspaceTabsProps } from './WorkspaceTabs';
