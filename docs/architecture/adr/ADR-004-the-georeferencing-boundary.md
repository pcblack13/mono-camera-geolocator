# ADR-004 — `ai_engine` ends at pixels; `gis` is the only birthplace of lat/lon

**Status:** Accepted
**Normative record:** `CONTRACT.md` L3, L4, §10.5 (the CI greps) · `00-overview.md` §2.1 calls this
*"the most important line in the system"*

---

## Context

This system's characteristic bug is a **frame confusion**: a number that is metres treated as degrees,
a 3857 metre treated as a true metre, an image pixel treated as a window pixel, a `(lat, lon)` handed
to a function expecting `(x, y)`. These bugs do not crash. They produce a coordinate that is wrong by
108 metres and looks entirely plausible in a CSV.

`CONTRACT.md` §13.1 names one such case for `gis` alone: *"`crop_to_bbox` folds the offset into the
origin — **this is the test that catches the ~108 m error that crashes nothing**."*

If both CV code and geodesy code may touch coordinates, every module becomes a place where the
confusion can happen, and no test can be pointed at the boundary because there is no boundary.

## Decision

**One line, drawn through the middle of the system:**

> **`ai_engine` begins at pixels and ends at pixels. `gis` is the only module that knows what a CRS
> is.**

**L3 — `ai_engine` does not know what a CRS is.** No pyproj, no EPSG, no `lat`, no `lon`, no `z/x/y`.
It receives a `CandidateWindow` carrying an **opaque** `geotransform` and `crs` string which it
**round-trips unchanged** and never interprets. It returns pixel coordinates and **pixel** covariance.

**L4 — `gis` does not know what a descriptor is.** No SIFT, no ratio test, no RANSAC, no homography
estimation. It ends at pixels plus a geotransform.

**`gis/crs.py` is the only module that may import `pyproj` or `osgeo.osr`** — `always_xy=True`,
always. **`gis/accuracy.py` is the single producer of `AccuracyEstimate`** — the module that must never
see a degree or a 3857 metre.

**Enforced by CI greps (§10.5) and import-linter**, not by review. CI additionally greps for
`from_crs` **outside `gis/crs.py`** — the `always_xy` pitfall is made *unreachable* rather than
documented.

## Rationale

**A boundary you can grep for is a boundary that survives.** L3 and L4 are each one regex. A reviewer
who forgets the rule is caught by the build; a new contributor learns it from a failure, not from a
1600-line document they have not read yet.

**It puts the conversion in exactly one place, so it can be tested to death.** `gis/tiles.py` is pure
numpy + stdlib, no I/O, no optional deps, and carries golden values against known OSM tile numbers
plus a `lonlat → tile → lonlat` round-trip under 1e-9°. That is only possible because it is the *only*
code doing the conversion.

**Units and frames in the names, everywhere.** §13.4 rule 6 requires public functions to state units
and frames in their docstrings (`px` vs `m` vs `deg`; image frame vs window frame vs EPSG:4326).
**Most bugs in this system will be a frame confusion; naming is the cheapest defence.**

**Under `SCOPE.md`, the line matters more, not less.** With matching deferred, `ai_engine` contributes
almost nothing to this build — but the manual GCP path runs **the same conversion chain**
(`image px → map click → EPSG:4326 → geography(Point,4326)`), and `gis/accuracy.py` is now the *sole*
producer of the accuracy number, sourced from imagery GSD and click precision rather than from a
homography. **The boundary is load-bearing today even though the CV side of it is empty.**

## Consequences

**Positive.**
- The ~108 m class of bug has exactly one place to live, and a golden test sitting on it.
- `ai_engine` is testable with pure synthetic pixel data — no geodesy, no network, no imagery.
- Swapping pyproj for `osgeo.osr` for closed-form NumPy is a `gis/crs.py` change (§11.3), invisible
  to every caller.

**Negative, stated honestly.**
- The `CandidateWindow.geotransform` being **opaque to `ai_engine`** means the engine cannot sanity-
  check it; a garbage geotransform is `gis`'s bug to catch, and `gis` must catch it.
- Some conversions cross the line and need an owner. `CONTRACT.md` §14 F-98 records what happens when
  they do not: `ai_engine` emitted a **window-local** yaw while `camera_poses` required 0=North, and
  **no module owned the conversion**. The fix was `gis/pose.py` (grid convergence included), not a
  relaxation of the rule.
- Two dataclasses named `BBox` / `LonLat` exist on either side of the line with different shapes.
  `backend/app/services/_adapters.py` is the **only** place a wire type becomes a `gis` type — because
  somebody must convert, and §14 F-47 records that v1.0 assigned nobody.

## Alternatives considered

**Rejected — let `ai_engine` return lat/lon directly.** It is one import of pyproj and it looks
convenient. It puts geodesy in the CV package, makes the CV package untestable without a projection
stack, and scatters the frame confusion across every extractor and matcher. The bug we most fear would
gain a dozen new homes.

**Rejected — a shared `coordinates` package both sides import.** Same problem in a new wrapper: both
sides would then know about CRSs, and the grep gate would have nothing to grep for. The line would
exist in prose only.

**Rejected — document the rule and enforce it in code review.** Reviewers are the least reliable
enforcement mechanism available, and this rule is violated by *adding one import*, silently, in a PR
about something else.

## Related

- ADR-001 — the packaging that makes this enforceable.
- ADR-009 (`00-overview.md` §7) — the GDAL/rasterio adapter; `gis/rasterio_shim.py` in the contract.
- `CONTRACT.md` §4.18 (`gis.tiles`), §4.20 (`gis.accuracy`), §10.5 (the greps), §13.1 IU-09.
