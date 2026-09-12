/**
 * `workspace/WorkspaceSetupPanel.tsx` — what stands in the map's place until the
 * surveyor has said how this project's map should work.
 *
 * ★ **The map is not deployed on arrival, and that is the point.** Dropping straight
 *   onto a live basemap silently decides which imagery provider the surveyor's
 *   coordinates are read against — a licence, a network dependency, and several metres
 *   of georeferencing error. That choice belongs to the project and is stated here
 *   before a single tile is fetched.
 *
 * ★ **The DEM moved to the project's SETUP PAGE** (`/projects/{id}/setup`), where it
 *   sits with the other project-wide inputs — main image, camera intrinsics, position
 *   and tilt. This panel no longer re-asks for it on the way into every workspace; it
 *   only points there.
 */

import { type JSX } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import LayersOutlinedIcon from '@mui/icons-material/LayersOutlined';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';

import { useProviders } from '../../api/hooks/useProviders';
import {
  useProjectSetupStore,
  type MapSourceKind,
  type ProjectSetup,
} from '../../store/projectSetupStore';
import { useCameraRefForProject } from '../../lib/cameras/projectCamera';
import { type Uuid } from '../../types/common';
import type { BasemapKind } from '../../types/geo';
import { t } from '../../i18n';

interface SourceOption {
  value: MapSourceKind;
  label: string;
  detail: string;
  /** Stated plainly — each of these costs the surveyor something different. */
  caveat: string | null;
  /**
   * ★ True when the caveat is pure SETUP instructions ("set this variable"), which are
   * noise once the server reports the source configured — a surveyor who already
   * provided the token reads them as "it still wants a token". Licence/honesty caveats
   * (Google's ToS, Sentinel's 10 m pixels) stay visible regardless: being configured
   * does not discharge them.
   */
  setupOnly?: boolean;
}

/** Setup source → the imagery registry key the server knows it by. */
const SOURCE_PROVIDER_ID: Record<MapSourceKind, string | null> = {
  mapbox: 'mapbox_satellite',
  esri: 'esri_world_imagery',
  google: 'google_map_tiles',
  sentinel: 'sentinel_copernicus',
  offline: null, // cached tiles ride whatever provider they were cached from
};

const SOURCES: SourceOption[] = [
  {
    value: 'mapbox',
    label: 'Mapbox Satellite',
    detail: 'Maxar-class imagery, ±5 m georeferencing. Satellite only — no hybrid or terrain view.',
    caveat:
      'Needs LE_MAPBOX_ACCESS_TOKEN in backend/.env (a public token from a free ' +
      'account at mapbox.com — the free tier covers 200k tiles/month), then an API ' +
      'restart.',
    setupOnly: true,
  },
  {
    value: 'esri',
    label: 'Esri World Imagery',
    detail:
      'Keyless — always available, no account or token. Satellite, hybrid and terrain ' +
      'views. ±8 m georeferencing (an estimate: the mosaic mixes many vendors, so ' +
      'alignment varies by region).',
    caveat: null,
  },
  {
    value: 'google',
    label: 'Google (Map Tiles)',
    detail: 'Sharper in some regions. ±5 m georeferencing. Clean tiles — no repeated credit strip.',
    caveat:
      'Google Map Tiles API — a commercial, separately licensed product (NOT Google ' +
      'Earth, which is excluded here by licence). Needs LE_GOOGLE_MAPS_STATIC_KEY and ' +
      'LE_GOOGLE_TOS_ACKNOWLEDGED=true in backend/.env, AND the Map Tiles API enabled ' +
      'on that key in the Google Cloud console. Attribution is rendered once, below the ' +
      'map; it is a licence obligation, not decoration.',
  },
  {
    value: 'sentinel',
    label: 'Sentinel / Copernicus',
    detail:
      'ESA, free and fully open (commercial use included). ~5-day revisit — the imagery behind EU emergency mapping. ±11 m georeferencing.',
    caveat:
      '10 m pixels, and the provider refuses zoom beyond 15 rather than faking detail: ' +
      'right for locating an area and monitoring change, WRONG for precise GCP clicking — ' +
      'a gate post is smaller than one pixel. Needs LE_COPERNICUS_CLIENT_ID / ' +
      '_CLIENT_SECRET / _INSTANCE_ID in backend/.env (free account at ' +
      'dataspace.copernicus.eu), then an API restart.',
  },
  {
    value: 'offline',
    label: 'Pre-cached offline tiles',
    detail: 'No network. Only the areas and zooms you cached are available.',
    caveat:
      'Cache the survey area while online first — outside the cached extent the map will be blank.',
  },
];

const BASEMAPS: { value: BasemapKind; label: string }[] = [
  { value: 'satellite', label: 'Satellite' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'terrain', label: 'Terrain' },
];

export interface WorkspaceSetupPanelProps {
  projectId: Uuid;
}

export function WorkspaceSetupPanel({ projectId }: WorkspaceSetupPanelProps): JSX.Element {
  const setup: ProjectSetup = useProjectSetupStore((s) => s.get(projectId));
  // ★ A camera's backing project speaks as the camera (2026-09-04).
  const cameraRef = useCameraRefForProject(projectId);
  const setSetup = useProjectSetupStore((s) => s.set);

  // ★ Live configured-state per source, so an impossible choice is visible BEFORE
  //   "Open the map" — a silent fallback afterwards taught us that a guard nobody can
  //   see reads as a bug ("I picked Google and it stayed on Esri").
  const providersQuery = useProviders();

  /**
   * ★ WHY A SOURCE IS UNUSABLE, NOT MERELY THAT IT IS (1.2.6). Both failures block
   *   the map, but they have DIFFERENT cures and the old single "not configured on
   *   server" message named the wrong one — it sent a surveyor to add an API key for
   *   Esri, which is keyless and whose `is_configured()` is unconditionally true.
   *   The real cause there is always the operator's allow-list.
   *
   *   · `'unconfigured'` — the provider's own verdict: a key/path is missing.
   *   · `'banned'`       — `LE_ALLOWED_PROVIDERS` excludes it (server answers 403).
   *   · `null`           — the list has not loaded; claim nothing.
   */
  type SourceBlock = 'unconfigured' | 'banned' | null;
  const sourceBlock = (source: MapSourceKind): SourceBlock => {
    const id = SOURCE_PROVIDER_ID[source];
    if (id === null) return null; // offline: nothing server-side to configure here
    if (providersQuery.data === undefined) return null; // unknown yet — claim nothing
    const info = providersQuery.data.items.find((x) => x.name === id);
    if (info === undefined) return 'unconfigured'; // the server does not know it at all
    if (info.allowed === false) return 'banned';
    return info.configured ? null : 'unconfigured';
  };
  const isSourceConfigured = (source: MapSourceKind): boolean | null => {
    const id = SOURCE_PROVIDER_ID[source];
    if (id === null) return true; // offline: nothing server-side to configure here
    if (providersQuery.data === undefined) return null; // unknown yet — claim nothing
    return sourceBlock(source) === null;
  };

  const chosen = SOURCES.find((s) => s.value === setup.source) ?? SOURCES[0];

  // ★ Offer only the basemap kinds the chosen provider can SERVE (Mapbox is
  //   satellite-only; Esri had all three). A "Hybrid" entry the provider cannot draw
  //   is a promise the map would break on open. Unknown (list still loading) or
  //   offline ⇒ all kinds, and the map's own switcher stays honest downstream.
  const kindsFor = (source: MapSourceKind): BasemapKind[] | null => {
    const id = SOURCE_PROVIDER_ID[source];
    if (id === null) return null;
    const kinds = providersQuery.data?.items.find((x) => x.name === id)?.capabilities?.kinds;
    return kinds && kinds.length > 0 ? kinds : null;
  };
  const offeredKinds = kindsFor(setup.source);
  const offeredBasemaps = BASEMAPS.filter(
    (b) => offeredKinds === null || offeredKinds.includes(b.value),
  );

  const handleSourceChange = (next: MapSourceKind): void => {
    const patch: Partial<ProjectSetup> = { source: next };
    // A basemap the new provider cannot serve is corrected here, visibly, not
    // silently swapped by the map later.
    const kinds = kindsFor(next);
    if (kinds !== null && !kinds.includes(setup.basemap)) patch.basemap = 'satellite';
    setSetup(projectId, patch);
  };

  return (
    <Box sx={{ height: '100%', overflowY: 'auto', bgcolor: 'background.default' }}>
      <Box sx={{ maxWidth: 620, mx: 'auto', p: 3 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 0.5 }}>
          <TuneOutlinedIcon color="primary" />
          <Typography variant="h6">
            {cameraRef !== null ? t('Set up this camera’s map') : t('Set up this project’s map')}
          </Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          {cameraRef !== null
            ? t(
                'This choice belongs to this camera and shapes every control point placed on its frame. The map loads once you are done. The DEM, the calibration and the position are set on the camera’s settings page.',
              )
            : t(
                'This choice belongs to this project and shapes every control point in it. The map loads once you are done. The elevation source (DEM) is set in Project settings; the main image and camera live on each photo’s setup page.',
              )}
        </Typography>

        {/* ── Imagery ──────────────────────────────────────────────────── */}
        <Card variant="outlined" sx={{ mb: 2 }}>
          <CardContent>
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
              <LayersOutlinedIcon fontSize="small" color="action" />
              <Typography variant="subtitle2">{t('Map imagery')}</Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              {t(
                'What you click on to place a coordinate. The provider’s own georeferencing error is usually the largest term in a GCP’s accuracy.',
              )}
            </Typography>

            <RadioGroup
              value={setup.source}
              onChange={(e) => handleSourceChange(e.target.value as MapSourceKind)}
            >
              {SOURCES.map((s) => (
                <Box key={s.value} sx={{ mb: 0.5 }}>
                  <FormControlLabel
                    value={s.value}
                    control={<Radio size="small" />}
                    label={
                      <Box>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="body2">{s.label}</Typography>
                          {sourceBlock(s.value) !== null && (
                            <Chip
                              size="small"
                              color="warning"
                              variant="outlined"
                              label={
                                sourceBlock(s.value) === 'banned'
                                  ? 'blocked by the server’s provider list'
                                  : 'not configured on server'
                              }
                            />
                          )}
                        </Stack>
                        <Typography variant="caption" color="text.secondary">
                          {s.detail}
                        </Typography>
                      </Box>
                    }
                  />
                </Box>
              ))}
            </RadioGroup>

            {chosen.caveat && (!chosen.setupOnly || isSourceConfigured(setup.source) !== true) && (
              <Alert severity="info" sx={{ mt: 1 }}>
                {chosen.caveat}
              </Alert>
            )}

            {sourceBlock(setup.source) === 'banned' && (
              <Alert severity="warning" sx={{ mt: 1 }}>
                <AlertTitle>{t('This source is blocked by the server’s provider list')}</AlertTitle>
                Nothing is missing from this provider — the server’s{' '}
                <code>LE_ALLOWED_PROVIDERS</code>{' '}
                {t(
                  'simply does not list it, so requesting it is refused. Add it to that line (or delete the line entirely — empty means every provider is allowed) and restart the app.',
                )}
                <Box component="span" sx={{ display: 'block', mt: 1 }}>
                  {t('★ In the installed app that setting is read from the')}{' '}
                  <b>{t('running copy’s')}</b> <code>.env</code> —{' '}
                  <code>~/.local/share/MonoCameraGeolocator/work/.env</code> — <b>not</b> from{' '}
                  <code>backend/.env</code>{' '}
                  {t('in the source tree. Editing the wrong one changes nothing.')}
                </Box>
              </Alert>
            )}

            {sourceBlock(setup.source) === 'unconfigured' && (
              <Alert severity="warning" sx={{ mt: 1 }}>
                <AlertTitle>{t('This source is not configured on the server')}</AlertTitle>
                {t(
                  'You can keep it selected, but the map will stay on the server’s default provider until the variables in the note above are set in the running copy’s .env file, and the API is restarted — pointing the map at an unconfigured provider would only render a grid of failed tiles.',
                )}
              </Alert>
            )}

            <FormControl size="small" fullWidth sx={{ mt: 2 }}>
              <InputLabel id="setup-basemap">{t('Basemap')}</InputLabel>
              <Select
                labelId="setup-basemap"
                label={t('Basemap')}
                value={setup.basemap}
                onChange={(e) => setSetup(projectId, { basemap: e.target.value as BasemapKind })}
              >
                {offeredBasemaps.map((b) => (
                  <MenuItem key={b.value} value={b.value}>
                    {b.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </CardContent>
        </Card>

        <Divider sx={{ my: 2 }} />

        <Stack direction="row" spacing={1.5} alignItems="center">
          <Button variant="contained" onClick={() => setSetup(projectId, { configured: true })}>
            {t('Open the map')}
          </Button>
          <Chip size="small" variant="outlined" label={chosen.label} />
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          {t(
            'You can change this later from the map’s settings button. The DEM is managed in the project’s setup page (Project settings).',
          )}
        </Typography>
      </Box>
    </Box>
  );
}

export default WorkspaceSetupPanel;
