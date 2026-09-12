/**
 * The domain model barrel — `src/types/` (§8.2), owned by IU-23.
 *
 * ★ THE CASING LAW (§8.1 / L9): every wire field in this directory is snake_case and
 *   mirrors its Pydantic counterpart (§6) field for field. There is no
 *   case-mapping layer anywhere in the frontend, and `.eslintrc.cjs` disables
 *   `camelcase` for `src/types/**` and `src/api/**` for exactly this reason.
 *
 * ★ SCOPE.md: the automatic matching engine is DEFERRED. `match.ts`, `pose.ts`,
 *   `heatmap.ts`, `semantic.ts` and `suggestion.ts` are complete and honest — the
 *   seam must be real, not decorative (SCOPE.md §4 rule 1) — but their endpoints
 *   return `501` with a `feature: "deferred"` marker in this build. Every GCP this
 *   build produces carries `source: 'manual'` and a surveyor-declared
 *   `declared_confidence` (SCOPE.md §5).
 *
 * Re-exported as types only (`export type`) so this barrel erases completely at
 * runtime — except for the handful of real values, which are listed separately.
 */

// ── values (runtime) ─────────────────────────────────────────────────────────
export { ApiError, asIsoDateTime, asUuid, err, ok } from './common';
export { isTerminal } from './job';

// ── common ───────────────────────────────────────────────────────────────────
export type {
  ApiErrorCode,
  CoordinateFormat,
  CountResponse,
  DeletedResponse,
  ErrorBody,
  ErrorDetail,
  ErrorEnvelope,
  IdResponse,
  IsoDateTime,
  Page,
  PaginationParams,
  Point2D,
  Rect,
  Result,
  ResultRef,
  RevisionSummary,
  Size,
  SortParams,
  Uuid,
  WarningItem,
} from './common';

// ── geo ──────────────────────────────────────────────────────────────────────
export type {
  BasemapKind,
  BBox,
  Crs,
  GeoJsonFeature,
  GeoJsonFeatureCollection,
  GeoJsonGeometry,
  GeoJsonLineString,
  GeoJsonMultiPolygon,
  GeoJsonPoint,
  GeoJsonPolygon,
  GeoTransform,
  Homography,
  LatLon,
  LatLonAlt,
  LocationHint,
  MapViewState,
  PixelBox,
  PixelXY,
  ProviderAttribution,
  ProviderCapabilities,
  ProviderCoverage,
  ProviderHealth,
  ProviderId,
  ProviderInfo,
  ViewOrigin,
} from './geo';

// ── image ────────────────────────────────────────────────────────────────────
export type {
  CameraMetadata,
  CaptureMetadata,
  DerivedMetadata,
  FileMetadata,
  GeoTiffMetadata,
  GpsMetadata,
  ImageCounts,
  ImageFilters,
  ImageMetadataRead,
  ImageRead,
  ImageStatus,
  ImageSummary,
  ImageUpdate,
  ImageUploadAccepted,
  ImageUrls,
  ImageVariant,
  LatestMatchRef,
  RasterMetadata,
  VariantName,
} from './image';

// ── annotation ───────────────────────────────────────────────────────────────
export type {
  AnnotationApplyCounts,
  AnnotationBulkUpsertItem,
  AnnotationBulkUpsertRequest,
  AnnotationBulkUpsertResponse,
  AnnotationBulkUpsertResultItem,
  AnnotationCreate,
  AnnotationGeomType,
  AnnotationKind,
  AnnotationOp,
  AnnotationRead,
  AnnotationStyle,
  AnnotationSummary,
  AnnotationUpdate,
  AnnotationVersionChangeSummary,
  AnnotationVersionFilters,
  AnnotationVersionRead,
  AnnotationVersionSummary,
  RevisionCreate,
  RevisionDiffSummary,
  RevisionRead,
  RevisionRestoreRequest,
  RevisionRestoreResponse,
  RevisionSnapshot,
} from './annotation';

// ── gcp ★ the deliverable ────────────────────────────────────────────────────
export type {
  ConfidenceBand,
  GcpAccuracy,
  GcpFilters,
  GcpLandmarkRef,
  GcpOriginal,
  GcpOverview,
  GcpOverviewFilters,
  GcpRead,
  GcpRecomputeDelta,
  GcpRecomputeDryRun,
  GcpRecomputeFitStats,
  GcpRecomputeRequest,
  GcpResetRequest,
  GcpSource,
  GcpStaleReason,
  GcpSummary,
  GcpTableRow,
  GcpUpdate,
  SurveyorConfidence,
} from './gcp';

// ── match (DEFERRED surface — SCOPE.md §1) ───────────────────────────────────
export type {
  EstimatorName,
  ExtractorName,
  FeatureDetectorName,
  MatcherName,
  MatchFilters,
  MatchOptions,
  MatchRequest,
  MatchResultRead,
  MatchResultSelectRequest,
  MatchResultSummary,
  MatchScores,
  MatchStats,
  MatchTileRef,
  QualityFlag,
  SatelliteImageParams,
  ScoreWeights,
  SearchHint,
  ViewRegime,
} from './match';

// ── job ──────────────────────────────────────────────────────────────────────
export type {
  JobFilters,
  JobPollParams,
  JobProgress,
  JobRead,
  JobStage,
  JobStatus,
  JobSummary,
  JobType,
} from './job';

// ── album ★ collections of projects, many-to-many ────────────────────────────
export type {
  Album,
  AlbumCreate,
  AlbumFilters,
  AlbumRef,
  AlbumSummary,
  AlbumUpdate,
} from './album';

// ── video ★ a frame source: scrub → capture → a real image ───────────────────
export type { FrameCaptureRequest, Video, VideoCreate, VideoSummary, VideoUrls } from './video';

// ── project ──────────────────────────────────────────────────────────────────
export type {
  ProjectCounts,
  ProjectCreate,
  ProjectFilters,
  ProjectRead,
  ProjectSummary,
  ProjectUpdate,
} from './project';

// ── export ───────────────────────────────────────────────────────────────────
export type {
  CsvExportOptions,
  DxfExportOptions,
  ExportFilter,
  ExportFilters,
  ExportFormat,
  ExportOptions,
  ExportRead,
  ExportRequest,
  ExportSummary,
  KmlExportOptions,
  PdfExportOptions,
  ShapefileExportOptions,
} from './export';

// ── capabilities ─────────────────────────────────────────────────────────────
export type {
  CapabilitiesResponse,
  CapabilityItem,
  ComponentHealth,
  ComponentStatus,
  ComputeInfo,
  DefaultsInfo,
  ExportCapability,
  HealthResponse,
  HealthStatus,
  LimitsInfo,
  ReadinessResponse,
} from './capabilities';

// ── pose (DEFERRED — SCOPE.md §4) ────────────────────────────────────────────
export type {
  CameraIntrinsics,
  CameraIntrinsicsInput,
  CameraPoseRead,
  CameraPoseUpdate,
  Orientation,
  OrientationInput,
  PoseAmbiguity,
  PoseMethod,
  PoseUncertainty,
} from './pose';

// ── heatmap (DEFERRED — SCOPE.md §4) ─────────────────────────────────────────
export type {
  Colormap,
  HeatmapCandidate,
  HeatmapCell,
  HeatmapFormat,
  HeatmapGrid,
  HeatmapParams,
  HeatmapRead,
  HeatmapScoreRange,
  HeatmapSparsity,
} from './heatmap';

// ── semantic (DEFERRED — SCOPE.md §4) ────────────────────────────────────────
export type {
  FeatureSpace,
  MaskRle,
  SegmentBackend,
  SegmentPoint,
  SegmentRequest,
  SemanticClass,
  SemanticFeatureRead,
  SemanticFeatureSummary,
  SemanticFilters,
} from './semantic';

// ── suggestion (DEFERRED — SCOPE.md §4) ──────────────────────────────────────
export type {
  LandmarkSuggestionRead,
  SuggestionAcceptedRef,
  SuggestionAcceptRequest,
  SuggestionAcceptResponse,
  SuggestionFilters,
  SuggestionRejectRequest,
  SuggestionRejectResponse,
  SuggestionStatus,
  SuggestionStrategy,
  SuggestLandmarksRequest,
} from './suggestion';

// ── batch ────────────────────────────────────────────────────────────────────
export type {
  BatchCounts,
  BatchCreate,
  BatchFilters,
  BatchImageFilter,
  BatchItemRead,
  BatchOnError,
  BatchRead,
  BatchRollup,
  BatchSummary,
} from './batch';

// ── commands (client-only) ───────────────────────────────────────────────────
export type {
  AddAnnotationPayload,
  AddVertexPayload,
  AnnotationCommand,
  AnnotationCommandPayload,
  Command,
  CommandType,
  DeleteAnnotationPayload,
  DeleteVertexPayload,
  MoveAnnotationPayload,
  MoveVertexPayload,
  ReorderAnnotationPayload,
  SerializedCommand,
  SetConfidencePayload,
  SetKindPayload,
  SetLabelPayload,
} from './commands';

// ── DEM processing (`gis.dem`) ───────────────────────────────────────────────
export type {
  DemActiveResponse,
  DemCameraSummary,
  DemCropSummary,
  DemPoint,
  DemProcessForm,
  DemProcessResponse,
  DemReprojectSummary,
  DemResampling,
  DemSampleForm,
  DemSampleResponse,
  DemSampledPoint,
  DemStatistics,
} from './dem';

// ── The photograph's entered camera (from its setup page, one per image) ─────
export type { ImageCameraPut, ImageCameraRead } from './imageCamera';
