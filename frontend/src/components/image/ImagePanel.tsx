/**
 * `image/ImagePanel.tsx` — the left pane container. 50-frontend.md §2.8.
 *
 * Runs `useImage(imageId)`, chooses the display variant, loads its bitmap, and hands
 * the viewer everything it needs. Owns the loading / error / empty states, the
 * fullscreen element, and the wiring of the viewer controls to `viewerStore`.
 *
 * ★★ THE VARIANT DECISION IS PRESENTATION-ONLY (§5.1/§5.3). Which raster the browser
 *    draws never touches a stored coordinate: `viewerStore.setImageSource(natural, D)`
 *    carries the ORIGINAL dimensions and the variant's `display_scale`, and every
 *    coordinate stays in ORIGINAL image space. Swapping a variant only changes `D`.
 *
 * ★ Hydrates `annotationStore` from the server's latest annotations when the draft is
 *   not already for this image — idempotent, so it is harmless if the workspace shell
 *   hydrated first (it guards on `draft.image_id`).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import Tooltip from '@mui/material/Tooltip';
import { useTheme } from '@mui/material/styles';
import ImageNotSupportedIcon from '@mui/icons-material/ImageNotSupported';
import AddLocationAltIcon from '@mui/icons-material/AddLocationAlt';
import MyLocationIcon from '@mui/icons-material/MyLocation';
import Button from '@mui/material/Button';

import type { Uuid } from '../../types/common';
import type { GcpRead, GcpSummary } from '../../types/gcp';
import type { ImageVariant } from '../../types/image';
import { useImage } from '../../api/hooks/useImages';
import { useAnnotations } from '../../api/hooks/useAnnotations';
import { AutoGcpControl, AUTO_GCP_REQUIRED } from '../gcp/AutoGcpControl';
import { LivePredictController } from './LivePredictController';
import { useImageCamera } from '../../api/hooks/useImageCamera';
import { usePredictionStore } from '../../store/predictionStore';
import { useAutosaveAnnotations } from '../../api/hooks/useAutosaveAnnotations';
import { useGcps } from '../../api/hooks/useGcps';
import { useQueryClient } from '@tanstack/react-query';
import { qk } from '../../api/queryKeys';
import { useAnnotationStore } from '../../store/annotationStore';
import { useSelectionStore } from '../../store/selectionStore';
import { useCorrespondenceStore } from '../../store/correspondenceStore';
import { useViewerStore } from '../../store/viewerStore';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { ImageViewer } from './ImageViewer';
import { ToolRail } from '../annotation/ToolRail';
import { useAccuracyState } from '../../api/hooks/useAccuracy';
import { ViewerControls } from './ViewerControls';
import { ZoneLegend } from './ZoneLegend';
import { ImageStatusBar } from './ImageStatusBar';
import { RescaleImageDialog } from './RescaleImageDialog';
import { t } from '../../i18n';

export interface ImagePanelProps {
  imageId: Uuid;
}

/** Prefer the mid-resolution variant; it is the right trade-off on cellular (§5.1). */
function chooseVariant(variants: ImageVariant[]): ImageVariant | null {
  const by = (n: ImageVariant['name']): ImageVariant | undefined =>
    variants.find((v) => v.name === n);
  return by('preview') ?? by('full') ?? by('original') ?? by('thumbnail') ?? variants[0] ?? null;
}

/** Project a `GcpRead` down to the summary the canvas needs for confidence colouring. */
function toSummary(g: GcpRead): GcpSummary {
  return {
    id: g.id,
    image_id: g.image_id,
    code: g.code,
    image_px: g.image_px,
    lat: g.lat,
    lon: g.lon,
    source: g.source,
    confidence: g.confidence,
    declared_confidence: g.declared_confidence,
    total_ce90_m: g.accuracy.total_ce90_m,
    manually_adjusted: g.manually_adjusted,
    is_stale: g.is_stale,
    is_included_in_export: g.is_included_in_export,
  };
}

export function ImagePanel({ imageId }: ImagePanelProps): JSX.Element {
  const queryClient = useQueryClient();
  const theme = useTheme();
  const rootRef = useRef<HTMLDivElement>(null);

  const imageQuery = useImage(imageId);
  const annotationsQuery = useAnnotations(imageId);
  const gcpsQuery = useGcps(imageId);

  const image = imageQuery.data;

  // ── where the next control point should go ───────────────────────────────────
  // ★ THE ADVICE BELONGS WHERE THE CLICK HAPPENS. The accuracy check ranks regions,
  //   but the surveyor places points HERE — so the boxes are drawn on this canvas, and
  //   are shown as soon as a suggestion run finishes. They are guidance, not a
  //   constraint, so they can be switched off from the viewer controls.
  const accuracyQuery = useAccuracyState(imageId);
  const suggestions = accuracyQuery.data?.suggestions?.regions ?? [];
  const [showSuggestions, setShowSuggestions] = useState(true);
  const suggestionLimit = useWorkspaceStore((s) => s.suggestionLimit);
  // How the marks are drawn — the surveyor's own choices (Workspace preferences).
  const suggestionColor = useWorkspaceStore((s) => s.suggestionColor);
  const photoMarkColor = useWorkspaceStore((s) => s.photoMarkColor);
  const pointColors = useWorkspaceStore((s) => s.pointColors);
  const setSuggestionLimit = useWorkspaceStore((s) => s.setSuggestionLimit);
  const shownSuggestions = showSuggestions ? suggestions : [];
  // ── the nine range zones ──────────────────────────────────────────────────────
  // ★ THE VERDICT WHERE THE SURVEYOR IS LOOKING. The measurement's tiles live on
  //   the satellite pane; the zones put the same numbers on the frame itself, so
  //   "is the far left trustworthy?" is answered without switching panes.
  const zones = accuracyQuery.data?.measurement?.zones ?? null;
  const zoneOverlay = useWorkspaceStore((s) => s.zoneOverlay);
  const zoneOpacity = useWorkspaceStore((s) => s.zoneOpacity);
  const setZoneOverlay = useWorkspaceStore((s) => s.setZoneOverlay);
  const setZoneOpacity = useWorkspaceStore((s) => s.setZoneOpacity);
  const shownZones = zoneOverlay ? zones : null;

  // ★ Opening a correspondence from the photo header. `open()` is the same store action
  //   the removed side panel called, so the flow downstream is byte-for-byte unchanged:
  //   the inspector still appears for the map click, the confidence and the commit.
  const openCorrespondence = useCorrespondenceStore((s) => s.open);
  const correspondenceOpen = useCorrespondenceStore((s) => s.status !== 'idle');
  const startCorrespondence = (): void => openCorrespondence({ image_id: imageId });

  // ── live cursor prediction (1.2.6) ───────────────────────────────────────────
  // ★ The same solver the auto-GCP commit uses, run on HOVER: move the cursor over the
  //   photo and the map shows where that pixel lands — without opening or committing a
  //   correspondence. Only offered once the camera is solvable (Auto on + 4 points),
  //   because that is exactly when the estimate endpoint can answer.
  const cameraQuery = useImageCamera(imageId);
  const gcpTotal = gcpsQuery.data?.total ?? gcpsQuery.data?.items.length ?? 0;
  const autoReady = cameraQuery.data?.auto_gcp_enabled === true && gcpTotal >= AUTO_GCP_REQUIRED;
  const predictActive = usePredictionStore((s) => s.active);
  const setPredictActive = usePredictionStore((s) => s.setActive);
  // The live ghost and an open correspondence must not compete — close the ghost the
  // moment a New GCP correspondence opens.
  useEffect(() => {
    if (correspondenceOpen && predictActive) setPredictActive(false);
  }, [correspondenceOpen, predictActive, setPredictActive]);
  // No prediction (or its toggle) survives a move to another photo.
  useEffect(() => () => usePredictionStore.getState().reset(), [imageId]);

  // ★ Persist the landmark draft to the server (debounced). Without this, marks on the
  //   photo live only in the browser and vanish on reload. See useAutosaveAnnotations.
  useAutosaveAnnotations(imageId, image?.project_id);
  const variant = useMemo(() => (image ? chooseVariant(image.variants) : null), [image]);

  // ── viewer store wiring ──────────────────────────────────────────────────────
  const transform = useViewerStore((s) => s.transform);
  const minScale = useViewerStore((s) => s.minScale);
  const maxScale = useViewerStore((s) => s.maxScale);
  const naturalSize = useViewerStore((s) => s.naturalSize);
  const viewport = useViewerStore((s) => s.viewport);
  const adjustments = useViewerStore((s) => s.adjustments);
  const isFullscreen = useViewerStore((s) => s.isFullscreen);
  const setImageSource = useViewerStore((s) => s.setImageSource);
  const setAdjustment = useViewerStore((s) => s.setAdjustment);
  const resetAdjustments = useViewerStore((s) => s.resetAdjustments);
  const setFullscreen = useViewerStore((s) => s.setFullscreen);
  const fitToView = useViewerStore((s) => s.fitToView);
  const zoomToActualSize = useViewerStore((s) => s.zoomToActualSize);
  const zoomAt = useViewerStore((s) => s.zoomAt);
  const reset = useViewerStore((s) => s.reset);

  // ── annotation hydration (idempotent) ────────────────────────────────────────
  const draftImageId = useAnnotationStore((s) => s.draft.image_id);
  const hydrate = useAnnotationStore((s) => s.hydrate);
  useEffect(() => {
    if (draftImageId === imageId) return;
    const data = annotationsQuery.data;
    if (!data) return;
    const items = data.items;
    const baseSeq = items.length ? items.reduce((m, a) => Math.max(m, a.revision_seq), 0) : null;
    hydrate(imageId, items, baseSeq);
  }, [imageId, draftImageId, annotationsQuery.data, hydrate]);

  // ── bitmap loading + variant swap ────────────────────────────────────────────
  const [bitmap, setBitmap] = useState<HTMLImageElement | null>(null);
  const [loadError, setLoadError] = useState(false);

  // ★ A new photograph starts blank: B must not show A stretched to B's size,
  //   nor A's load error.
  useEffect(() => {
    setBitmap(null);
    setLoadError(false);
  }, [imageId]);

  // ── change-resolution dialog ──────────────────────────────────────────────────
  const [rescaleOpen, setRescaleOpen] = useState(false);
  const variantUrl = variant?.url ?? null;

  useEffect(() => {
    if (!variant || !variantUrl) return;
    let cancelled = false;
    const img = new Image();
    // crossOrigin lets the loupe/magnifier read the layer canvas without tainting it.
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      if (cancelled) return;
      setBitmap(img);
      setLoadError(false);
      // ★ Atomic with the bitmap swap: no frame renders with a mismatched s/D (§5.3).
      setImageSource(
        { width: variant.original_width, height: variant.original_height },
        variant.display_scale,
      );
    };
    img.onerror = () => {
      if (!cancelled) setLoadError(true);
    };
    img.src = variantUrl;
    return () => {
      cancelled = true;
    };
  }, [variant, variantUrl, setImageSource]);

  // Reset the viewer transform when leaving the image entirely.
  useEffect(() => () => reset(), [imageId, reset]);

  // ── maximise ──────────────────────────────────────────────────────────────────
  // ★ A CSS maximise (the pane grows to cover the viewport), NOT the browser Fullscreen
  //   API: `requestFullscreen` renders MUI overlays — the Change-resolution DIALOG, tooltips,
  //   selects — into `document.body`, which the browser hides behind the fullscreen element,
  //   so a maximised photo would lose exactly the rescale/drawing controls this is meant to
  //   surface. A high-z fixed element keeps every portal working.
  useEffect(() => {
    if (!isFullscreen) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setFullscreen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isFullscreen, setFullscreen]);

  const toggleFullscreen = useCallback(
    () => setFullscreen(!isFullscreen),
    [isFullscreen, setFullscreen],
  );

  const center = useMemo(
    () => ({ x: viewport.width / 2, y: viewport.height / 2 }),
    [viewport.width, viewport.height],
  );
  const onZoomIn = useCallback(() => zoomAt(center, 1.25), [zoomAt, center]);
  const onZoomOut = useCallback(() => zoomAt(center, 1 / 1.25), [zoomAt, center]);

  const gcps = useMemo<GcpSummary[]>(
    () => (gcpsQuery.data?.items ?? []).map(toSummary),
    [gcpsQuery.data],
  );

  // ★ Cross-pane REVEAL on the photo: when a GCP (from the table/map) or its landmark is
  //   selected somewhere other than the photo itself, centre the viewer on its pixel so the
  //   surveyor is taken to the point they clicked. Prefers the linked landmark's pixel; falls
  //   back to the GCP's own image pixel when there is no landmark. Gated on focusOrigin so a
  //   click IN the photo never yanks the photo.
  const selectedRefs = useSelectionStore((s) => s.selected);
  const selectionFocus = useSelectionStore((s) => s.focusOrigin);
  const zoomToImageRect = useViewerStore((s) => s.zoomToImageRect);
  const draftAnnotations = useAnnotationStore((s) => s.draft.annotations);
  useEffect(() => {
    if (selectionFocus === 'image' || selectedRefs.length === 0 || !naturalSize) return;
    const ref = selectedRefs[selectedRefs.length - 1];
    if (!ref) return;
    let px: number | null = null;
    let py: number | null = null;
    const ann = draftAnnotations.find((a) => a.id === ref.id || a.id === ref.linkedId);
    if (ann) {
      px = ann.pixel_x;
      py = ann.pixel_y;
    } else if (ref.kind === 'gcp') {
      const g = gcps.find((x) => x.id === ref.id);
      if (g?.image_px) {
        px = g.image_px.x;
        py = g.image_px.y;
      }
    }
    if (px === null || py === null) return;
    const span = Math.max(naturalSize.width, naturalSize.height) * 0.3;
    zoomToImageRect({ x: px - span / 2, y: py - span / 2, width: span, height: span });
  }, [selectedRefs, selectionFocus, draftAnnotations, gcps, naturalSize, zoomToImageRect]);

  const correspondenceColor = theme.palette.primary.main;

  // ── render ────────────────────────────────────────────────────────────────────
  const loading = imageQuery.isLoading || (!bitmap && !loadError);
  const failed = imageQuery.isError || loadError;

  return (
    <Box
      ref={rootRef}
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minWidth: 0,
        bgcolor: 'surfaces.canvasBackdrop',
        // ★ Maximised: cover the viewport as a fixed, high-z pane. zIndex sits BELOW MUI's
        //   modal layer (1300) so the Change-resolution dialog and tooltips render on top.
        ...(isFullscreen
          ? { position: 'fixed', inset: 0, zIndex: 1200, height: '100vh', width: '100vw' }
          : {}),
      }}
    >
      {/* Compact header (the workspace supplies PaneHeader; this is the pane-local strip). */}
      <Stack
        direction="row"
        spacing={1}
        alignItems="center"
        sx={{
          px: 1.5,
          py: 0.75,
          bgcolor: 'background.paper',
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Typography variant="subtitle2" noWrap sx={{ maxWidth: '55%' }} title={image?.filename}>
          {image?.filename ?? 'Image'}
        </Typography>
        {image && (
          <Typography variant="mono" sx={{ fontSize: 11, color: 'text.secondary' }}>
            {image.width}×{image.height}
          </Typography>
        )}
        {image?.is_geotiff && (
          <Chip
            size="small"
            label="GeoTIFF"
            color="success"
            variant="outlined"
            sx={{ height: 20 }}
          />
        )}
        <Box sx={{ flexGrow: 1 }} />
        {/* ★ Starting a correspondence lives HERE, beside the resolution control, rather
            than in a standing panel of its own. It is an action on the photograph — the
            same class of thing as changing its resolution — and giving it a permanent
            side panel cost a whole column of the workspace to hold one button. */}
        {/* ★ The picking MODE sits beside the action it governs: choose Manual or
            Auto here, then press New GCP — one glance covers both decisions. */}
        {image && (
          <AutoGcpControl
            imageId={imageId}
            gcpCount={gcpsQuery.data?.total ?? gcpsQuery.data?.items.length ?? 0}
          />
        )}
        {/* ★ LIVE PREDICT (1.2.6): a look-only preview beside the commit action. Enabled
            only when the camera is solvable; disabled with the reason otherwise. */}
        {image && (
          <Tooltip
            title={
              cameraQuery.data?.auto_gcp_enabled !== true
                ? 'Turn on Auto GCP to preview where the photo cursor lands on the map.'
                : gcpTotal < AUTO_GCP_REQUIRED
                  ? `Locate ${AUTO_GCP_REQUIRED} points first — ${gcpTotal}/${AUTO_GCP_REQUIRED} placed.`
                  : correspondenceOpen
                    ? 'Finish or cancel the open GCP to use live predict.'
                    : 'Move the cursor over the photo to preview its map position — nothing is committed.'
            }
          >
            <span>
              <Button
                size="small"
                variant={predictActive ? 'contained' : 'outlined'}
                startIcon={<MyLocationIcon fontSize="small" />}
                onClick={() => setPredictActive(!predictActive)}
                disabled={!autoReady || correspondenceOpen}
                aria-pressed={predictActive}
                sx={{ whiteSpace: 'nowrap' }}
              >
                {predictActive ? t('Predicting…') : t('Live predict')}
              </Button>
            </span>
          </Tooltip>
        )}
        {image && (
          // ★ ONE NAME (owner report 2026-09-10). The button used to relabel itself
          //   "Correspondence open" while a correspondence was in progress, and the
          //   longer text spilled past the button's edges. The name stays; the state
          //   is the disabled button and its tooltip.
          <Tooltip
            title={
              correspondenceOpen
                ? t('A correspondence is open — place it or cancel it first.')
                : t('Start a new ground control point: a photo click, then a map click.')
            }
          >
            <span>
              <Button
                size="small"
                variant="outlined"
                startIcon={<AddLocationAltIcon fontSize="small" />}
                onClick={startCorrespondence}
                disabled={correspondenceOpen}
                sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}
              >
                {t('New GCP')}
              </Button>
            </span>
          </Tooltip>
        )}
      </Stack>
      {image && <LivePredictController imageId={imageId} />}

      <Box sx={{ position: 'relative', flex: 1, minHeight: 0 }}>
        {failed ? (
          <Stack
            sx={{ position: 'absolute', inset: 0 }}
            alignItems="center"
            justifyContent="center"
            spacing={1}
          >
            <ImageNotSupportedIcon color="disabled" fontSize="large" />
            <Typography variant="body2" color="text.secondary">
              {t('This image could not be loaded.')}
            </Typography>
          </Stack>
        ) : bitmap && variant ? (
          <ImageViewer
            image={bitmap}
            displayWidth={variant.width}
            displayHeight={variant.height}
            gcps={gcps}
            correspondenceColor={correspondenceColor}
            suggestionColor={suggestionColor}
            photoColor={photoMarkColor}
            pointColors={pointColors}
            suggestions={shownSuggestions}
            zones={shownZones}
            zoneOpacity={zoneOpacity}
          />
        ) : null}
        {shownZones && bitmap && <ZoneLegend range={shownZones.range_m} />}

        {loading && !failed && (
          <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}>
            <CircularProgress size={28} />
          </Box>
        )}

        {/* ★ When the photo is MAXIMISED (fullscreen), the workspace's tool rail is outside
            the fullscreen element and so invisible. Float a live copy on the photo itself so
            pointing/drawing stays available — it reads the same stores, so it is in lock-step
            with the docked rail. Rescale + zoom live in the header/footer, already inside. */}
        {/* ★ Only while a GCP correspondence is open (1.2.6) — same rule as the
            docked rail: undo/redo/delete belong to the mark-editing stage. */}
        {isFullscreen && !failed && correspondenceOpen ? (
          <Box
            sx={{
              position: 'absolute',
              top: 8,
              left: 8,
              zIndex: 5,
              bgcolor: 'background.paper',
              borderRadius: 1,
              boxShadow: 3,
              p: 0.5,
            }}
          >
            <ToolRail orientation="vertical" />
          </Box>
        ) : null}
      </Box>

      <ViewerControls
        scale={transform.scale}
        minScale={minScale}
        maxScale={maxScale}
        onZoomIn={onZoomIn}
        onZoomOut={onZoomOut}
        onFit={fitToView}
        onActualSize={zoomToActualSize}
        onToggleFullscreen={toggleFullscreen}
        isFullscreen={isFullscreen}
        brightness={adjustments.brightness}
        contrast={adjustments.contrast}
        onBrightnessChange={(v) => setAdjustment('brightness', v)}
        onContrastChange={(v) => setAdjustment('contrast', v)}
        onResetAdjustments={resetAdjustments}
        onRescale={image ? () => setRescaleOpen(true) : undefined}
        suggestionCount={suggestions.length}
        showSuggestions={showSuggestions}
        onToggleSuggestions={() => setShowSuggestions((v) => !v)}
        suggestionLimit={suggestionLimit}
        onSuggestionLimitChange={setSuggestionLimit}
        hasZones={zones !== null}
        showZones={zoneOverlay}
        onToggleZones={() => setZoneOverlay(!zoneOverlay)}
        zoneOpacity={zoneOpacity}
        onZoneOpacityChange={setZoneOpacity}
        zoneRange={zones?.range_m ?? null}
      />
      <ImageStatusBar
        scale={transform.scale}
        naturalSize={naturalSize}
        hasGps={image?.gps != null}
        adjusted={adjustments.brightness !== 0 || adjustments.contrast !== 0}
      />

      {image && (
        <RescaleImageDialog
          open={rescaleOpen}
          imageId={imageId}
          filename={image.filename}
          currentWidth={image.width}
          currentHeight={image.height}
          onClose={() => setRescaleOpen(false)}
          // ★ The server scaled every annotation's pixels; the local draft still holds
          //   the old space and autosave would push it straight back (undoing the
          //   rescale). Refetch, THEN drop the draft + undo stack so hydration re-runs
          //   from the scaled set — order matters, or hydrate would re-read the stale cache.
          onRescaled={() => {
            void queryClient
              .refetchQueries({ queryKey: qk.annotations.forImage(imageId) })
              .then(() => useAnnotationStore.getState().reset());
          }}
        />
      )}
    </Box>
  );
}
