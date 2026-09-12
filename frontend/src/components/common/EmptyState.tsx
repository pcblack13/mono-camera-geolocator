/**
 * `common/EmptyState.tsx` — every pane's zero-data state (50-frontend §8.1).
 *
 * ★ "The panes are never blank rectangles. Each empty state names what will occupy
 *   it." A blank rectangle teaches nothing; this component always states the thing
 *   that belongs here and, where there is one, the action that puts it there.
 *
 * ★ (pure) — no store dependency, trivially testable.
 */

import type { JSX, ReactNode } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export interface EmptyStateAction {
  label: string;
  onClick: () => void;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface EmptyStateProps {
  /** A large, muted glyph — an MUI icon element, sized by this component. */
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  primaryAction?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  /** `full` centres in the whole pane; `inline` sits in normal flow (e.g. a table body). */
  variant?: 'full' | 'inline';
  /** Extra content below the actions — e.g. an `UploadDropzone`. */
  children?: ReactNode;
}

export function EmptyState({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  variant = 'full',
  children,
}: EmptyStateProps): JSX.Element {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: variant === 'full' ? 'center' : 'flex-start',
        textAlign: 'center',
        gap: 2,
        p: 4,
        width: '100%',
        minHeight: variant === 'full' ? '100%' : undefined,
        color: 'text.secondary',
      }}
    >
      {icon != null && (
        <Box
          aria-hidden
          sx={{
            '& > *': { fontSize: 56 },
            'color': 'text.disabled',
            'display': 'grid',
            'placeItems': 'center',
          }}
        >
          {icon}
        </Box>
      )}

      <Stack spacing={0.75} sx={{ maxWidth: 420 }}>
        <Typography variant="h6" color="text.primary">
          {title}
        </Typography>
        {description != null && (
          <Typography variant="body2" color="text.secondary">
            {description}
          </Typography>
        )}
      </Stack>

      {(primaryAction || secondaryAction) && (
        <Stack direction="row" spacing={1.5} sx={{ mt: 0.5 }}>
          {secondaryAction && (
            <Button
              variant="text"
              onClick={secondaryAction.onClick}
              startIcon={secondaryAction.icon}
              disabled={secondaryAction.disabled}
            >
              {secondaryAction.label}
            </Button>
          )}
          {primaryAction && (
            <Button
              variant="contained"
              onClick={primaryAction.onClick}
              startIcon={primaryAction.icon}
              disabled={primaryAction.disabled}
            >
              {primaryAction.label}
            </Button>
          )}
        </Stack>
      )}

      {children}
    </Box>
  );
}

export default EmptyState;
