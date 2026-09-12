/**
 * `monitor/globe/PlaceSearch.tsx` — type a place or a coordinate pair, go there.
 *
 * ★ THREE ANSWERS, IN ORDER (owner ask 2026-09-10). Typed coordinates are parsed
 *   here and offered first — no lookup, no network. Then the app's own gazetteer
 *   (countries, provinces, major cities, continents, regions — shipped with the
 *   app, works offline). Only when those find nothing, and the text is three
 *   characters or more, the server's geocoder is asked, debounced, and its
 *   answers are marked as online so the operator knows which answers survive
 *   a cut cable.
 */

import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
import Autocomplete from '@mui/material/Autocomplete';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import InputAdornment from '@mui/material/InputAdornment';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import SearchIcon from '@mui/icons-material/Search';
import PublicOutlinedIcon from '@mui/icons-material/PublicOutlined';
import FlagOutlinedIcon from '@mui/icons-material/FlagOutlined';
import LocationCityOutlinedIcon from '@mui/icons-material/LocationCityOutlined';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';
import MyLocationIcon from '@mui/icons-material/MyLocation';
import CloudOutlinedIcon from '@mui/icons-material/CloudOutlined';

import { providersApi } from '../../../api/providers';
import { coordinatesPlace, loadGazetteer, searchPlaces, type Place, type PlaceKind } from '../../../lib/geo/gazetteer';
import { t } from '../../../i18n';

export interface PlaceSearchProps {
  onGo: (place: Place) => void;
  /** The input, for the page's `/` shortcut. */
  inputRef?: (el: HTMLInputElement | null) => void;
}

const KIND_WORD: Record<PlaceKind, string> = {
  continent: 'Continent',
  region: 'Region',
  country: 'Country',
  province: 'Province',
  city: 'City',
  coordinates: 'Coordinates',
  online: 'Online result',
};

function KindIcon({ kind }: { kind: PlaceKind }): JSX.Element {
  const sx = { fontSize: 16, color: 'var(--text-tertiary)' };
  switch (kind) {
    case 'continent':
    case 'region':
      return <PublicOutlinedIcon sx={sx} />;
    case 'country':
      return <FlagOutlinedIcon sx={sx} />;
    case 'province':
      return <MapOutlinedIcon sx={sx} />;
    case 'city':
      return <LocationCityOutlinedIcon sx={sx} />;
    case 'coordinates':
      return <MyLocationIcon sx={sx} />;
    default:
      return <CloudOutlinedIcon sx={sx} />;
  }
}

const ONLINE_DEBOUNCE_MS = 450;

export function PlaceSearch({ onGo, inputRef }: PlaceSearchProps): JSX.Element {
  const [input, setInput] = useState('');
  const [gazetteer, setGazetteer] = useState<Place[] | null>(null);
  const [online, setOnline] = useState<Place[]>([]);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  // The gazetteer loads on the first keystroke — a page that is never searched
  // never pays for it.
  useEffect(() => {
    if (input === '' || gazetteer !== null) return;
    let alive = true;
    loadGazetteer()
      .then((g) => {
        if (alive) setGazetteer(g);
      })
      .catch(() => undefined); // the coordinate parser and the geocoder still work
    return () => {
      alive = false;
    };
  }, [input, gazetteer]);

  const local = useMemo((): Place[] => {
    const coords = coordinatesPlace(input);
    const hits = gazetteer === null ? [] : searchPlaces(gazetteer, input, 8);
    return coords === null ? hits : [coords, ...hits];
  }, [input, gazetteer]);

  // ★ The geocoder is the LAST resort: only when nothing local answers.
  useEffect(() => {
    const q = input.trim();
    const mySeq = ++seq.current;
    if (q.length < 3 || local.length > 0) {
      setOnline([]);
      setBusy(false);
      return undefined;
    }
    setBusy(true);
    const timer = window.setTimeout(() => {
      providersApi
        .geocode(q, 6)
        .then((rows) => {
          if (mySeq !== seq.current) return;
          setOnline(
            rows.map((r) => ({
              kind: 'online' as const,
              name: r.display_name,
              context: r.category,
              lat: r.lat,
              lon: r.lon,
              zoom: 12,
              pop: 0,
            })),
          );
        })
        .catch(() => {
          if (mySeq === seq.current) setOnline([]);
        })
        .finally(() => {
          if (mySeq === seq.current) setBusy(false);
        });
    }, ONLINE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [input, local]);

  const options = local.length > 0 ? local : online;

  return (
    <Autocomplete<Place, false, false, true>
      freeSolo
      size="small"
      options={options}
      filterOptions={(x) => x}
      inputValue={input}
      onInputChange={(_e, v) => setInput(v)}
      value={null}
      onChange={(_e, v) => {
        if (v === null) return;
        // Enter on plain text: the first suggestion, or the typed coordinates.
        const place = typeof v === 'string' ? (options[0] ?? coordinatesPlace(v)) : v;
        if (place) {
          onGo(place);
          setInput('');
        }
      }}
      getOptionLabel={(o) => (typeof o === 'string' ? o : o.name)}
      isOptionEqualToValue={(a, b) => a.name === b.name && a.lat === b.lat && a.lon === b.lon}
      noOptionsText={busy ? t('Searching online…') : t('No place found')}
      loading={busy}
      sx={{ width: { xs: 220, md: 320 } }}
      renderOption={(props, o) => (
        <Box component="li" {...props} key={`${o.kind}:${o.name}:${o.lat}:${o.lon}`} sx={{ gap: 1 }}>
          <KindIcon kind={o.kind} />
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="body2" noWrap>
              {o.name}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
              {t(KIND_WORD[o.kind])}
              {o.context ? ` · ${o.context}` : ''}
            </Typography>
          </Box>
        </Box>
      )}
      renderInput={(params) => (
        <TextField
          {...params}
          inputRef={inputRef}
          placeholder={t('City, country, region — or lat, lon')}
          inputProps={{ ...params.inputProps, 'aria-label': t('Search places or coordinates') }}
          InputProps={{
            ...params.InputProps,
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon sx={{ fontSize: 18, color: 'var(--text-tertiary)' }} />
              </InputAdornment>
            ),
            endAdornment: (
              <>
                {busy ? <CircularProgress size={14} /> : null}
                {params.InputProps.endAdornment}
              </>
            ),
            sx: { height: 30, fontSize: 13, bgcolor: 'var(--bg-elevated)' },
          }}
        />
      )}
    />
  );
}

export default PlaceSearch;
