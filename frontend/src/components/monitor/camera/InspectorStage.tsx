/**
 * `monitor/camera/InspectorStage.tsx` — one numbered stage of the inspector.
 *
 * ★ COLLAPSED, IT STILL TELLS THE TRUTH: a green check and a one-line summary when
 *   satisfied; the gate line and its fix when not. A gated stage's body is
 *   collapsed — the controls exist, but the line explains why they cannot act yet.
 */

import { useState, type JSX, type ReactNode } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Collapse from '@mui/material/Collapse';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';

import type { StageState } from '../../../lib/monitor/stages';
import { t } from '../../../i18n';

const CIRCLED = ['①', '②', '③', '④', '⑤'] as const;

export interface InspectorStageProps {
  stage: StageState;
  onFix?: (action: NonNullable<StageState['fix']>['action']) => void;
  /** Open by default when satisfied; a gated stage opens on demand. */
  children: ReactNode;
}

export function InspectorStage({ stage, onFix, children }: InspectorStageProps): JSX.Element {
  const [open, setOpen] = useState(stage.satisfied);
  const fix = stage.fix;
  return (
    <Box
      component="section"
      aria-labelledby={`stage-${stage.key}`}
      data-testid={`stage-${stage.key}`}
      data-satisfied={stage.satisfied}
      sx={{ borderBottom: '1px solid var(--hairline)' }}
    >
      <Stack
        direction="row"
        alignItems="center"
        spacing={1}
        component="button"
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        sx={{
          'width': '100%',
          'textAlign': 'start',
          'bgcolor': 'transparent',
          'border': 0,
          'px': 1.5,
          'py': 1,
          'cursor': 'pointer',
          'color': 'inherit',
          '&:hover': { bgcolor: 'var(--accent-quiet)' },
        }}
      >
        {stage.satisfied ? (
          <CheckCircleIcon sx={{ fontSize: 18, color: 'var(--status-ok)' }} />
        ) : (
          <RadioButtonUncheckedIcon sx={{ fontSize: 18, color: 'var(--text-tertiary)' }} />
        )}
        <Typography
          variant="mono"
          component="span"
          sx={{ fontSize: 13, color: 'var(--text-tertiary)' }}
        >
          {CIRCLED[stage.index - 1]}
        </Typography>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography id={`stage-${stage.key}`} variant="subtitle2" sx={{ lineHeight: 1.2 }}>
            {t(stage.title)}
          </Typography>
          <Typography
            variant="caption"
            noWrap
            title={stage.summary}
            sx={{
              display: 'block',
              color: stage.satisfied ? 'var(--text-secondary)' : 'var(--text-tertiary)',
            }}
          >
            {t(stage.summary)}
          </Typography>
        </Box>
        <ExpandMoreIcon
          sx={{
            fontSize: 18,
            color: 'var(--text-tertiary)',
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform 150ms cubic-bezier(0.2,0,0,1)',
          }}
        />
      </Stack>
      {fix !== undefined && !stage.satisfied && (
        <Box sx={{ px: 1.5, pb: 1 }}>
          {fix.to !== undefined ? (
            <Button size="small" component={RouterLink} to={fix.to}>
              {t(fix.label)} →
            </Button>
          ) : (
            <Button size="small" onClick={() => fix.action && onFix?.(fix.action)}>
              {t(fix.label)}
            </Button>
          )}
        </Box>
      )}
      <Collapse in={open} timeout={150}>
        <Box sx={{ px: 1.5, pb: 1.5 }}>{children}</Box>
      </Collapse>
    </Box>
  );
}
