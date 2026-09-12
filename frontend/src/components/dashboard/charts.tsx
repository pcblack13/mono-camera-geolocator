/**
 * `dashboard/charts.tsx` — the information dashboard's small, honest marks.
 *
 * ★ Plain SVG and CSS, no chart library: thin bars anchored to the baseline with a
 *   rounded data end, a 2 px gap between neighbours, labels in text tokens (never
 *   the series colour), and a native tooltip on every mark. One hue per chart for
 *   magnitude; the status palette — always with its word — for state.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export interface BarRow {
  label: string;
  value: number;
  /** Override the single-hue fill — used only for STATE rows, with their word beside. */
  color?: string;
  /** A trailing detail, e.g. "of 7". */
  note?: string;
}

/** Horizontal bars, one per row, all on one scale. */
export function BarRows({
  rows,
  max,
  color = 'var(--accent)',
  'aria-label': ariaLabel,
}: {
  rows: readonly BarRow[];
  /** The scale's end; defaults to the largest row. */
  max?: number;
  color?: string;
  'aria-label': string;
}): JSX.Element {
  const top = Math.max(1, max ?? Math.max(...rows.map((r) => r.value), 0));
  return (
    <Stack spacing={0.75} role="img" aria-label={ariaLabel}>
      {rows.map((r) => (
        <Box
          key={r.label}
          title={`${r.label}: ${r.value}${r.note ? ` ${r.note}` : ''}`}
          sx={{ display: 'grid', gridTemplateColumns: 'minmax(96px, 30%) 1fr auto', gap: 1, alignItems: 'center' }}
        >
          <Typography variant="caption" color="text.secondary" noWrap>
            {r.label}
          </Typography>
          <Box sx={{ height: 8, borderRadius: 4, bgcolor: 'var(--hairline)', overflow: 'hidden' }}>
            <Box
              sx={{
                width: `${Math.min(100, (r.value / top) * 100)}%`,
                height: '100%',
                borderRadius: 4,
                bgcolor: r.color ?? color,
                transition: 'width var(--dur-fast) var(--ease-standard)',
              }}
            />
          </Box>
          <Typography variant="caption" className="le-mono" sx={{ minWidth: 28, textAlign: 'end' }}>
            {r.value}
            {r.note && (
              <Box component="span" sx={{ color: 'text.disabled', ml: 0.5 }}>
                {r.note}
              </Box>
            )}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}

export interface DayCount {
  /** ISO date, e.g. 2026-09-10. */
  day: string;
  count: number;
}

/** Columns per day, oldest → newest, for "how much lately". */
export function DayBars({
  days,
  'aria-label': ariaLabel,
  height = 56,
}: {
  days: readonly DayCount[];
  'aria-label': string;
  height?: number;
}): JSX.Element {
  const top = Math.max(1, ...days.map((d) => d.count));
  const w = 100 / Math.max(1, days.length);
  return (
    <Box>
      <Box
        component="svg"
        role="img"
        aria-label={ariaLabel}
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        sx={{ display: 'block', width: '100%', height }}
      >
        <line x1={0} y1={height - 0.5} x2={100} y2={height - 0.5} stroke="var(--hairline-strong)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        {days.map((d, i) => {
          const h = d.count === 0 ? 0 : Math.max(2, ((height - 4) * d.count) / top);
          return (
            <rect
              key={d.day}
              x={i * w + w * 0.15}
              y={height - 1 - h}
              width={w * 0.7}
              height={h}
              rx={1}
              fill="var(--accent)"
              opacity={d.count === 0 ? 0 : 0.9}
            >
              <title>{`${d.day}: ${d.count}`}</title>
            </rect>
          );
        })}
      </Box>
      <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.25 }}>
        <Typography variant="caption" color="text.disabled" className="le-mono">
          {days[0]?.day.slice(5) ?? ''}
        </Typography>
        <Typography variant="caption" color="text.disabled" className="le-mono">
          {days[days.length - 1]?.day.slice(5) ?? ''}
        </Typography>
      </Stack>
    </Box>
  );
}

/** A headline number with its word under it. */
export function StatTile({
  value,
  label,
  tone,
  hint,
}: {
  value: number | string;
  label: string;
  tone?: string;
  hint?: string;
}): JSX.Element {
  return (
    <Box
      title={hint}
      sx={{
        p: 1.5,
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
        minWidth: 0,
      }}
    >
      <Typography className="le-mono" sx={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1, color: tone ?? 'text.primary' }}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
        {label}
      </Typography>
    </Box>
  );
}

/** A titled card holding one reading of the dashboard. */
export function Panel({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}): JSX.Element {
  return (
    <Box
      component="section"
      aria-label={title}
      sx={{
        p: 2,
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
        minWidth: 0,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, flex: 1 }}>
          {title}
        </Typography>
        {action}
      </Stack>
      {children}
    </Box>
  );
}
