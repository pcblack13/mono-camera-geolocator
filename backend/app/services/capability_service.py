"""``capability_service`` — ``GET /capabilities`` (endpoint 3), the honest picture.

★★ **It READS the cached ``PreflightReport`` off ``app.state`` and NEVER re-runs preflight**
(§11.1, §14 F-60). Re-running sha256 over a 2.4 GB SAM checkpoint per request is not a
health check, it is an outage. The report is computed once in ``main.py``'s lifespan; this
service turns it, plus the (cheap, offline) gis registries, into a
:class:`~app.schemas.capabilities.CapabilitiesResponse`.

★ **It reports the truth of THIS build** (SCOPE.md §4 rule 3): every ``ai_engine``
component is **deferred** — the interface exists, the body raises ``NotImplementedDeferred``,
and there is no fallback because the fallback is deferred too. So each extractor / matcher /
estimator / segmenter / suggester is reported with ``status="deferred"`` and ``fallback=
None`` — never ``available`` and never a fabricated substitute. Providers and elevation
providers are **built**, so they report ``available``/``unavailable`` honestly.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
from datetime import datetime, timezone
from typing import Any

from ai_engine.errors import SCOPE_DOC

from app.core.config import Settings
from app.schemas.capabilities import (
    CapabilitiesResponse,
    CapabilityItem,
    ComputeInfo,
    DefaultsInfo,
    ExportCapability,
    LimitsInfo,
)
from app.services.imagery_service import ImageryService

__all__ = ["CapabilityService"]

_log = logging.getLogger("app.services.capability")

#: SCOPE.md §1's deferred feature names, published so the UI gates controls off ONE
#: server list rather than a hard-coded constant (SCOPE.md §7). Each matches a 501 body's
#: ``component`` family.
DEFERRED_FEATURES = (
    "matching",
    "feature_extraction",
    "ransac",
    "camera_pose",
    "heatmap",
    "segmentation",
    "landmark_suggestion",
)

_DEFERRED_REASON = f"Deferred in this build (manual GCP surveying); see {SCOPE_DOC}."

#: Export format → the optional dependency and pip extra that enable it. Formats not
#: listed here are pure-stdlib writers and are always available.
_EXPORT_DEPS: dict[str, tuple[str, str]] = {
    "shapefile": ("geopandas", "gis[exports]"),
    "gpkg": ("geopandas", "gis[exports]"),
    "dxf": ("ezdxf", "gis[exports]"),
    "pdf": ("reportlab", "gis[exports]"),
}


class CapabilityService:
    """Assemble the capabilities response from cached, cheap sources only.

    Args:
        settings: The backend settings — limits, defaults, export formats.
        imagery: For the provider list and the resolved default provider (L2).
        preflight_report: The ``PreflightReport`` cached on ``app.state`` at boot. Passed
            in (never recomputed here). May be None if the lifespan has not run yet — the
            compute block then degrades to what it can read cheaply.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        imagery: ImageryService,
        preflight_report: Any | None = None,
    ) -> None:
        self._settings = settings
        self._imagery = imagery
        self._report = preflight_report

    def get_capabilities(self) -> CapabilitiesResponse:
        """Build the whole honest picture in one read. Never re-runs preflight."""
        from ai_engine.models import ComponentKind, REGISTRY  # call-time: keep import cheap

        engine_version = self._engine_version()

        return CapabilitiesResponse(
            version="1.0.0",
            engine_version=engine_version,
            extractors=self._engine_items(REGISTRY, ComponentKind.EXTRACTOR),
            matchers=self._engine_items(REGISTRY, ComponentKind.MATCHER)
            + self._engine_items(REGISTRY, ComponentKind.DETECTOR_FREE),
            estimators=self._engine_items(REGISTRY, ComponentKind.ESTIMATOR),
            segmenters=self._engine_items(REGISTRY, ComponentKind.SEGMENTER),
            suggesters=self._engine_items(REGISTRY, ComponentKind.SUGGESTER),
            providers=self._provider_items(),
            elevation_providers=self._elevation_items(),
            exports=self._export_items(),
            compute=self._compute_info(),
            limits=self._limits_info(),
            defaults=self._defaults_info(),
            deferred_features=list(DEFERRED_FEATURES),
            checked_at=self._checked_at(),
        )

    # ── ai_engine components — every one deferred in this build ────────────────

    def _engine_items(self, registry: Any, kind: Any) -> list[CapabilityItem]:
        """Every registered spec of a kind, reported as DEFERRED (SCOPE.md §4).

        The registry knows what EXISTS; SCOPE.md decides what is IMPLEMENTED, and in this
        build every ``ai_engine`` path resolves to deferred. So ``status='deferred'``,
        ``available=False``, ``fallback=None`` — offering a substitute that also will not
        run is the one thing worse than saying so plainly.
        """
        items: list[CapabilityItem] = []
        for spec in registry.specs(kind):
            requires_weights = bool(spec.requires_weights)
            items.append(
                CapabilityItem(
                    name=spec.name,
                    available=False,
                    kind="deep" if requires_weights else "classical",
                    requires_weights=requires_weights,
                    status="deferred",
                    reason=_DEFERRED_REASON,
                    fallback=None,
                )
            )
        return items

    # ── providers — built, real ───────────────────────────────────────────────

    def _provider_items(self) -> list[CapabilityItem]:
        """Imagery providers as capability items. Real: available iff configured+allowed."""
        items: list[CapabilityItem] = []
        for listing in self._imagery._registry.available():  # cheap, never raises
            usable = listing.usable
            items.append(
                CapabilityItem(
                    name=listing.name,
                    available=usable,
                    kind="classical",
                    requires_weights=False,
                    status="available" if usable else "unavailable",
                    reason=None if usable else listing.reason,
                    fallback=None,
                )
            )
        return items

    def _elevation_items(self) -> list[CapabilityItem]:
        """Elevation providers as capability items."""
        from gis.elevation import ELEVATION_PROVIDER_NAMES, get_elevation_provider

        items: list[CapabilityItem] = []
        for name in ELEVATION_PROVIDER_NAMES:
            configured, reason = self._elevation_state(name, get_elevation_provider)
            items.append(
                CapabilityItem(
                    name=name,
                    available=configured,
                    kind="classical",
                    requires_weights=False,
                    status="available" if configured else "unavailable",
                    reason=None if configured else reason,
                    fallback=None,
                )
            )
        return items

    def _elevation_state(self, name: str, factory: Any) -> tuple[bool, str | None]:
        try:
            if name == "local_dem":
                provider = factory("local_dem", dem_dir=str(self._settings.local_dem_dir))
            elif name == "copernicus_dem":
                provider = factory("copernicus_dem", service_url=self._settings.copernicus_dem_url)
            else:
                provider = factory(name)
            configured = provider.is_configured()
            return configured, (None if configured else "not configured")
        except Exception as exc:  # noqa: BLE001 - a capability probe never raises
            return False, f"unavailable: {exc}"

    # ── exports — built, degrade on a missing optional dep ────────────────────

    def _export_items(self) -> list[ExportCapability]:
        """Every configured export format, available iff its writer's dep is importable."""
        items: list[ExportCapability] = []
        for fmt in self._settings.export_formats:
            dep = _EXPORT_DEPS.get(fmt)
            if dep is None:
                items.append(ExportCapability(format=fmt, available=True))  # type: ignore[arg-type]
                continue
            module, extra = dep
            available = importlib.util.find_spec(module) is not None
            items.append(
                ExportCapability(
                    format=fmt,  # type: ignore[arg-type]
                    available=available,
                    reason=None if available else f"{module} is not installed.",
                    requires_extra=None if available else extra,
                )
            )
        return items

    # ── compute / limits / defaults ───────────────────────────────────────────

    def _compute_info(self) -> ComputeInfo:
        """What this process can run on, from the cached report + cheap, non-torch reads.

        ★ Does NOT import torch (L8 — torch lives in exactly one module, inside
        ``ai_engine``). The torch *version* is read from installed-package metadata, which
        does not import it; ``cuda_available`` and the selected device come from the cached
        ``PreflightReport``.
        """
        import numpy as np

        device, cuda = self._device_and_cuda()
        return ComputeInfo(
            device=device,
            torch_available=self._package_present("torch"),
            torch_version=self._package_version("torch"),
            cuda_available=cuda,
            gpu_name=None if not cuda else self._report_attr("gpu_name", None),
            opencv_version=self._opencv_version(),
            numpy_version=np.__version__,
            raster_backend=self._raster_backend(),
            worker_count=self._settings.celery_worker_concurrency,
        )

    def _limits_info(self) -> LimitsInfo:
        s = self._settings
        return LimitsInfo(
            upload_max_bytes=s.upload_max_bytes,
            async_ingest_threshold_bytes=s.async_ingest_threshold_bytes,
            max_image_pixels=s.max_image_pixels,
            max_image_dimension=s.max_image_dim,
            max_annotations_per_image=s.max_annotations_per_image,
            max_tiles_per_match=s.max_tiles_per_job,
            max_search_radius_m=s.search_max_radius_m,
            max_timeout_s=s.celery_task_soft_time_limit,
            max_replay_events=s.max_replay_events,
            max_batch_items=s.max_batch_files,
        )

    def _defaults_info(self) -> DefaultsInfo:
        s = self._settings
        return DefaultsInfo(
            provider=self._imagery._default_provider_name(),  # type: ignore[arg-type]
            extractor=s.ai_extractor,  # type: ignore[arg-type]
            matcher=s.ai_matcher,  # type: ignore[arg-type]
            # ★ EstimatorName is the robust-fit METHOD (usac_magsac, ...), NOT the
            #   component registry key (ai_estimator_backend='opencv'). §9.8 keeps the two
            #   concepts separate; DefaultsInfo wants the method.
            estimator=s.ai_ransac_method,  # type: ignore[arg-type]
            search_radius_m=s.search_default_radius_m,
            search_zoom=s.search_default_zoom,
            min_confidence=s.ai_min_confidence,
        )

    # ── internals ─────────────────────────────────────────────────────────────

    def _device_and_cuda(self) -> tuple[str, bool]:
        cuda = bool(self._report_attr("cuda_available", False))
        device_selected = self._report_attr("device_selected", None)
        name = str(device_selected).lower() if device_selected is not None else ("cuda" if cuda else "cpu")
        device = "cuda" if ("cuda" in name and cuda) else "cpu"
        return device, cuda

    def _report_attr(self, name: str, default: Any) -> Any:
        return getattr(self._report, name, default) if self._report is not None else default

    def _checked_at(self) -> datetime:
        epoch = self._report_attr("checked_at", None)
        if isinstance(epoch, (int, float)):
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        return datetime.now(tz=timezone.utc)

    def _engine_version(self) -> str:
        try:
            import ai_engine

            return ai_engine.__version__
        except Exception:  # noqa: BLE001
            return "unknown"

    @staticmethod
    def _package_present(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    @staticmethod
    def _package_version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _opencv_version() -> str:
        try:
            import cv2  # base dep of ai_engine/gis; safe to import

            return cv2.__version__
        except Exception:  # noqa: BLE001
            return "unavailable"

    @staticmethod
    def _raster_backend() -> str:
        try:
            from gis.rasterio_shim import probe

            return str(probe())
        except Exception:  # noqa: BLE001
            return "none"
