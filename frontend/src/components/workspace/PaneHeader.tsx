/**
 * `workspace/PaneHeader.tsx` — the label strip atop each pane (50-frontend §2, wireframe §1.2). **(pure)**
 *
 * ★ A thin, non-scrolling header that names the pane ("IMAGE field_north_0714.jpg",
 *   "MAP") and hosts pane-local controls on the right (basemap switch, viewer
 *   controls). It never scrolls with pane content — the workspace is a tool, not a
 *   document, and each region manages its own overflow (§1.1).
 */

import type { JSX, ReactNode } from 'react';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export interface PaneHeaderProps {
  /** Short uppercase pane label, e.g. "IMAGE" / "MAP". */
  label: string;
  /** Optional secondary text — a filename, dimensions, a coordinate readout. */
  detail?: ReactNode;
  /** Right-aligned controls. */
  actions?: ReactNode;
  /** A leading glyph. */
  icon?: ReactNode;
}

export function PaneHeader({ label, detail, actions, icon }: PaneHeaderProps): JSX.Element {
  return (
    <Stack
      direction="row"
      alignItems="center"
      spacing={1}
      sx={{
        flex: '0 0 auto',
        px: 1.5,
        height: 40,
        borderBottom: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
        minWidth: 0,
      }}
    >
      {icon != null && <Box sx={{ display: 'flex', color: 'text.secondary' }}>{icon}</Box>}
      <Typography variant="overline" sx={{ letterSpacing: 1, lineHeight: 1 }}>
        {label}
      </Typography>
      {detail != null && (
        <Typography
          variant="body2"
          color="text.secondary"
          noWrap
          sx={{ flex: 1, minWidth: 0 }}
          title={typeof detail === 'string' ? detail : undefined}
        >
          {detail}
        </Typography>
      )}
      <Box sx={{ flex: detail != null ? '0 0 auto' : 1 }} />
      {actions != null && (
        <Stack direction="row" spacing={0.5} alignItems="center">
          {actions}
        </Stack>
      )}
    </Stack>
  );
}

export default PaneHeader;
