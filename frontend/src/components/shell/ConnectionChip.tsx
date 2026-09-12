/**
 * `shell/ConnectionChip.tsx` — the system's pulse, always on the top bar.
 *
 * ★ OFFLINE-PROUD, per the brief: cache coverage and system health are
 *   first-class status, not a buried menu. The chip shows the worst component's
 *   state in one dot; the popover shows every component with its latency and its
 *   own message — the same detail `/health/ready` gives a probe, because an
 *   operator debugging in the field deserves what the infrastructure gets.
 *
 * ★ THE FAILURE STATE IS THE POINT. When the API itself is unreachable, the chip
 *   is the one element that must still say so — it renders "API unreachable"
 *   from the failed fetch rather than vanishing with the data it cannot get.
 */

import { useState, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ButtonBase from '@mui/material/ButtonBase';
import Popover from '@mui/material/Popover';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';

import { capabilitiesApi } from '../../api/capabilities';
import { t } from '../../i18n';
import type { ComponentStatus } from '../../types';

const DOT: Record<ComponentStatus, string> = {
  up: 'var(--status-ok)',
  degraded: 'var(--status-warn)',
  down: 'var(--status-error)',
  skipped: 'var(--acc-none)',
};

export function ConnectionChip(): JSX.Element {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const navigate = useNavigate();

  const readiness = useQuery({
    queryKey: ['health', 'readiness'],
    queryFn: ({ signal }) => capabilitiesApi.readiness(undefined, false, signal),
    // A pulse, not a poll storm: health changes on the scale of services, not frames.
    refetchInterval: 30_000,
    retry: 1,
  });

  const unreachable = readiness.isError;
  const status = readiness.data?.status;
  const dot = unreachable
    ? 'var(--status-error)'
    : status === 'ok'
      ? 'var(--status-ok)'
      : status === 'degraded'
        ? 'var(--status-warn)'
        : status === undefined
          ? 'var(--acc-none)'
          : 'var(--status-error)';
  const label = unreachable
    ? t('API unreachable')
    : status === 'ok'
      ? t('Online')
      : status === 'degraded'
        ? t('Degraded')
        : status === undefined
          ? '…'
          : t('Not ready');

  return (
    <>
      <ButtonBase
        onClick={(e) => setAnchor(e.currentTarget)}
        aria-label={`${t('System status')}: ${label}`}
        className="le-chrome"
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.75,
          px: 1,
          height: 'var(--control-sm)',
          borderRadius: 'var(--radius-pill)',
          border: '1px solid var(--hairline-strong)',
        }}
      >
        <Box sx={{ width: 7, height: 7, borderRadius: '50%', bgcolor: dot, flexShrink: 0 }} />
        <Typography
          className="le-mono"
          sx={{ fontSize: 10.5, color: 'text.secondary', whiteSpace: 'nowrap' }}
        >
          {label}
        </Typography>
      </ButtonBase>

      <Popover
        open={anchor !== null}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Box sx={{ p: 1.5, minWidth: 260 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {t('System status')}
          </Typography>
          {unreachable ? (
            <Typography className="le-mono" sx={{ fontSize: 11.5, color: 'error.main' }}>
              {t('The API did not answer — the app cannot reach its own server.')}
            </Typography>
          ) : (
            <Stack spacing={0.25}>
              {(readiness.data?.components ?? []).map((c) => (
                <Stack
                  key={c.name}
                  direction="row"
                  alignItems="center"
                  spacing={1}
                  sx={{ py: 0.25 }}
                >
                  <Box
                    sx={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      bgcolor: DOT[c.status],
                      flexShrink: 0,
                    }}
                  />
                  <Typography className="le-mono" sx={{ fontSize: 11, flex: 1 }}>
                    {c.name}
                  </Typography>
                  <Typography className="le-mono" sx={{ fontSize: 10.5, color: 'text.disabled' }}>
                    {c.latency_ms !== null ? `${Math.round(c.latency_ms)} ms` : c.status}
                  </Typography>
                </Stack>
              ))}
              {(readiness.data?.components ?? [])
                .filter((c) => c.message !== null && c.status !== 'up')
                .map((c) => (
                  <Typography
                    key={`${c.name}-msg`}
                    className="le-mono"
                    sx={{
                      fontSize: 10.5,
                      color: 'text.secondary',
                      pl: 1.75,
                      wordBreak: 'break-word',
                    }}
                  >
                    {c.message}
                  </Typography>
                ))}
            </Stack>
          )}
          {/* ★ The door to the FULL story: the same components explained one by
              one, plus the server's live log — where "why is this dot amber?"
              gets answered. Shown even when the API is unreachable: the status
              page renders that state honestly rather than hiding the door. */}
          <Button
            fullWidth
            size="small"
            variant="outlined"
            startIcon={<MonitorHeartOutlinedIcon />}
            sx={{ mt: 1.25 }}
            onClick={() => {
              setAnchor(null);
              navigate('/status');
            }}
          >
            {t('Open app status & logs')}
          </Button>
        </Box>
      </Popover>
    </>
  );
}
