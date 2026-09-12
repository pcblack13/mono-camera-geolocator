"""Project elevation sampling — the wire contract for ``/projects/{id}/elevation/sample``.

★ **Distinct from ``/dem/{run_id}/sample``, and deliberately so.** That endpoint samples a
specific *processing run's* output and reports the DEM's own CRS, easting/northing and
nodata geometry — it is the DEM page's stage 3, aimed at someone preparing a raster. This
one answers a different question: *"what does THIS PROJECT say the elevation is here?"* It
takes the project's own attached DEM (``ElevationService._project_provider``), returns
metres plus the vertical error bar, and knows nothing about runs. A surveyor hovering the
map does not have a run id and should not need one.

★ **THE NULL IS THE POINT.** A project with no DEM attached, a point outside coverage, and
a nodata void all return ``elevation_m: null`` with ``source: null``. They never return 0.
``ck_gcps_elevation_source_consistent`` binds that pair in the database and this schema
mirrors it on the wire, so a client cannot receive a height whose provenance is unstated —
nor a source naming a DEM that did not answer.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel

__all__ = [
    "ElevationSampleRequest",
    "ElevationSampleResponse",
    "ElevationSamplePoint",
    "SampledElevation",
]


class ElevationSamplePoint(ApiModel):
    """One coordinate to sample, EPSG:4326."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class SampledElevation(ApiModel):
    """One point's answer, positionally aligned with the request."""

    model_config = ConfigDict(extra="forbid")

    elevation_m: float | None = Field(
        default=None,
        description=(
            "Metres above the vertical datum, or **null** when this project has no DEM, "
            "the point is outside coverage, or the cell is nodata. ★ Never 0 as a "
            "stand-in — 0 m is a real elevation and must stay distinguishable."
        ),
    )
    source: str | None = Field(
        default=None,
        description=(
            "`local_dem` | `copernicus_dem` | `srtm` | `exif` | `manual`. ★ Non-null **iff** "
            "`elevation_m` is — a source may never name a provider that did not answer."
        ),
    )
    vertical_ce90_m: float | None = Field(
        default=None,
        description=(
            "Vertical CE90 in metres, or null when unquantified. ★ Null is honest; 0 "
            "would launder an estimate into a measurement."
        ),
    )


class ElevationSampleRequest(ApiModel):
    """``POST /projects/{id}/elevation/sample``.

    ★ **Batched, even for one point.** The provider reads a raster (or calls a service)
    once per request regardless of point count, so a hover readout and a 500-point query
    take the same code path. A single-point convenience endpoint would be a second
    implementation of the one thing that must not drift.
    """

    model_config = ConfigDict(extra="forbid")

    points: Annotated[list[ElevationSamplePoint], Field(min_length=1, max_length=5000)] = (
        Field(..., description="Coordinates to sample, EPSG:4326.")
    )


class ElevationSampleResponse(ApiModel):
    """``POST /projects/{id}/elevation/sample`` result."""

    model_config = ConfigDict(extra="forbid")

    results: list[SampledElevation] = Field(
        default_factory=list,
        description="One entry per requested point, in the order they were sent.",
    )
    dem_attached: bool = Field(
        description=(
            "Whether this project has a DEM at all. ★ Distinguishes *'no DEM configured'* "
            "from *'DEM answered null here'* — the first is a setup step the surveyor can "
            "take, the second is the terrain. Collapsing them would send someone hunting "
            "for a coverage problem when they simply never attached a raster."
        )
    )
    with_elevation_count: int = Field(
        ge=0, description="How many points actually resolved to a height."
    )
