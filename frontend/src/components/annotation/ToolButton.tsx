/**
 * `annotation/ToolButton.tsx` (pure) — one entry in the ToolRail. 50-frontend.md §2.11.
 *
 * A `ToggleButton` carrying an icon, an accessible label, and a tooltip that names the
 * keyboard shortcut — discoverable shortcuts are how this becomes fast for a
 * professional (§2.11).
 */

import ToggleButton from '@mui/material/ToggleButton';
import Tooltip from '@mui/material/Tooltip';

export interface ToolButtonProps {
  value: string;
  icon: JSX.Element;
  /** Human label — the tooltip title and the `aria-label`. */
  label: string;
  /** e.g. `'P'` or `'⌘Z'`. Appended to the tooltip. */
  shortcut?: string;
  selected: boolean;
  disabled?: boolean;
  onClick: () => void;
}

export function ToolButton({
  value,
  icon,
  label,
  shortcut,
  selected,
  disabled,
  onClick,
}: ToolButtonProps): JSX.Element {
  return (
    <Tooltip title={shortcut ? `${label} (${shortcut})` : label} placement="right">
      <span>
        <ToggleButton
          value={value}
          selected={selected}
          disabled={disabled}
          onClick={onClick}
          aria-label={label}
          size="small"
          sx={{ border: 0, width: 40, height: 40 }}
        >
          {icon}
        </ToggleButton>
      </span>
    </Tooltip>
  );
}
