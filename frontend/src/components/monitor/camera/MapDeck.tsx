/**
 * `monitor/camera/MapDeck.tsx` — the marks on the ground, synced to the video.
 *
 * ★ The map is the existing `LiveMarksMap` (Leaflet, lazy). Selection flows both
 *   ways through the page: a selected box highlights its mark; a marker click
 *   reports its index. The map never re-centres on a click — its centre is the
 *   operator's from the first touch.
 *
 * ★ The empty state is ONE LINE and the link that fixes it — not an illustration.
 */

import { lazy, Suspense, type JSX } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Link from '@mui/material/Link';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';

import type { DetectionMark } from '../../../api/detection';
import type { DriftVerdict } from '../../../api/drift';
import type { ProviderInfo } from '../../../types/geo';
import { DriftMapBanner } from '../../drift/DriftMapBanner';
import { t } from '../../../i18n';

const LiveMarksMap = lazy(() => import('../../live/LiveMarksMap'));

export interface MapDeckProps {
  marks: DetectionMark[];
  /** Where this camera's lookup table is set up — its settings page (2026-09-04). */
  settingsTo?: string;
  center: [number, number] | null;
  provider: ProviderInfo | undefined;
  lutSite: string;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
  driftVerdict: DriftVerdict | null;
  /** ★ Live predict (2026-09-10): the cursor's ground point, as a reticle. */
  prediction?: { lat: number; lon: number } | null;
  predictionPinned?: boolean;
}

export function MapDeck(p: MapDeckProps): JSX.Element {
  if (p.provider === undefined || p.center === null) {
    return (
      <Box sx={{ p: 2, display: 'flex', alignItems: 'center', height: '100%' }}>
        <Typography variant="body2" color="text.secondary">
          {p.lutSite === '' ? (
            <>
              {t('No lookup table — detections are counted, not placed.')}{' '}
              <Link component={RouterLink} to={p.settingsTo ?? '/cameras'}>
                {t('Set up the lookup table')}
              </Link>
            </>
          ) : (
            t(
              'This lookup table records no camera position, so the map cannot open on its site. Detections will still be placed once the run starts.',
            )
          )}
        </Typography>
      </Box>
    );
  }
  return (
    <Box sx={{ position: 'absolute', inset: 0 }}>
      <DriftMapBanner verdict={p.driftVerdict} />
      <Suspense fallback={<Skeleton variant="rectangular" height="100%" />}>
        <LiveMarksMap
          marks={p.marks}
          center={p.center}
          provider={p.provider}
          selectedIndex={p.selectedIndex}
          onSelect={p.onSelect}
          // ★ The deck's height is the law here — no 360px floor to spill past it.
          minHeight={0}
          prediction={p.prediction ?? null}
          predictionPinned={p.predictionPinned ?? false}
        />
      </Suspense>
    </Box>
  );
}
