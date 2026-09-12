/**
 * `map/GoToLocationDialog.tsx` — "take me to this place".
 *
 * ★ THREE SEPARATE FIELDS, because they are three different questions:
 *   - **Zone / place name** — matched against the zones this app actually knows:
 *     the surveyor's own projects and the ground control points they have placed.
 *   - **Latitude** and **Longitude** — one box each, so there is no ambiguity about
 *     which number is which (the single-box form had to GUESS from hemisphere
 *     letters; two boxes cannot be misread). Each accepts decimal degrees or
 *     degrees/minutes/seconds, with or without a hemisphere letter.
 *
 * ★ Whichever is filled in wins: type a name to search, or fill both coordinate
 *   boxes to fly there. Filling one coordinate box alone is refused — half a
 *   coordinate is not a place.
 *
 * ★ NAMES ARE MATCHED LOCALLY, ON PURPOSE. There is no online gazetteer call: this
 *   product runs fully offline, and a "geocoder" that silently needs the internet
 *   would break exactly where surveyors work. The app can only honestly claim to
 *   know the places its own data names — so that is what it searches, and it says
 *   so when nothing matches.
 */

import { useMemo, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import PlaceOutlinedIcon from '@mui/icons-material/PlaceOutlined';

import { parseCoordinateValue } from '../../lib/geo/parseLocation';
import type { LatLon } from '../../types/geo';
import type { GcpOverview } from '../../types/gcp';
import { t } from '../../i18n';

/** A place the app can honestly take you to. */
export interface NamedPlace {
  key: string;
  label: string;
  detail: string;
  at: LatLon;
}

export interface GoToLocationDialogProps {
  open: boolean;
  onClose: () => void;
  /** The searchable places — built by the caller from its own data. */
  places: readonly NamedPlace[];
  /** Fly the map. `zoom` is a suggestion; a coordinate jump wants a close one. */
  onGo: (at: LatLon, zoom: number) => void;
}

/** Points → searchable places, deduplicated by zone name. Exported for the caller. */
export function placesFromGcps(points: readonly GcpOverview[]): NamedPlace[] {
  const byProject = new Map<string, NamedPlace>();
  const pointPlaces: NamedPlace[] = [];
  for (const p of points) {
    if (!byProject.has(p.project_id as string)) {
      byProject.set(p.project_id as string, {
        key: `project:${p.project_id}`,
        label: p.project_name,
        detail: 'project — first point',
        at: { lat: p.lat, lon: p.lon },
      });
    }
    const name = p.code ?? p.landmark_name;
    if (name) {
      pointPlaces.push({
        key: `gcp:${p.id}`,
        label: name,
        detail: `point in ${p.project_name}`,
        at: { lat: p.lat, lon: p.lon },
      });
    }
  }
  return [...byProject.values(), ...pointPlaces];
}

export function GoToLocationDialog({
  open,
  onClose,
  places,
  onGo,
}: GoToLocationDialogProps): JSX.Element {
  const [name, setName] = useState('');
  const [latText, setLatText] = useState('');
  const [lonText, setLonText] = useState('');

  // Each box is parsed on its own: decimal degrees or DMS, hemisphere optional.
  const lat = useMemo(() => parseCoordinateValue(latText, 'lat'), [latText]);
  const lon = useMemo(() => parseCoordinateValue(lonText, 'lon'), [lonText]);
  const latBad = latText.trim() !== '' && lat === null;
  const lonBad = lonText.trim() !== '' && lon === null;
  const coordinate = lat !== null && lon !== null ? { lat, lon } : null;

  const matches = useMemo(() => {
    const q = name.trim().toLowerCase();
    if (q === '') return [];
    return places
      .filter((p) => p.label.toLowerCase().includes(q) || p.detail.toLowerCase().includes(q))
      .slice(0, 6);
  }, [places, name]);

  const reset = (): void => {
    setName('');
    setLatText('');
    setLonText('');
  };

  const go = (at: LatLon, zoom: number): void => {
    onGo(at, zoom);
    reset();
    onClose();
  };

  /** Coordinates win when both are given; otherwise the first name match. */
  const submit = (): void => {
    if (coordinate) go(coordinate, 16);
    else if (matches.length > 0) go(matches[0].at, 15);
  };
  const canSubmit = coordinate !== null || matches.length > 0;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t('Go to a location')}</DialogTitle>
      <DialogContent>
        {/* ── by name ────────────────────────────────────────────────────── */}
        <TextField
          autoFocus
          fullWidth
          label={t('Zone or place name')}
          placeholder="Canal survey"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit();
          }}
          sx={{ mt: 1 }}
        />

        {matches.length > 0 && (
          <List dense sx={{ mt: 0.5 }}>
            {matches.map((place) => (
              <ListItemButton
                key={place.key}
                onClick={() => go(place.at, 15)}
                sx={{ borderRadius: 1 }}
              >
                <ListItemIcon sx={{ minWidth: 36 }}>
                  <PlaceOutlinedIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primary={place.label} secondary={place.detail} />
              </ListItemButton>
            ))}
          </List>
        )}

        {name.trim() !== '' && matches.length === 0 && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            No match. Names are searched among your own projects and points — this app has no online
            place lookup, so it can only find the zones your data names.
          </Typography>
        )}

        <Divider sx={{ my: 2 }}>
          <Typography variant="caption" color="text.secondary">
            {t('or by coordinates')}
          </Typography>
        </Divider>

        {/* ── by coordinates: one box each, never one box for both ────────── */}
        <Stack direction="row" spacing={1.5}>
          <TextField
            fullWidth
            label={t('Latitude')}
            placeholder="34.1067"
            value={latText}
            error={latBad}
            helperText={latBad ? 'Not a latitude (−90…90)' : ' '}
            onChange={(e) => setLatText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
            inputProps={{ inputMode: 'decimal', sx: { fontFamily: 'monospace' } }}
          />
          <TextField
            fullWidth
            label={t('Longitude')}
            placeholder="36.0172"
            value={lonText}
            error={lonBad}
            helperText={lonBad ? 'Not a longitude (−180…180)' : ' '}
            onChange={(e) => setLonText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
            inputProps={{ inputMode: 'decimal', sx: { fontFamily: 'monospace' } }}
          />
        </Stack>

        <Box>
          <Typography variant="caption" color="text.secondary">
            {coordinate !== null
              ? `Ready: ${coordinate.lat.toFixed(6)}, ${coordinate.lon.toFixed(6)}`
              : 'Decimal degrees (34.1067) or degrees/minutes/seconds (34°06\'24"N). Both boxes are needed.'}
          </Typography>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('Cancel')}</Button>
        <Button variant="contained" disabled={!canSubmit} onClick={submit}>
          Go
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default GoToLocationDialog;
