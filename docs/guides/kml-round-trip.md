# The KML round trip — refining GCP positions in an external viewer

You export this project's ground control points as KML, open the file in whatever mapping
or globe application you own, drag each marker to where *that* program's imagery shows the
feature, save, and import the file back. LandExplorer matches each placemark to the GCP it
came from and moves it.

This exists because no single basemap is best everywhere. The imagery in the workspace map
may be stale, cloudy, or too coarse over a particular site, while a program already on your
desk shows it clearly. The round trip lets your judgement, formed against that other
imagery, land in the deliverable — without this application ever fetching, caching, or
redistributing a pixel of it.

---

## What the loop looks like

1. **Pair the point in the workspace.** Click the landmark in the photo, then the same
   spot on the map. This is what gives the GCP its image pixel — the half a placemark can
   never supply. A rough map click is fine; you are about to refine it.
2. **Export → KML** (or KMZ) from the GCP table's export menu.
3. **Open the file in your viewer.** Move the markers. Save the folder back out as `.kml`
   or `.kmz`.
4. **Import** from the button beside the export menu. Review the preview. Apply.

Steps 2–4 are repeatable. Re-importing a file you did not edit changes nothing.

---

## What the preview shows you, and why it shows all of it

An import edits coordinates in a survey deliverable, so the preview is a required step
rather than a courtesy. Every placemark in your file lands in exactly one of three
buckets, and every GCP the file did not mention is counted separately:

| Section | Meaning |
|---|---|
| **Matched** | Tied to an existing GCP. Shows current position, the file's position, and the distance between them in true ground metres. |
| **Unmatched** | Parsed fine, but no GCP here corresponds to it. **Never created** — see below. |
| **Skipped** | Could not be read as a point at all: no `<Point>`, a malformed coordinate, a `<NetworkLink>`. |
| **Not in this file** | GCPs left exactly as they are. An import is a patch, never a replace. |

If you exported 30 points and 28 come back, the preview names the other two and says why.

Matching is tried in order of how much it can be trusted:

1. **`gcp_id`** — carried in the file's `ExtendedData` if we exported it. An exact round
   trip, not a guess.
2. **`code`** — the point's code, from `ExtendedData` or from the placemark's own `<name>`.
3. **`name`** — the free-text name.

A label that matches **more than one** GCP in the project matches *none* of them, and says
so. Picking one would be a coin flip written into a deliverable. Likewise, two placemarks
cannot both claim the same GCP — the second is reported rather than silently overwriting
the first.

---

## What an import will not do

**It will not create a GCP.** `gcps.pixel_x` and `pixel_y` are `NOT NULL`. A GCP is a
*pairing* — an image pixel bound to a ground coordinate — and a placemark carries only the
ground half. There is no pixel to write and no honest way to invent one. To add a point,
pair it in the workspace against the photo it belongs to.

**It will not recompute accuracy.** The horizontal CE90 on the record was derived from a
known provider's ground sample distance and pointing precision (`gis.accuracy`). Nothing in
an imported file supports recalculating it, so the accuracy columns are left alone. What
*is* recorded is that a human moved the point and by how far: `manually_adjusted`,
`adjustment_offset_m` (measured by PostGIS in true ground metres), and the adjustment note.

**It will not claim to know how wrong an imported height is.** If the file carries an
altitude and you leave the elevation switch on, it is written with
`elevation_source = 'manual'` and `elevation_ce90_m = NULL`. You asserted the height; this
system has no basis for an error bar on it, and `0` would be a lie. Turn the switch off to
move points horizontally and leave Z to the project's DEM — which *does* come with a
vertical CE90.

**It will not honour a non-absolute altitude.** Under `clampToGround` the number beside the
coordinate is a display instruction — "put this on the terrain, whatever the terrain is" —
not a height claim. Those are reported as *altitude ignored* and never written.

**It will not fetch anything.** No reader here resolves a URL or follows a
`<NetworkLink>`. An import reads bytes you uploaded, and nothing else.

---

## Re-importing is safe

A match that resolves to within 1 mm of where the point already is counts as *unchanged*
and is not written. That floor exists because exporting rounds coordinates to a fixed
number of decimals — without it, a round trip that changed nothing would stamp
`manually_adjusted` on every GCP and invent an `adjustment_offset_m`, destroying the one
signal that says a human actually intervened.

When you apply, the count of matches you confirmed is sent back with the file. If the
server re-parses and disagrees, the file changed between preview and apply and the import
is refused with `409 IMPORT_FILE_CHANGED` rather than committing edits nobody reviewed.

---

## On imagery sources — read this once

This feature reads **files**, not imagery. It is format-agnostic and producer-agnostic: OGC
KML 2.2 is an open standard maintained by the Open Geospatial Consortium, and QGIS, ArcGIS,
Garmin and every desktop globe viewer write it. The parser cannot tell which program
produced its input and deliberately does not try — there is no producer sniffing, no
vendor branch, and no database column in which an answer could be recorded.

That is not an oversight; it is what keeps this separate from
[`docs/legal/imagery-terms.md` §1](../legal/imagery-terms.md), which excludes a particular
vendor's globe product as an **imagery provider**. That exclusion is about fetching,
caching and redistributing *their pixels*, and it is unchanged and unweakened by this
feature. Nothing here contacts that service.

What does follow is a limit on what a coordinate from an external viewer *means*. The
program you used showed you imagery this system never saw, with georeferencing accuracy it
cannot inspect. Your placement is a real act of survey judgement and is recorded as such —
the same standing as a click on our own map. It is not evidence for a *tighter* accuracy
claim, and the import does not make one. If a deliverable's accuracy matters, the
highest-confidence path in this product remains your own georeferenced orthophotos
(`local_orthophoto`), whose georeferencing is known because you produced it.

---

## See also

- [`offline-mode.md`](offline-mode.md) — working with no basemap at all
- [`../legal/imagery-terms.md`](../legal/imagery-terms.md) — per-provider terms, and §1 on
  the excluded source
- [`../architecture/SCOPE.md`](../architecture/SCOPE.md) §5 — why every coordinate in this
  build is a direct observation
