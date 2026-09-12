"""Accuracy checks — wire types for ``/accuracy/*``.

★ WHAT THIS FEATURE CLAIMS, stated once so every field below inherits it: the error
reported here is measured against the SATELLITE BASEMAP, which carries its own
georeferencing error of a few metres. "3 m of error" means "3 m from where the basemap
puts it", not "3 m from truth". Breaking that floor needs GNSS-surveyed checkpoints,
and no number in these models pretends otherwise.

The stages, and why the API mirrors them as separate calls: **measure** (Stage D) is the
slow, network-touching step whose result is worth keeping; **correct** (Stages E + F) is
seconds and re-runnable against the same measurement; **suggest** needs neither.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from .common import ApiModel

__all__ = [
    "AccuracyBand",
    "AccuracyMeasurement",
    "AccuracyRunStatus",
    "AccuracyState",
    "AccuracyTile",
    "AdoptRequest",
    "AdoptionRead",
    "BasePoseRead",
    "CorrectRequest",
    "CorrectionReport",
    "HeatmapVersion",
    "MeasureRequest",
    "PixelQueryAnswer",
    "PixelQueryRead",
    "PixelQueryRequest",
    "SolutionEntry",
    "SolutionRow",
    "SolutionsRead",
    "SolveOptionsRead",
    "SolveOptionsRequest",
    "SuggestRequest",
    "SuggestRegion",
    "SuggestionsRead",
]

RunKind = Literal["measure", "correct", "suggest"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
SolutionKey = Literal["raw", "pose", "field", "stagef"]


# ─────────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────────


class MeasureRequest(ApiModel):
    """``POST /accuracy/measure`` — Stage D, on one photograph.

    The defaults are the field tool's own and suit 100–200 m flights. ``tile`` and
    ``stride`` trade resolution against reliability: smaller tiles resolve local
    structure but lock less often.
    """

    image_id: UUID
    #: Basemap to measure against. Omitted → the server's default provider. A provider
    #: whose terms forbid storing tiles is refused: the run writes a mosaic to disk.
    provider: str | None = None
    #: Ortho ground sample distance, metres per cell.
    gsd: float = Field(default=1.0, ge=0.25, le=5.0)
    #: How far out to rectify and match.
    max_range: float = Field(default=1100.0, ge=100.0, le=5000.0)
    #: Correlation tile size, metres.
    tile: int = Field(default=128, ge=32, le=512)
    #: Tile step, metres. Must not exceed ``tile`` or the scene goes unmeasured.
    stride: int = Field(default=64, ge=16, le=512)
    #: Satellite zoom to fetch. The server steps down if the area is too large.
    sat_zoom: int = Field(default=17, ge=13, le=20)
    #: Mutual-information second chance for tiles phase correlation rejected.
    mi_rescue: bool = True
    #: Coarse-to-fine half-size sub-tiles over each lock.
    fine_pass: bool = True
    # ── grazing geometry (2026-09-10) ───────────────────────────────────────────
    # ★ EVERY DEFAULT BELOW IS THE ENGINE'S OWN. A request that names none of them
    #   measures exactly what it measured before they existed, so a measurement made
    #   last week and one made today stay comparable. They exist for the cameras this
    #   product watches — a fixed mast looking kilometres out, where a tile is
    #   SHEARED by terrain-height error rather than merely shifted.
    #: A 'match' larger than this is refused as a false lock. THE ONE DEFAULT THAT IS
    #: NOT THE ENGINE'S: its 25 m suits a drone, and this product watches fixed masts
    #: at grazing incidence, where 25 m censors real 26-30 m errors and silently
    #: shrinks the measured set. Upstream names 50 m for a ground camera.
    max_shift: float = Field(default=50.0, ge=5.0, le=200.0)
    #: Affine (ECC) third chance for tiles both phase correlation and mutual
    #: information rejected. Rescue only — a tile that already locked is never
    #: touched. Off by default: it changes WHICH ground gets measured, so a run with
    #: it on is not comparable with one without.
    ecc_rescue: bool = False
    #: Let the scene's own geometry choose the tile size, overriding ``tile`` and
    #: ``stride``. A large tile holds more texture; a small one spans less change in
    #: amplification. The summary reports which size actually ran.
    tile_auto: bool = False
    #: The terrain model's 1-sigma height error, metres. Scales the ``sigma_m``
    #: reported per tile; on its own it gates nothing.
    sigma_dtm: float = Field(default=3.0, ge=0.1, le=50.0)
    #: Above 0, drop tiles whose expected sigma exceeds this many metres. 0 reports
    #: the number on every tile and drops none, which is the honest default: a tile
    #: with a large expected sigma is weak evidence, not absent evidence.
    reliability_max: float = Field(default=0.0, ge=0.0, le=200.0)
    #: Raise ``max_range`` when it leaves under 85% of the visible ground inside it —
    #: a coverage rule, not a distance, so a drone flight at 94-100% keeps its numbers
    #: and a mast whose 1100 m circle holds 3% of what it sees gets a reach that
    #: contains its subject. The summary records what was requested and what ran.
    auto_reach: bool = True
    #: Remove cloud in the satellite imagery from the content before matching. A
    #: lock on a cloud edge is not a geolocation error, and the consistency filter
    #: cannot catch one. Off by default because white roofs can trigger the mask;
    #: the run reports how many locked tiles sit on cloud either way.
    cloud_mask: bool = False


class CorrectRequest(ApiModel):
    """``POST /accuracy/correct`` — Stages E + F over the stored measurement."""

    image_id: UUID
    #: Interpolate what the refined pose could not express. Never extrapolated outside
    #: the measured area — off that area it corrects nothing rather than guessing.
    use_residual_field: bool = True
    #: Also solve one focal scale (fy follows fx). Off by default: at grazing geometry
    #: focal trades off against tilt, and a free focal can wander.
    free_focal: bool = False


class SuggestRequest(ApiModel):
    """``POST /accuracy/suggest`` — where the next control point would help most."""

    image_id: UUID
    count: int = Field(default=4, ge=1, le=8)
    #: ``ground`` = metres of predicted error removed where the error actually is.
    #: ``dopt`` = plain D-optimality, kept for comparison and measurably worse.
    criterion: Literal["ground", "dopt"] = "ground"
    #: Region HALF-size as a fraction of image width. None = the core's default.
    box_frac: float | None = Field(default=None, ge=0.01, le=0.35)
    #: Below this predicted cut, adding points has stopped mattering.
    stop_below_pct: float = Field(default=5.0, ge=0.0, le=100.0)


class AdoptRequest(ApiModel):
    """``POST /accuracy/images/{image_id}/adoption`` — choose the answer to stand on.

    ★ Any AVAILABLE stage, including ``raw``. The comparison's ``best`` is a
    recommendation from held-out tiles; the surveyor may know better (a feature they can
    see is in the right place), and "I chose not to correct" is a decision worth
    recording rather than an absence of one.
    """

    stage: SolutionKey


class AdoptionRead(ApiModel):
    """What this photograph stands on, and the evidence as it stood when chosen.

    ★ SCOPE, stated so no client can imply more: adopting changes what a **LUT build**
    stands on. Placed GCPs, exported coordinates and Auto GCP estimates keep using the
    pose solved from the control points themselves — a correction measured against a
    basemap does not retroactively rewrite coordinates that were signed off against
    something else.
    """

    stage: SolutionKey
    label: str
    adopted_at: datetime
    #: When the comparison it was chosen from was produced. A newer correction clears
    #: the adoption rather than re-pointing it at numbers it never saw.
    corrected_at: datetime | None
    all_m: float | None
    p95_m: float | None
    worst20_share: float | None
    held_out: bool
    #: What the comparison recommended — kept beside the choice, never instead of it.
    recommended: SolutionKey
    matches_recommendation: bool
    gate_accepted: bool
    gate_reason: str | None
    #: False for ``raw``: the build stands on the GCP-solved pose, as it always did.
    uses_refined_pose: bool


class SolveOptionsRequest(ApiModel):
    """``PUT /accuracy/images/{image_id}/solve-options`` — how the RAW pose is solved.

    ★ Changing this retires everything derived from the previous pose (measurement,
    correction, comparison, adoption), because those numbers describe a solve that no
    longer exists. The next cycle measures the pose actually in force.
    """

    #: Solve ONE focal scale alongside the pose (fy follows fx at the entered ratio)
    #: instead of trusting the calibration exactly. Off by default: at grazing geometry
    #: focal trades off against tilt, so a freed focal can wander far from the
    #: calibrated value while the reprojection barely moves.
    free_focal: bool = False


class SolveOptionsRead(ApiModel):
    """How this photograph's raw pose is being solved."""

    free_focal: bool


class PixelQueryRequest(ApiModel):
    """``POST /accuracy/images/{image_id}/query`` — one pixel, every answer."""

    #: Full-resolution image pixels, y-down — the space ``gcps.pixel_x/y`` uses.
    u: float = Field(ge=0)
    v: float = Field(ge=0)
    target_height_m: float = Field(default=0.0, ge=-100.0, le=1000.0)


# ─────────────────────────────────────────────────────────────────────────────
# Runs
# ─────────────────────────────────────────────────────────────────────────────


class AccuracyRunStatus(ApiModel):
    """One stage's run. Polled — the message is the core's own progress narration."""

    run_id: str
    kind: RunKind
    image_id: UUID
    project_id: UUID
    status: RunStatus
    progress_pct: int
    message: str
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# The stored result
# ─────────────────────────────────────────────────────────────────────────────


class AccuracyTile(ApiModel):
    """One matched patch of ground: where our content sits versus the basemap's.

    ★ ``ok`` false means the tile did NOT lock — it is carried so the map can grey it
    rather than imply the ground there was measured and found good.
    """

    x: float
    y: float
    tile_px: int
    dE: float
    dN: float
    err: float
    #: Along the sightline — the DEM-height channel.
    radial: float
    #: Across it — the pose channel.
    tangential: float
    range_m: float
    response: float
    #: ``ecc`` is the affine rescue — a tile recovered because it was SHEARED by
    #: terrain-height error rather than merely shifted.
    method: Literal["phase", "mi", "fine", "ecc"]
    ok: bool
    # ── how much this tile's number is worth (2026-09-10) ───────────────────────
    #: How far a metre of terrain-height error moves this tile's ground
    #: intersection: about 2 looking down from a drone, several times that along a
    #: mast's grazing sight line. Two tiles both reading 8 m are not equal evidence
    #: when one amplifies twice and the other six times.
    #: Null where the tile's ground centre could not be read.
    amplification: float | None = None
    #: ``amplification * sigma_dtm`` — the error this tile carries from the terrain
    #: model alone, before anything the pose did.
    sigma_m: float | None = None


class AccuracyBand(ApiModel):
    """Per-distance-band summary — near/mid/far, because error grows with range."""

    band: str
    tiles: int
    median_error_m: float
    dE: float
    dN: float
    radial: float
    tangential: float


class AccuracyAmplification(ApiModel):
    """What the scene's geometry does to terrain-height error, over the locked tiles.

    ★ A SPREAD, NOT ONE NUMBER. The near ground and the far ground of a grazing view
    amplify very differently, and a median alone would hide exactly that. Read
    ``p90`` when deciding whether a scene is measurable at all: it is what the worst
    usable tiles are carrying.
    """

    median: float
    p90: float
    max: float
    tiles: int
    #: The convention behind the figures — per locked tile, not per ground cell. An
    #: area-weighted figure reads higher on the same scene, so it is named rather
    #: than left for a reader to assume.
    weighting: str
    #: What ``median`` implies at this terrain model's 1-sigma: the floor under the
    #: measured error that no pose correction can lift.
    expected_sigma_m: float
    sigma_dtm_m: float


class AccuracyZoneCell(ApiModel):
    """One of the nine zones: a range band crossed with an image column."""

    #: Index into ``bands_m`` — 0 is the nearest band.
    band: int
    column: Literal["L", "M", "R"]
    #: How many locked tiles the number rests on.
    tiles: int
    #: Median error of those tiles. Null under ``min_tiles``: the zone then has NO
    #: number, and a client must draw a wash rather than a colour that reads as one.
    median_error_m: float | None


class AccuracyZones(ApiModel):
    """The nine range zones traced on the photograph, and the error inside each.

    ★ THE MEASUREMENT PUT BACK IN THE FRAME. Stage D measures on the ground; the
    surveyor's question is asked at the photograph. Curves are in ORIGINAL photo
    pixels — the same convention the suggestion boxes use — and BEND with the
    terrain: a straight row would be wrong by hundreds of metres on any real slope.
    """

    width: int
    height: int
    #: The far edge of each band, metres of ground range. Thirds of the farthest
    #: locked tile, so the bands fit the scene rather than a fixed drone default.
    bands_m: list[float]
    min_tiles: int
    #: One contour per band, ``[[u, v], ...]`` left to right; null where that edge
    #: never crosses the frame.
    curves: list[list[list[float]] | None]
    cells: list[AccuracyZoneCell]
    #: The colour scale's two ends over the zones with data; null when none has any.
    range_m: list[float] | None = None


class AccuracyReach(ApiModel):
    """What the coverage rule did with the requested reach."""

    requested_m: float
    #: The reach that ran — the mosaic's radius and the ortho's extent.
    used_m: float
    #: Share of the visible ground inside the requested reach, 0..1.
    coverage_requested: float
    coverage_used: float
    raised: bool
    min_coverage: float
    cap_m: float
    #: How many sampled pixels saw ground at all; the coverages are shares of these.
    visible_samples: int


class AccuracyCloud(ApiModel):
    """Basemap cloud — how much of the content it is, and how many locks sit on it."""

    masked: bool
    #: Share of the content the photograph covers that the mask calls cloud, 0..1.
    content_fraction: float
    #: Locked tiles with more than ``tile_fraction_threshold`` of their footprint on
    #: cloud. With the mask off, the reason to turn it on.
    locked_tiles_on_cloud: int
    tile_fraction_threshold: float


class AccuracyMeasurement(ApiModel):
    """Stage D's stored result."""

    measured_at: datetime
    provider: str
    params: dict[str, Any]
    tiles_total: int
    tiles_locked: int
    #: ★ THE TRUST SIGNAL. Under ~0.5 the comparison is unreliable — usually a very low
    #: flight. Reported, never hidden, and warned about in ``warnings``.
    match_rate: float
    median_error_m: float | None
    bands: list[AccuracyBand]
    methods: dict[str, int]
    #: Null when nothing locked, or when no locked tile had a readable ground centre.
    amplification: AccuracyAmplification | None = None
    #: Null when nothing locked, or when no band edge could be traced on the frame.
    zones: AccuracyZones | None = None
    #: Null when the coverage rule was switched off for the run.
    reach: AccuracyReach | None = None
    cloud: AccuracyCloud | None = None
    #: Ortho-grid geometry, so the client can place tiles and the camera on the layers.
    grid: dict[str, Any]
    pose: dict[str, Any]
    warnings: list[str]
    tiles: list[AccuracyTile]


class CorrectionReport(ApiModel):
    """Stage E's own verdict on itself.

    ★ ``accepted`` IS THE GATE. It is false when the refined pose measured WORSE than
    the raw one — validated across a 15-case study to catch 3/3 regressions with no
    false rejects. A client must not present a refused correction as an improvement.
    """

    n_pseudo_gcps: int
    position_shift_m: float
    azimuth_deg: float
    tilt_down_deg: float
    reproj_median_px: float
    before_m: dict[str, float]
    after_pose_m: dict[str, float]
    after_full_m: dict[str, float]
    residual_field: bool
    free_focal: bool
    accepted: bool
    gate_reason: str


class SolutionEntry(ApiModel):
    """One candidate answer, scored on the same tiles as every other."""

    key: SolutionKey
    label: str
    #: The colour the map pin and the legend share, so a pin needs no key.
    colour: str
    available: bool
    #: ★ Measured on tiles the fit never saw (spatially blocked, buffered folds).
    #: Where false, the number restates the fit rather than testing it — and the
    #: ``note`` says so.
    held_out: bool
    note: str
    tiles: int
    all_m: float | None
    #: ★ READ THIS ONE. A correction can halve the median and still make the worst
    #: places worse.
    p95_m: float | None
    #: Share of all the error carried by the worst fifth of the scene.
    worst20_share: float | None
    bands: dict[str, float | None]


class SolutionRow(ApiModel):
    """One band of the comparison grid: the same distance band across every stage."""

    band: str
    values: dict[str, float | None]


class SolutionsRead(ApiModel):
    """The comparison — what makes choosing a correction an informed decision."""

    corrected_at: datetime
    use_residual_field: bool
    free_focal: bool
    #: The winner on the all-band median, held out where it matters. ★ Genuinely not
    #: the same stage every time, and sometimes ``raw`` — meaning: do not correct.
    best: SolutionKey
    rows: list[SolutionRow]
    entries: list[SolutionEntry]
    stage_f: dict[str, Any]
    warnings: list[str]
    basemap_caveat: str


class SuggestRegion(ApiModel):
    """A region to put the next control point in, and why."""

    rank: int
    u: float
    v: float
    half_px: int
    #: ★ THE NUMBER THAT MATTERS — not where the box is, but how much predicted error
    #: a point there would remove. When it goes small, stop adding points.
    cut_pct: float
    score: float
    range_m: float
    slope: float
    reasons: list[str]
    short: str


class SuggestionsRead(ApiModel):
    suggested_at: datetime
    criterion: Literal["ground", "dopt"]
    gcps_used: int
    #: True when a Stage D measurement weighted the score toward the measured error.
    measured: bool
    max_range_m: float | None
    best_cut_pct: float
    stop_below_pct: float
    verdict: Literal["converged", "keep_going"]
    regions: list[SuggestRegion]


class BasePoseRead(ApiModel):
    """Which pose this photograph's measurements are taken FROM.

    ★ WHY IT MATTERS TO THE READER. After a correction is adopted, the next measurement
    starts from that pose — so its error is what the correction LEFT, not the error the
    control points alone produce. Two readings of "4 m" that answer different questions
    have to be distinguishable, and this is what distinguishes them.
    """

    source: Literal["gcps", "adopted"]
    #: Which stage the adopted pose came from — null while measuring from the GCPs.
    from_stage: SolutionKey | None
    adopted_at: datetime | None
    #: How many refinements deep. 0 = the control-point solve.
    generation: int


class HeatmapVersion(ApiModel):
    """One archived measurement — an entry in the heat-map version history.

    ★ WHY A HISTORY EXISTS AT ALL. The loop re-measures after every control point, so
    the useful question stops being "how wrong is it" and becomes "is it improving, and
    where". Answering that needs the earlier runs still to exist, with the numbers that
    describe them and the layers they produced.
    """

    version: str
    measured_at: datetime
    provider: str
    params: dict[str, Any]
    tiles_total: int
    tiles_locked: int
    match_rate: float
    #: The RAW measured median — what the pose in force was found to be wrong by.
    median_error_m: float | None
    bands: list[AccuracyBand]
    #: How the tiles were matched — phase correlation, MI rescue, fine sub-tiles,
    #: and the affine rescue when it was asked for.
    methods: dict[str, int] = Field(default_factory=dict)
    #: What this run's geometry did to terrain-height error. Carried through the
    #: history because a re-measure after a new frame can change the geometry, and
    #: comparing two medians without it would compare two different scenes.
    amplification: AccuracyAmplification | None = None
    #: The zones as they were on THIS run's frame — an older version's photo overlay.
    zones: AccuracyZones | None = None
    reach: AccuracyReach | None = None
    cloud: AccuracyCloud | None = None
    #: The ortho grid this run produced, including `web_bounds` — what lets an OLDER
    #: version be drawn on the satellite pane, not just in the comparison panel.
    grid: dict[str, Any] = Field(default_factory=dict)
    pose: dict[str, Any]
    warnings: list[str]
    #: Present once this run was corrected: the winning stage and its numbers.
    corrected: dict[str, Any] | None = None
    #: The correction's own verdict on itself, when there was one.
    gate: dict[str, Any] | None = None
    #: Layer names available at ``…/history/{version}/layers/{name}``.
    layers: list[str] = Field(default_factory=list)


class AccuracyState(ApiModel):
    """Everything stored for one photograph — what the page loads on arrival.

    ★ Read from DISK, not from the run registry, so a result outlives an API restart.
    """

    image_id: UUID
    measurement: AccuracyMeasurement | None
    correction: CorrectionReport | None
    solutions: SolutionsRead | None
    suggestions: SuggestionsRead | None
    #: The stage this photograph stands on, once the surveyor has chosen one.
    adoption: AdoptionRead | None
    #: The pose the measurements are taken from. Survives a re-measurement, unlike the
    #: adoption record — see :class:`BasePoseRead`.
    base_pose: BasePoseRead
    #: How the raw pose is solved from the control points.
    solve_options: SolveOptionsRead
    #: Layer names available at ``/accuracy/images/{id}/layers/{name}``.
    layers: list[str]
    report_available: bool
    correction_available: bool
    active_run: AccuracyRunStatus | None = None


class PixelQueryAnswer(ApiModel):
    """One stage's answer for the queried pixel."""

    key: SolutionKey
    lat: float
    lon: float
    elevation_m: float
    #: Stage F only: which base its subtraction was applied to.
    base: str | None = None


class PixelQueryRead(ApiModel):
    """★ EVERY answer, never just the winner — the disagreement is the information.

    Drop one pin per answer on a feature you recognise; the pin that lands on it is the
    stage that works for this scene.
    """

    answers: list[PixelQueryAnswer]
    best: SolutionKey
