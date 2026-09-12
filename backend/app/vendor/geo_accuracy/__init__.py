"""``geo_accuracy`` — the field tool's measure-and-correct core, VENDORED VERBATIM.

Provenance: ``geolocation_gui/core/`` (the teammate's standalone GUI). Same rule as
``app.vendor.lut_generator``: **fix bugs in its standalone home and re-copy**, never
here. The bridge that feeds it LandExplorer's entities is
``app.services.accuracy_service``.

What it does — the second half of the geolocation pipeline. Stages A–C answer "where
is this pixel?"; these stages answer "and how wrong is that answer?", by measuring the
solve against satellite imagery instead of against field survey:

===========  ==========================  ====================================
Module       Stage                       What it produces
===========  ==========================  ====================================
stage_a      A  pose from GCPs           R, C (SQPnP + LM refine)
stage_b      B  pixel → ray → terrain    X, Y, Z
error_map    D  measure the real error   per-tile (dE, dN) vectors
error_corr…  E  re-solve from that       refined pose + residual field
stage_f      F  choose base, subtract     the local leftover, SNR-shrunk
solutions    —  score all four honestly  cross-validated comparison table
gcp_suggest  —  where the next GCP goes  ranked regions, % error removed
error_map_…  —  offline interactive HTML  one self-contained file
===========  ==========================  ====================================

``stage_a``/``stage_b`` are duplicated by ``app.services.geolocate`` (the port that
serves Auto GCP) exactly as ``lut_generator.pose`` duplicates them — a vendor must be
self-contained and re-copyable, and this copy additionally carries the constrained /
``free_focal`` solve that Stage E's refinement needs.

THE EDITS MADE WHILE COPYING — deliberately minimal, all marked in place:

1. ``from core import …`` → relative imports (a package move, no behaviour).
2. ``matplotlib.tri`` → :mod:`._interp`, a SciPy-backed shim with the same
   construction-raises / masked-outside-the-hull semantics. matplotlib is not a
   backend dependency; SciPy already is. See that module's docstring.
3. ``error_map.fetch_satellite`` takes an injected ``mosaic_writer`` instead of
   calling the tool's own Mapbox client, so imagery flows through
   ``ImageryService`` — provider allow-list, disk cache, usage ledger and offline
   mode all stay in force.

Nothing else was touched: no renamed symbol, no changed default, no reordered step.

★ THE HONESTY THIS CORE ENFORCES, which the API and the UI must not paper over: the
correction carries an ACCEPTANCE GATE (``Correction.report['accepted']``) and can
report that correcting would make things WORSE, in which case the raw pose stands.
``solutions.best_key`` picks the winner on spatially blocked, buffered
cross-validation, and the winner is genuinely not the same stage every time.
"""

from __future__ import annotations

__all__ = [
    "error_correction",
    "error_map",
    "error_map_html",
    "gcp_suggest",
    "geo_io",
    "solutions",
    "stage_a",
    "stage_b",
    "stage_f",
]
