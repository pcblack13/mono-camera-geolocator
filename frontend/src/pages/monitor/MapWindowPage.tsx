/**
 * `pages/monitor/MapWindowPage.tsx` — `/monitor/cameras/:id/map`: the satellite map
 * ALONE, in its own window, for the second screen.
 *
 * ★ NO SHELL. This route sits beside the app layout, not inside it: a popped-out
 *   map wants the map, a one-line header and nothing else. It is the monitor
 *   page's `MapDeck` fed by the monitor page over a `BroadcastChannel`
 *   (`lib/monitor/mapWindow.ts`): which run, which table, which mark is selected.
 *
 * ★ IT POLLS THE RUN ITSELF, READ-ONLY. It never touches `useLiveDetection` —
 *   that hook STOPS the run it owns when its page unmounts, and closing a map
 *   window must never end the operator's detection. A plain query on the public
 *   session endpoint, and marks accumulated through the same `since` cursor the
 *   page uses, give it the same picture without any ownership.
 */

import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';

import { detectionApi, type DetectionMark } from '../../api/detection';
import { installDisplayZoomShortcuts } from '../../lib/displayZoom';
import { useProviders } from '../../api/hooks';
import { lutApi } from '../../api/lut';
import { qk } from '../../api/queryKeys';
import {
  isMapWindowMessage,
  openMapChannel,
  type MapWindowStateMessage,
} from '../../lib/monitor/mapWindow';
import { useMapStore } from '../../store';
import { selectCameraById, useCameraRegistryStore } from '../../store/cameraRegistryStore';
import { MapDeck } from '../../components/monitor/camera/MapDeck';
import { t } from '../../i18n';

/** The run's marks, appended from the `since` cursor — never re-downloaded. */
function useSessionMarks(sessionId: string | null, total: number | undefined): DetectionMark[] {
  const [marks, setMarks] = useState<DetectionMark[]>([]);
  const cursor = useRef(0);
  useEffect(() => {
    cursor.current = 0;
    setMarks([]);
  }, [sessionId]);
  useEffect(() => {
    if (sessionId === null || total === undefined || total <= cursor.current) return undefined;
    let cancelled = false;
    void detectionApi
      .marks(sessionId, cursor.current)
      .then((batch) => {
        if (cancelled) return;
        cursor.current = batch.next_index;
        if (batch.marks.length > 0) setMarks((old) => [...old, ...batch.marks]);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [sessionId, total]);
  return marks;
}

export function MapWindowPage(): JSX.Element {
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const camera = useCameraRegistryStore(selectCameraById(id));

  // ★ The URL seeds the state; the channel keeps it current.
  const [state, setState] = useState<Omit<MapWindowStateMessage, 'type'>>({
    session: params.get('session'),
    lut: params.get('lut') ?? '',
    selectedIndex: null,
  });
  // No shell here, so the display-size keys are installed by the page itself.
  useEffect(() => installDisplayZoomShortcuts(), []);
  const channel = useRef<BroadcastChannel | null>(null);
  useEffect(() => {
    const ch = openMapChannel(id);
    channel.current = ch;
    if (ch === null) return undefined;
    ch.onmessage = (e: MessageEvent) => {
      const m: unknown = e.data;
      if (!isMapWindowMessage(m) || m.type !== 'state') return;
      setState({ session: m.session, lut: m.lut, selectedIndex: m.selectedIndex });
    };
    ch.postMessage({ type: 'hello' });
    const bye = (): void => ch.postMessage({ type: 'closed' });
    window.addEventListener('pagehide', bye);
    return () => {
      window.removeEventListener('pagehide', bye);
      ch.close();
      channel.current = null;
    };
  }, [id]);

  const session = useQuery({
    queryKey: ['detection', 'session', state.session],
    queryFn: ({ signal }) => detectionApi.get(state.session!, signal),
    enabled: state.session !== null,
    refetchInterval: 1000,
    retry: false,
  });
  const marks = useSessionMarks(state.session, session.data?.marks_total);

  const lutLibrary = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
    staleTime: 30_000,
  });
  const center = useMemo((): [number, number] | null => {
    const fromRun = session.data?.lut_summary?.center;
    if (Array.isArray(fromRun) && fromRun.length === 2)
      return [Number(fromRun[0]), Number(fromRun[1])];
    const entry = (lutLibrary.data ?? []).find((e) => e.site_name === state.lut);
    const c = entry?.center;
    return Array.isArray(c) && c.length === 2 ? [Number(c[0]), Number(c[1])] : null;
  }, [session.data?.lut_summary?.center, lutLibrary.data, state.lut]);

  const providersQuery = useProviders();
  const chosenProviderId = useMapStore((st) => st.providerId);
  const provider = useMemo(() => {
    const items = providersQuery.data?.items ?? [];
    const byChoice = chosenProviderId ? items.find((p) => p.name === chosenProviderId) : undefined;
    const usable =
      byChoice && byChoice.configured && byChoice.allowed !== false ? byChoice : undefined;
    return usable ?? items.find((p) => p.is_default) ?? items[0];
  }, [providersQuery.data, chosenProviderId]);

  const running =
    session.data !== undefined &&
    (session.data.status === 'starting' || session.data.status === 'running');

  return (
    <Box
      sx={{
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'background.default',
        color: 'text.primary',
      }}
    >
      <Stack
        direction="row"
        alignItems="center"
        spacing={1}
        sx={{ height: 44, px: 1.5, flexShrink: 0, borderBottom: '1px solid var(--hairline)' }}
      >
        <MapOutlinedIcon fontSize="small" sx={{ color: 'var(--accent)' }} />
        <Typography variant="subtitle2" noWrap sx={{ minWidth: 0 }}>
          {t('Satellite map')}
          {camera !== undefined && ` · ${camera.name}`}
        </Typography>
        <Typography variant="caption" color="text.secondary" noWrap sx={{ flex: 1, minWidth: 0 }}>
          {state.session === null
            ? t('No run yet — marks appear here the moment detection starts.')
            : running
              ? `${t('detecting')} · ${marks.length} ${t('marks')}`
              : `${marks.length} ${t('marks')}`}
        </Typography>
        {/* ★ The selection is SAID, not only drawn: a canvas marker cannot be
            read by anyone but the eye, and the two windows must agree on it. */}
        {state.selectedIndex !== null && marks[state.selectedIndex] !== undefined && (
          <Typography
            variant="caption"
            className="le-mono"
            data-testid="map-window-selected"
            sx={{ color: 'var(--accent)', whiteSpace: 'nowrap' }}
          >
            {t('selected')} #{state.selectedIndex + 1}
            {marks[state.selectedIndex].track_id !== null &&
              ` · ${t('track')} ${marks[state.selectedIndex].track_id}`}
          </Typography>
        )}
        <Button
          size="small"
          color="inherit"
          startIcon={<CloseRoundedIcon fontSize="small" />}
          onClick={() => window.close()}
          sx={{ textTransform: 'none', whiteSpace: 'nowrap' }}
        >
          {t('Back to the monitor')}
        </Button>
      </Stack>
      <Box sx={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <MapDeck
          marks={marks}
          center={center}
          provider={provider}
          lutSite={state.lut}
          selectedIndex={state.selectedIndex}
          onSelect={(index) => {
            setState((s) => ({ ...s, selectedIndex: index }));
            channel.current?.postMessage({ type: 'select', index });
          }}
          driftVerdict={null}
        />
      </Box>
    </Box>
  );
}

export default MapWindowPage;
