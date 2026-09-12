/**
 * `components/map/` barrel — IU-27 (fe-map).
 *
 * The mandated 2D satellite pane + manual GCP mode's map half (SCOPE.md §5). `MapPanel`
 * is the only component another pane/shell mounts; the rest are its children.
 */

export { MapPanel } from './MapPanel';
export type { MapPanelProps } from './MapPanel';

export { SatelliteMap } from './SatelliteMap';
export type { SatelliteMapProps, SatelliteMapCapabilities } from './SatelliteMap';
export { MapViewSync } from './MapViewSync';
export type { MapViewSyncProps } from './MapViewSync';
export { BasemapSwitcher } from './BasemapSwitcher';
export type { BasemapSwitcherProps } from './BasemapSwitcher';
export { ProviderAttribution } from './ProviderAttribution';
export type { ProviderAttributionProps } from './ProviderAttribution';
export { GcpMarkerLayer } from './GcpMarkerLayer';
export type { GcpMarkerLayerProps } from './GcpMarkerLayer';
export { GcpMarker } from './GcpMarker';
/** ★ The dashboard's cross-project overview map. */
export { GcpOverviewMap } from './GcpOverviewMap';
export type { GcpOverviewMapProps } from './GcpOverviewMap';
export type { GcpMarkerProps } from './GcpMarker';
export { FootprintLayer } from './FootprintLayer';
export type { FootprintLayerProps } from './FootprintLayer';
export { ConfidenceHeatmapLayer } from './ConfidenceHeatmapLayer';
export type { ConfidenceHeatmapLayerProps } from './ConfidenceHeatmapLayer';
export { LocationHintControl } from './LocationHintControl';
export type { LocationHintControlProps } from './LocationHintControl';
export { OfflineCacheLayer } from './OfflineCacheLayer';
export type { OfflineCacheLayerProps } from './OfflineCacheLayer';
export { OfflineCachePanel } from './OfflineCachePanel';
export type { OfflineCachePanelProps } from './OfflineCachePanel';

// ★ Manual GCP mode — added in the spirit of the tree (§2), flagged in the report.
export { CorrespondenceLayer } from './CorrespondenceLayer';
export type { CorrespondenceLayerProps } from './CorrespondenceLayer';
export { MapAccuracyReadout } from './MapAccuracyReadout';
export type { MapAccuracyReadoutProps } from './MapAccuracyReadout';

export {
  estimateClickAccuracy,
  metresPerPixel,
  proxyTileUrl,
  CLICK_PRECISION_PX,
  EARTH_RADIUS_M,
  EARTH_CIRCUMFERENCE_M,
} from './tileMath';
export type { ClickAccuracyEstimate } from './tileMath';
