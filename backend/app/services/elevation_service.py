"""``elevation_service`` — the mandated third coordinate (§4.27).

The client brief mandates ``lat/lon/elevation/confidence``. This service wraps
``gis.elevation`` and fills ``gcps.elevation_m`` + ``gcps.elevation_source``, or — when no
provider resolves — leaves **both NULL** and reports ``ELEVATION_UNAVAILABLE``.

★ **The honesty rules are normative and are the whole point of this module:**

* when the resolved provider yields ``None``, ``elevation_m IS NULL`` **and
  ``elevation_source IS NULL``** (the DB check ``ck_gcps_elevation_source_consistent``
  binds the pair). The source may never name a producer that did not run.
* the default provider is ``none`` — keyless, offline, terminal — and it honestly returns
  ``ElevationSample(None, None, None)`` for every point. Honest beats absent.
* ``vertical_ce90_m`` is honest or ``None``; never a fabricated ``0``.

★ **Call-time binding.** ``gis.elevation`` reaches ``rasterio_shim`` for ``local_dem`` and
``httpx`` for ``copernicus_dem``; both are bound *inside* the provider's ``sample()``, and
this service imports ``gis.elevation`` at module scope only for its (dependency-free)
registry. Sampling on a bare machine with the ``none`` default touches neither.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from gis.elevation import ElevationSample, get_elevation_provider
from gis.errors import UnknownProviderError as GisUnknownProvider
from gis.types import LonLat

from app.core.config import Settings
from app.schemas.common import WarningItem

__all__ = ["ELEVATION_UNAVAILABLE_WARNING", "ElevationResult", "ElevationService"]

_log = logging.getLogger("app.services.elevation")

#: The warning the job appends when no elevation was produced (§4.27). Distinct object per
#: emission is unnecessary — it carries no per-point state — so it is a constant.
ELEVATION_UNAVAILABLE_WARNING = WarningItem(
    code="ELEVATION_UNAVAILABLE",
    message=(
        "No elevation provider resolved, so elevation is unavailable and is recorded as "
        "null rather than a fabricated value. Configure LE_ELEVATION_PROVIDER "
        "(local_dem or copernicus_dem) to populate it."
    ),
    field="elevation_m",
)


@dataclass(frozen=True, slots=True)
class ElevationResult:
    """One point's resolved elevation, ready to write onto a GCP.

    ``elevation_m`` and ``source`` are always both set or both ``None`` — the invariant
    ``ck_gcps_elevation_source_consistent`` enforces at the schema level and this type
    enforces at the service level.
    """

    elevation_m: float | None
    source: str | None
    vertical_ce90_m: float | None

    @property
    def available(self) -> bool:
        """True iff a provider actually produced an elevation for this point."""
        return self.elevation_m is not None


class ElevationService:
    """Resolve elevations for GCP coordinates from the configured DEM provider.

    Args:
        settings: The backend settings — the source of ``LE_ELEVATION_PROVIDER`` and its
            paths/URLs.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ── sampling ──────────────────────────────────────────────────────────────

    def sample(
        self,
        points: Sequence[LonLat],
        *,
        project_id: object | None = None,
        image_id: object | None = None,
    ) -> list[ElevationResult]:
        """Sample elevation at each point — batched, one provider call.

        ★ Batched by design (§4.27): a per-point HTTP call to a DEM service for 40 GCPs is
        40 round trips. When the provider is unavailable or unconfigured, every result is
        the honest ``(None, None, None)`` — never a raise, and never a fabricated value.

        Args:
            points: The GCP coordinates, ``(lon, lat)``.
            project_id: When given, the project's own DEM answers (or nothing does).
            image_id: When given alongside ``project_id``, THIS image's own DEM answers if
                it has one, else the project DEM — the image-overrides-project rule.

        Returns:
            One :class:`ElevationResult` per input point, positionally aligned.
        """
        if not points:
            return []

        provider = (
            # ★ No `or`-fallback: for a project, its own DEM answers or nothing does.
            self._project_provider(project_id, image_id)
            if project_id is not None
            else self._build_provider()
        )
        if provider is None or not self._is_configured(provider):
            return [ElevationResult(None, None, None) for _ in points]

        try:
            samples = provider.sample(list(points))
        except Exception as exc:  # noqa: BLE001 - a DEM outage degrades; it never fails a GCP
            _log.warning(
                "elevation provider %r failed to sample %d point(s): %s; recording null",
                self._settings.elevation_provider,
                len(points),
                exc,
            )
            return [ElevationResult(None, None, None) for _ in points]

        return [self._to_result(s) for s in samples]

    def sample_lonlat(
        self,
        points: Sequence[tuple[float, float]],
        *,
        project_id: object | None = None,
        image_id: object | None = None,
    ) -> list[ElevationResult]:
        """Sample from plain ``(lon, lat)`` pairs — the API layer's door into :meth:`sample`.

        ★ **Exists so a router never has to import ``gis``.** ``sample`` speaks
        ``gis.types.LonLat``, and the import-linter contract *"Routers do not touch the DB
        or the domain packages directly"* forbids ``app.api.v1 -> gis``. Constructing the
        value objects here keeps that boundary intact for one import's worth of
        convenience — which is precisely the sort of erosion the contract exists to stop.

        ★ **Longitude first**, matching ``LonLat`` and ``point_wkt``. Every human says
        "lat, lon" and every OGC format says the opposite; the transposition happens at
        the caller's boundary and is spelled out in the parameter name, not left implied.
        """
        return self.sample(
            [LonLat(lon=lon, lat=lat) for lon, lat in points],
            project_id=project_id,
            image_id=image_id,
        )

    def sample_one(
        self,
        lon: float,
        lat: float,
        *,
        project_id: object | None = None,
        image_id: object | None = None,
    ) -> ElevationResult:
        """Sample a single coordinate. The manual-GCP-create convenience over :meth:`sample`."""
        result = self.sample(
            [LonLat(lon=lon, lat=lat)], project_id=project_id, image_id=image_id
        )
        return result[0] if result else ElevationResult(None, None, None)

    def _project_provider(self, project_id: object | None, image_id: object | None = None):
        """The DEM provider for this project (or this image), or None when there is none.

        ★ Checked BEFORE ``LE_ELEVATION_PROVIDER`` and independently of it: uploading a
        DEM for a project is an explicit act by the surveyor for this survey, and should
        not need a server-wide setting to take effect. A missing file is simply "no
        project DEM" and falls through — never an error.

        ★ **Image overrides project**, the one rule shared with ``DemService`` and the
        auto-GCP raycast: when ``image_id`` names a photograph that has its own DEM
        (``{project}__{image}.tif``), that surface answers; otherwise the project DEM
        (``{project}.tif``) does. So a GCP's recorded Z comes from the same raster the
        raycast marched, never a different one.
        """
        if project_id is None:
            return None
        from pathlib import Path as _Path

        dem_dir = _Path(self._settings.project_dem_dir)
        path = dem_dir / f"{project_id}.tif"
        if image_id is not None:
            own = dem_dir / f"{project_id}__{image_id}.tif"
            try:
                if own.is_file():
                    path = own
            except OSError:  # pragma: no cover - permissions
                pass
        try:
            if not path.is_file():
                return None
        except OSError:  # pragma: no cover - permissions
            return None
        try:
            return get_elevation_provider(
                "dem_run",
                dem_path=str(path),
                vertical_ce90_m=self._settings.active_dem_ce90_m,
            )
        except GisUnknownProvider as exc:  # pragma: no cover - registry is static
            _log.warning("dem_run unavailable for project %s: %s", project_id, exc)
            return None

    def unavailable_warning(self, results: Sequence[ElevationResult]) -> WarningItem | None:
        """The ``ELEVATION_UNAVAILABLE`` warning, iff nothing resolved (§4.27).

        Returns ``None`` when at least one point got an elevation — a partial DEM is not a
        total failure and does not warrant a blanket warning.
        """
        if results and any(r.available for r in results):
            return None
        return ELEVATION_UNAVAILABLE_WARNING

    # ── internals ─────────────────────────────────────────────────────────────

    def _build_provider(self):
        """Construct the configured provider, or None if the name is unknown.

        ★ Construction never raises for missing config (the ABC's contract). An unknown
        *name* is a typo'd config: it is logged and degraded to null here rather than
        taking a GCP create down, because "no elevation" and "misconfigured elevation"
        both correctly yield a null third coordinate — refusing a survey coordinate over
        its elevation would be the worse failure.
        """
        name = self._settings.elevation_provider
        try:
            if name == "dem_run":
                # ★ Path, not directory: `dem_run` samples ONE raster — the adopted run —
                #   so the elevation on a GCP is traceable to a surface the surveyor saw.
                return get_elevation_provider(
                    "dem_run",
                    dem_path=str(self._settings.active_dem_path),
                    vertical_ce90_m=self._settings.active_dem_ce90_m,
                )
            if name == "local_dem":
                return get_elevation_provider("local_dem", dem_dir=str(self._settings.local_dem_dir))
            if name == "copernicus_dem":
                return get_elevation_provider(
                    "copernicus_dem", service_url=self._settings.copernicus_dem_url
                )
            return get_elevation_provider(name)
        except GisUnknownProvider as exc:
            _log.warning("unknown elevation provider %r; degrading to null: %s", name, exc)
            return None

    @staticmethod
    def _is_configured(provider) -> bool:
        try:
            return provider.is_configured()
        except Exception as exc:  # noqa: BLE001 - is_configured() must never raise
            _log.warning("elevation provider is_configured() raised: %s", exc)
            return False

    @staticmethod
    def _to_result(sample: ElevationSample) -> ElevationResult:
        """Coerce a gis ``ElevationSample`` into an ``ElevationResult``, enforcing the pair.

        ★ Defence in depth on the source/value biconditional: if a provider ever handed
        back an elevation with no source (or vice versa), that would violate
        ``ck_gcps_elevation_source_consistent`` on write. Rather than let psycopg reject
        it three frames later, the inconsistent half is discarded here and the row stays
        honest.
        """
        if sample.elevation_m is None or sample.source is None:
            return ElevationResult(None, None, None)
        return ElevationResult(
            elevation_m=float(sample.elevation_m),
            source=sample.source,
            vertical_ce90_m=(
                float(sample.vertical_ce90_m) if sample.vertical_ce90_m is not None else None
            ),
        )
