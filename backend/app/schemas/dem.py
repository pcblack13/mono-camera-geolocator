"""DEM processing — the wire contract for ``/dem`` (``gis.dem``).

Mirrors the three-stage algorithm's parameters exactly, and nothing else. The scaffold
page previously offered ``fill_sinks`` and a ``smoothing`` level; neither exists in the
algorithm, so neither exists here. Advertising a control the pipeline does not implement
is the same class of dishonesty as a fabricated confidence score.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "DemActiveResponse",
    "DemAoiCorner",
    "DemCameraSummary",
    "DemCropSummary",
    "DemProcessResponse",
    "DemReprojectSummary",
    "DemSampleRequest",
    "DemSampleResponse",
    "DemSampledPoint",
    "DemStatistics",
]


class DemAoiCorner(BaseModel):
    """One AOI corner. Accepts decimal degrees or any DMS spelling the algorithm reads."""

    model_config = ConfigDict(extra="forbid")

    lat: str | float = Field(
        ...,
        description=(
            "Latitude. Decimal degrees, or DMS such as `34°07'39.16\"N` or `34; 7; 39.16; N`."
        ),
        examples=["34°07'39.16\"N", 34.127544],
    )
    lon: str | float = Field(
        ...,
        description="Longitude, same accepted spellings as `lat`.",
        examples=["36°01'35.17\"E", 36.026436],
    )


class DemCropSummary(BaseModel):
    """What stage 1 did."""

    model_config = ConfigDict(extra="forbid")

    source_crs: str
    tolerance: float = Field(..., description="Padding fraction applied around the AOI.")
    output_size: tuple[int, int] = Field(..., description="(width, height) in pixels.")
    pixel_size: tuple[float, float] = Field(
        ..., description="Source pixel size, in the SOURCE CRS's units (degrees, usually)."
    )
    clipped: bool = Field(
        ...,
        description=(
            "True when the padded AOI reached past the DEM's edge and was clamped. "
            "The area of interest is not fully covered by this tile."
        ),
    )
    aoi_corners_lonlat: list[tuple[float, float]] = Field(default_factory=list)


class DemReprojectSummary(BaseModel):
    """What stage 2 did — ``(lambda, phi, H) -> (E, N, H)``."""

    model_config = ConfigDict(extra="forbid")

    source_crs: str
    target_crs: str
    resampling: str
    auto_utm: bool = Field(
        ..., description="True when the UTM zone was chosen from the DEM centre."
    )
    source_pixel_size: tuple[float, float]
    output_pixel_size_m: tuple[float, float] = Field(
        ...,
        description=(
            "★ The DEM's ground sample distance in TRUE metres — the number to read "
            "when judging what the surface can support."
        ),
    )
    output_size: tuple[int, int]
    output_bounds_m: tuple[float, float, float, float]


class DemStatistics(BaseModel):
    """Elevation range of the processed DEM. ``None`` when every cell is void."""

    model_config = ConfigDict(extra="forbid")

    min_m: float | None = None
    max_m: float | None = None
    mean_m: float | None = None
    valid_cells: int = 0
    void_cells: int = 0


class DemCameraSummary(BaseModel):
    """The camera station the AOI was built from, and the zone it fixes."""

    model_config = ConfigDict(extra="forbid")

    lat: float
    lon: float
    radius_m: float = Field(..., description="Working radius, TRUE ground metres.")
    utm_epsg: str = Field(
        ...,
        description=(
            "★ The UTM zone the camera position falls in. Derived, never typed — a zone "
            "entered by hand can be wrong; one taken from where the camera stood cannot."
        ),
    )


class DemProcessResponse(BaseModel):
    """``POST /dem/process`` — the full record of one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Handle for download and sampling.")
    camera: DemCameraSummary | None = Field(
        None, description="Present when the AOI came from a camera position + radius."
    )
    source_name: str
    source_crs: str
    output_crs: str
    output_size: tuple[int, int]
    output_pixel_size_m: tuple[float, float] | None = Field(
        None,
        description="None when the output is not in a ground-metre CRS.",
    )
    output_bytes: int
    crop: DemCropSummary | None = None
    reproject: DemReprojectSummary | None = None
    statistics: DemStatistics
    aoi_geojson: dict[str, Any] | None = Field(
        None, description="The AOI polygon, WGS84, for drawing on the map."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Honest notes: a clamped crop, a skipped stage, a void-heavy output.",
    )
    download_url: str
    is_elevation_source: bool = Field(
        False,
        description=(
            "True when this run's output was adopted as the DEM that new GCPs sample "
            "their elevation from. ★ Existing GCPs are NOT re-sampled — a recorded "
            "elevation is an observation, not a live query."
        ),
    )


class DemSampledPoint(BaseModel):
    """One sampled point — stage 3's row."""

    model_config = ConfigDict(extra="forbid")

    name: str
    lat: float
    lon: float
    x: float | None = Field(None, description="Easting in the output CRS, metres.")
    y: float | None = Field(None, description="Northing in the output CRS, metres.")
    dem_z_m: float | None = Field(
        None, description="Raw DEM elevation. ★ null and 0.0 are different claims."
    )
    offset_m: float = 0.0
    z_m: float | None = Field(None, description="dem_z_m + offset_m.")
    inside_dem: bool
    suspicious: bool = Field(
        False, description="Elevation outside the plausible land-surface range."
    )


class DemSampleRequest(BaseModel):
    """``POST /dem/{run_id}/sample`` — stage 3."""

    model_config = ConfigDict(extra="forbid")

    points: Annotated[list[DemAoiCorner], Field(min_length=1, max_length=5000)] = Field(
        ..., description="Points to sample, EPSG:4326."
    )
    names: list[str] | None = Field(
        None, description="Optional per-point labels; defaults to P1, P2, …"
    )
    method: Literal["bilinear", "nearest"] = "bilinear"
    offset_m: float = Field(0.0, description="Constant height offset added to every Z.")
    output_crs: str | None = Field(
        None, description="CRS for the returned X/Y. Defaults to the DEM's own CRS."
    )

    @field_validator("names")
    @classmethod
    def _names_match_points(cls, v: list[str] | None, info: Any) -> list[str] | None:
        points = info.data.get("points")
        if v is not None and points is not None and len(v) != len(points):
            raise ValueError(
                f"names has {len(v)} entries but points has {len(points)}; a label that "
                "silently pairs with the wrong coordinate is worse than no label"
            )
        return v


class DemSampleResponse(BaseModel):
    """``POST /dem/{run_id}/sample`` result."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    dem_crs: str = Field(..., description="The CRS the DEM was sampled in.")
    output_crs: str = Field(..., description="The CRS X/Y are reported in.")
    method: str
    offset_m: float
    points: list[DemSampledPoint]
    inside_count: int
    with_elevation_count: int


class DemActiveResponse(BaseModel):
    """``GET /dem/active`` — which DEM currently feeds GCP elevations."""

    model_config = ConfigDict(extra="allow")

    active: bool = Field(..., description="False when no DEM has been adopted.")
    provider_enabled: bool = Field(
        False,
        description=(
            "True when LE_ELEVATION_PROVIDER is `dem_run`. ★ A DEM can be adopted while "
            "the provider is off, in which case nothing samples it — reported rather "
            "than silently ignored."
        ),
    )
    path: str | None = None
    run_id: str | None = None
    source_name: str | None = None
    adopted_at: str | None = None
    output_crs: str | None = None
    output_pixel_size_m: list[float] | None = None
    vertical_ce90_m: float | None = Field(
        None, description="Reported on every GCP sampled from this DEM."
    )
    vertical_datum: str | None = Field(
        None,
        description=(
            "`unknown` unless declared. Copernicus/FABDEM are orthometric (EGM2008); "
            "GNSS altitudes are ellipsoidal and differ by ~20 m in Lebanon."
        ),
    )
    statistics: dict[str, Any] | None = None
