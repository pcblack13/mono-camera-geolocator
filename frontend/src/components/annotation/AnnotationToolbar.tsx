/**
 * `annotation/AnnotationToolbar.tsx` — the ToolRail. 50-frontend.md §1.3 / §2.11 /
 * SCOPE.md §3 (cursor · point · polygon · polyline · undo · redo · delete).
 *
 * ★ Every tool works and every button carries its shortcut in the tooltip. Undo/redo
 *   tooltips name the SPECIFIC action from the command's `label` (§4.1), so the user
 *   knows what they are about to reverse before they do.
 *
 * ★ Undo/redo are wired to `lib/commands`' stack via `annotationStore` by the
 *   container that renders this (the labels/enablement are passed in). The `undo`
 *   stack is annotations-only — a GCP adjustment is not undoable here, by design
 *   (`useAdjustGcp`).
 *
 * ★ `orientation` is what lets the one component serve the desktop vertical rail and
 *   the mobile horizontal chip row (§1.5).
 */

import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import UndoIcon from '@mui/icons-material/Undo';
import RedoIcon from '@mui/icons-material/Redo';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { t } from '../../i18n';

export interface AnnotationToolbarProps {
  orientation: 'vertical' | 'horizontal';
  canUndo: boolean;
  canRedo: boolean;
  /** e.g. "Undo Add point P4" — from the command's `label`. */
  undoLabel: string | null;
  redoLabel: string | null;
  onUndo: () => void;
  onRedo: () => void;
  canDelete: boolean;
  onDelete: () => void;
  /**
   * ★ What the delete button DOES, in words (1.2.6). It is no longer always "delete
   *   the selected annotation": while a GCP pairing is open with no landmark
   *   selected it clears the marks instead, and a button whose tooltip lies about
   *   its own action is worse than no tooltip.
   */
  deleteLabel?: string;
  disabled?: boolean;
}

/**
 * ★ NO TOOL PICKER AT ALL. Point/polygon/polyline were removed as UI — a ground
 * control point is created through the "New GCP" button (the correspondence flow),
 * and free-form shape annotation earned no keep. The cursor is simply what the
 * mouse always is now. The rail holds undo/redo/delete, which still operate on
 * whatever annotations exist. The stores keep the full `ToolId` vocabulary so old
 * drafts and state load untouched.
 */

export function AnnotationToolbar({
  orientation,
  canUndo,
  canRedo,
  undoLabel,
  redoLabel,
  onUndo,
  onRedo,
  canDelete,
  onDelete,
  deleteLabel = 'Delete selection (Del)',
  disabled = false,
}: AnnotationToolbarProps): JSX.Element {
  const dir = orientation === 'vertical' ? 'column' : 'row';

  return (
    <Stack
      direction={dir}
      spacing={0.5}
      alignItems="center"
      sx={{ p: 0.5 }}
      role="toolbar"
      aria-label={t('Annotation tools')}
      aria-orientation={orientation}
    >
      <Tooltip title={undoLabel ? `Undo ${undoLabel}` : 'Undo'} placement="right">
        <span>
          <IconButton
            size="small"
            onClick={onUndo}
            disabled={disabled || !canUndo}
            aria-label={undoLabel ? `Undo ${undoLabel}` : 'Undo'}
          >
            <UndoIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
      <Tooltip title={redoLabel ? `Redo ${redoLabel}` : 'Redo'} placement="right">
        <span>
          <IconButton
            size="small"
            onClick={onRedo}
            disabled={disabled || !canRedo}
            aria-label={redoLabel ? `Redo ${redoLabel}` : 'Redo'}
          >
            <RedoIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
      <Tooltip title={deleteLabel} placement="right">
        <span>
          <IconButton
            size="small"
            color="error"
            onClick={onDelete}
            disabled={disabled || !canDelete}
            aria-label={deleteLabel}
          >
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
    </Stack>
  );
}
