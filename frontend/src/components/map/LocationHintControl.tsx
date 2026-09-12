/**
 * `map/LocationHintControl.tsx` — 50-frontend §2.20.
 *
 * How the surveyor narrows *where on Earth* the map is looking. Three sources, in
 * priority order (§2.20): the photo's EXIF GPS (auto-detected, one click), typed
 * coordinates, or clear. It writes a `LocationHint` to `mapStore` and flies the map to
 * it.
 *
 * ★ In the FULL system the hint also scopes the (deferred) match search. Here its live
 *   job is navigational: getting the satellite pane to the right place is the first
 *   thing a manual surveyor needs, and "Use photo GPS" makes that one click when the
 *   photograph carries coordinates.
 *
 * ★ Draw-a-box on the map is deliberately out of this component's first cut (it needs a
 *   map-draw interaction mode); typed center + radius covers the navigational need.
 *   Flagged in the IU-27 report.
 */

import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Popover from '@mui/material/Popover';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import Divider from '@mui/material/Divider';
import MyLocationIcon from '@mui/icons-material/MyLocation';
import PlaceIcon from '@mui/icons-material/Place';
import SearchIcon from '@mui/icons-material/Search';

import type { BBox, GeocodeResult, LatLon, LocationHint } from '../../types/geo';
import { providersApi } from '../../api/providers';
import { ApiError } from '../../types/common';
import { t } from '../../i18n';

export interface LocationHintControlProps {
  hint: LocationHint | null;
  /** The photo's EXIF GPS, offered as a one-click chip. `null` when the photo has none. */
  exifGps: LatLon | null;
  onChange: (hint: LocationHint | null) => void;
  onFlyTo: (p: LatLon, zoom?: number) => void;
  /** Frame a whole town/field when the geocoder returns bounds. Falls back to a point fly-to. */
  onFrameBounds?: (b: BBox) => void;
}

const DEFAULT_RADIUS_M = 500;
/** The zoom a name search lands on when the geocoder gives only a point (no bounds). */
const GEOCODE_POINT_ZOOM = 15;

export function LocationHintControl({
  hint,
  exifGps,
  onChange,
  onFlyTo,
  onFrameBounds,
}: LocationHintControlProps): JSX.Element {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [latStr, setLatStr] = useState('');
  const [lonStr, setLonStr] = useState('');
  const [searchStr, setSearchStr] = useState('');
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const applyPoint = (p: LatLon): void => {
    onChange({ center: p, radius_m: hint?.radius_m ?? DEFAULT_RADIUS_M, aoi: null });
    onFlyTo(p, 16);
  };

  const submitTyped = (): void => {
    // ★ Blank is blank — `Number('')` is 0, which is a real place (Null Island).
    if (latStr.trim() === '' || lonStr.trim() === '') return;
    const lat = Number(latStr);
    const lon = Number(lonStr);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return;
    applyPoint({ lat, lon });
    setAnchor(null);
  };

  const runSearch = async (): Promise<void> => {
    const q = searchStr.trim();
    if (q === '') return;
    setSearching(true);
    setSearchError(null);
    setSearched(true);
    try {
      const hits = await providersApi.geocode(q, 8);
      setResults(hits);
    } catch (e) {
      setResults([]);
      setSearchError(
        e instanceof ApiError
          ? e.message
          : 'Place search is unavailable — check your connection, or type coordinates below.',
      );
    } finally {
      setSearching(false);
    }
  };

  const pickResult = (r: GeocodeResult): void => {
    const p = { lat: r.lat, lon: r.lon };
    onChange({ center: p, radius_m: hint?.radius_m ?? DEFAULT_RADIUS_M, aoi: null });
    if (r.bbox && onFrameBounds) onFrameBounds(r.bbox);
    else onFlyTo(p, GEOCODE_POINT_ZOOM);
    setAnchor(null);
  };

  return (
    <>
      <Tooltip title={t('Go to a location')}>
        <IconButton
          size="small"
          onClick={(e) => setAnchor(e.currentTarget)}
          aria-label={t('Go to a location')}
          sx={{
            'bgcolor': 'background.paper',
            'boxShadow': 2,
            '&:hover': { bgcolor: 'background.paper' },
          }}
        >
          <PlaceIcon fontSize="small" color={hint ? 'primary' : 'inherit'} />
        </IconButton>
      </Tooltip>

      <Popover
        open={anchor !== null}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        disablePortal
      >
        <Box sx={{ p: 1.5, width: 288, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="subtitle2">{t('Go to a location')}</Typography>

          {/* ★ PHOTO GPS (1.2.6): when the photograph carries EXIF coordinates, the very
              first thing offered is a one-click jump straight to where it was taken. Only
              rendered — i.e. "turned on" — when the photo actually has embedded GPS. */}
          {exifGps && (
            <Button
              variant="contained"
              size="small"
              startIcon={<MyLocationIcon />}
              onClick={() => {
                applyPoint(exifGps);
                setAnchor(null);
              }}
              sx={{ justifyContent: 'flex-start', textTransform: 'none' }}
            >
              Go to this photo&rsquo;s location&nbsp;({exifGps.lat.toFixed(4)},{' '}
              {exifGps.lon.toFixed(4)})
            </Button>
          )}

          {/* Place-name search (online geocoder) */}
          <TextField
            size="small"
            fullWidth
            placeholder={t('Search a place, e.g. Yammouneh')}
            value={searchStr}
            onChange={(e) => setSearchStr(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void runSearch();
              }
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: searching ? (
                <InputAdornment position="end">
                  <CircularProgress size={16} />
                </InputAdornment>
              ) : (
                <InputAdornment position="end">
                  <Button
                    size="small"
                    onClick={() => void runSearch()}
                    disabled={searchStr.trim() === ''}
                  >
                    Go
                  </Button>
                </InputAdornment>
              ),
            }}
          />

          {searchError && (
            <Alert severity="warning" sx={{ py: 0, fontSize: 12 }}>
              {searchError}
            </Alert>
          )}

          {results.length > 0 && (
            <List dense disablePadding sx={{ maxHeight: 200, overflowY: 'auto' }}>
              {results.map((r, i) => (
                <ListItemButton
                  key={`${r.lat},${r.lon},${i}`}
                  onClick={() => pickResult(r)}
                  sx={{ borderRadius: 1 }}
                >
                  <ListItemText
                    primary={r.display_name}
                    secondary={`${r.lat.toFixed(4)}, ${r.lon.toFixed(4)}${r.category ? ` · ${r.category}` : ''}`}
                    primaryTypographyProps={{ variant: 'body2', sx: { fontSize: 13 } }}
                    secondaryTypographyProps={{ variant: 'caption' }}
                  />
                </ListItemButton>
              ))}
            </List>
          )}

          {searched && !searching && !searchError && results.length === 0 && (
            <Typography variant="caption" color="text.secondary">
              {t('No matches. Try a different spelling, or type coordinates below.')}
            </Typography>
          )}

          <Divider flexItem>
            <Typography variant="caption" color="text.secondary">
              {t('or coordinates')}
            </Typography>
          </Divider>

          {!exifGps && (
            <Typography variant="caption" color="text.secondary">
              {t('This photo has no embedded GPS.')}
            </Typography>
          )}

          <Box sx={{ display: 'flex', gap: 1 }}>
            <TextField
              size="small"
              label={t('Latitude')}
              value={latStr}
              onChange={(e) => setLatStr(e.target.value)}
              inputProps={{ inputMode: 'decimal' }}
            />
            <TextField
              size="small"
              label={t('Longitude')}
              value={lonStr}
              onChange={(e) => setLonStr(e.target.value)}
              inputProps={{ inputMode: 'decimal' }}
            />
          </Box>

          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Button
              size="small"
              disabled={hint === null}
              onClick={() => {
                onChange(null);
                setAnchor(null);
              }}
            >
              {t('Clear')}
            </Button>
            <Button size="small" variant="contained" onClick={submitTyped}>
              Go
            </Button>
          </Box>
        </Box>
      </Popover>
    </>
  );
}
