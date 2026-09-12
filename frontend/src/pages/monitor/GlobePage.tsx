/**
 * `pages/monitor/GlobePage.tsx` — `/monitor`: every registered camera on a globe.
 *
 * ★ THE ENTRY POINT OF THE MONITORING WORKSPACE, replacing the flat Live stream
 *   tab. A camera is a place before it is a picture: register it by coordinates,
 *   find it on the Earth, open it. Lazy — this page pulls in MapLibre, which the
 *   projects list must never download.
 *
 * ★ Keys: / search · F focus mode (hide the HUD) · ? shortcuts.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Dialog from '@mui/material/Dialog';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useProviders } from '../../api/hooks';
import { useMapStore } from '../../store';
import {
  selectCameras,
  selectLiveCount,
  selectLostCount,
  useCameraRegistryStore,
} from '../../store/cameraRegistryStore';
import { useMonitorLayoutStore } from '../../store/monitorLayoutStore';
import { CameraGridView } from '../../components/monitor/globe/CameraGridView';
import { CameraListPanel } from '../../components/monitor/globe/CameraListPanel';
import { GlobeHud } from '../../components/monitor/globe/GlobeHud';
import { GlobeMap } from '../../components/monitor/globe/GlobeMap';
import { PlaceSearch } from '../../components/monitor/globe/PlaceSearch';
import { OfflineCachePanel } from '../../components/map/OfflineCachePanel';
import { getLanguage } from '../../i18n';
import type { Place } from '../../lib/geo/gazetteer';
import { useCameraProbe } from '../../components/monitor/globe/useCameraProbe';
import { t } from '../../i18n';

const SHORTCUTS: ReadonlyArray<[string, string]> = [
  ['/', 'Search the camera list'],
  ['F', 'Focus mode — hide the HUD'],
  ['?', 'This sheet'],
];

export function GlobePage(): JSX.Element {
  const navigate = useNavigate();
  const cameras = useCameraRegistryStore(selectCameras);
  const statuses = useCameraRegistryStore((s) => s.statuses);
  const live = useCameraRegistryStore(selectLiveCount);
  const lost = useCameraRegistryStore(selectLostCount);
  const dropped = useCameraRegistryStore((s) => s.droppedOnLoad);
  const acknowledgeDropped = useCameraRegistryStore((s) => s.acknowledgeDropped);
  const hudOpen = useMonitorLayoutStore((s) => s.hudOpen);
  const setHudOpen = useMonitorLayoutStore((s) => s.setHudOpen);
  const focusMode = useMonitorLayoutStore((s) => s.focusMode);
  const setFocusMode = useMonitorLayoutStore((s) => s.setFocusMode);
  // ★ GRID | GLOBE (2026-09-02): the wall of live tiles, or the Earth. Persisted —
  //   an operator who watches the wall gets the wall tomorrow.
  const monitorView = useMonitorLayoutStore((s) => s.monitorView);
  const setMonitorView = useMonitorLayoutStore((s) => s.setMonitorView);

  // ★ THE SAME PROVIDER AS EVERY OTHER MAP: the persisted choice if usable, else
  //   the server default, else the first.
  const providersQuery = useProviders();
  const chosenProviderId = useMapStore((st) => st.providerId);
  const provider = useMemo(() => {
    const items = providersQuery.data?.items ?? [];
    const byChoice = chosenProviderId ? items.find((p) => p.name === chosenProviderId) : undefined;
    const usable =
      byChoice && byChoice.configured && byChoice.allowed !== false ? byChoice : undefined;
    return usable ?? items.find((p) => p.is_default) ?? items[0];
  }, [providersQuery.data, chosenProviderId]);

  const [hovered, setHovered] = useState<string | null>(null);
  useCameraProbe(hovered);

  const [helpOpen, setHelpOpen] = useState(false);
  const [flyTo, setFlyTo] = useState<{ id: string; seq: number } | null>(null);
  const searchEl = useRef<HTMLInputElement | null>(null);
  // ★ 2026-09-10: go to a searched place / typed coordinates; the borders-and-names
  //   toggle; the offline-cache tool (moved here from the dashboard map).
  const [goTo, setGoTo] = useState<{ lat: number; lon: number; zoom: number; seq: number } | null>(
    null,
  );
  const goToPlace = useCallback(
    (place: Place) =>
      setGoTo((g) => ({
        lat: place.lat,
        lon: place.lon,
        zoom: place.zoom,
        seq: (g?.seq ?? 0) + 1,
      })),
    [],
  );
  const placesVisible = useMonitorLayoutStore((st) => st.placesVisible);
  const setPlacesVisible = useMonitorLayoutStore((st) => st.setPlacesVisible);

  const open = useCallback((id: string) => navigate(`/monitor/cameras/${id}`), [navigate]);
  const fly = useCallback((id: string) => setFlyTo((f) => ({ id, seq: (f?.seq ?? 0) + 1 })), []);

  // ── keys ─────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const target = e.target as HTMLElement | null;
      const typing = target !== null && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (helpOpen) return;
      switch (e.key) {
        case '/':
          e.preventDefault();
          if (!hudOpen) setHudOpen(true);
          window.setTimeout(() => searchEl.current?.focus(), 0);
          break;
        case 'f':
        case 'F':
          e.preventDefault();
          setFocusMode(!focusMode);
          break;
        case '?':
          e.preventDefault();
          setHelpOpen(true);
          break;
        default:
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [helpOpen, hudOpen, focusMode, setHudOpen, setFocusMode]);

  // Focus mode is transient: leaving the page clears it.
  useEffect(() => () => setFocusMode(false), [setFocusMode]);

  return (
    <Box
      sx={{
        position: 'relative',
        // Fill what the shell gives — same fix as the camera page (2026-09-01):
        // a hardcoded dvh calc drifts at other display sizes.
        flex: 1,
        minHeight: 0,
        overflow: 'hidden',
      }}
    >
      {/* ★ Rendered once the providers query has ANSWERED — with a provider, or with
          none (the API down, every provider banned): the globe, the markers and the
          registry do not depend on imagery. The GRID view depends on neither. */}
      {monitorView === 'grid' ? (
        <Box sx={{ position: 'absolute', inset: 0, pt: '40px' }}>
          <Box sx={{ position: 'relative', height: '100%' }}>
            <CameraGridView cameras={cameras} onOpen={open} />
          </Box>
        </Box>
      ) : providersQuery.isSuccess || providersQuery.isError ? (
        <GlobeMap
          cameras={cameras}
          statuses={statuses}
          provider={provider ?? null}
          onHover={setHovered}
          onOpen={open}
          flyTo={flyTo}
          goTo={goTo}
          placesVisible={placesVisible}
          lang={getLanguage()}
        />
      ) : (
        <Box sx={{ position: 'absolute', inset: 0, bgcolor: 'var(--bg-canvas)' }} />
      )}

      {!focusMode && (
        <>
          <GlobeHud
            view={monitorView}
            onView={setMonitorView}
            cameras={cameras.length}
            live={live}
            lost={lost}
            provider={provider}
            hudOpen={hudOpen}
            onToggleHud={() => setHudOpen(!hudOpen)}
            onHelp={() => setHelpOpen(true)}
            search={
              monitorView === 'globe' ? (
                <PlaceSearch
                  onGo={goToPlace}
                  inputRef={(el) => {
                    searchEl.current = el;
                  }}
                />
              ) : null
            }
            tools={
              monitorView === 'globe' && provider !== undefined ? (
                <OfflineCachePanel
                  providerId={provider.name}
                  kind="satellite"
                  cacheable={provider.configured && provider.allowed !== false}
                  color="var(--accent)"
                />
              ) : null
            }
            placesVisible={placesVisible}
            onTogglePlaces={() => setPlacesVisible(!placesVisible)}
          />
          {monitorView === 'globe' && hudOpen && (
            <CameraListPanel cameras={cameras} statuses={statuses} onFly={fly} onOpen={open} />
          )}
          {dropped > 0 && (
            <Alert
              severity="warning"
              onClose={acknowledgeDropped}
              sx={{
                position: 'absolute',
                // Clears the attribution, which now sits in this corner.
                bottom: 40,
                insetInlineStart: 12,
                zIndex: 2,
                maxWidth: 480,
              }}
            >
              {dropped} {t('stored camera row(s) were unreadable and were dropped on load.')}
            </Alert>
          )}
        </>
      )}

      <Dialog open={helpOpen} onClose={() => setHelpOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('Monitor')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t(
              'Watch a camera on your network (Raspberry Pi MJPEG, IP camera, RTSP) or a local capture device — an HDMI capture card or a USB/USB-C camera plugged into this machine — and capture frames from it. Each captured frame lands in the capture library and becomes an ordinary photograph in any project.',
            )}
          </Typography>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {t('Keyboard shortcuts')}
          </Typography>
          <Stack spacing={0.75}>
            {SHORTCUTS.map(([key, what]) => (
              <Stack key={key} direction="row" spacing={1.5} alignItems="center">
                <Typography
                  variant="mono"
                  component="kbd"
                  sx={{
                    px: 0.75,
                    borderRadius: 1,
                    border: '1px solid var(--hairline-strong)',
                    minWidth: 28,
                    textAlign: 'center',
                    fontSize: 12,
                  }}
                >
                  {key}
                </Typography>
                <Typography variant="body2">{t(what)}</Typography>
              </Stack>
            ))}
          </Stack>
        </DialogContent>
      </Dialog>
    </Box>
  );
}

export default GlobePage;
