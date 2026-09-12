"""Reading survey exchange files the operator supplies — the inverse of ``gis.exports``.

★ **Symmetry with ``gis.exports`` is deliberate.** That package turns our GCPs into a
file; this one turns a file back into records. Keeping them as siblings is what makes the
round trip auditable: the fields ``kml_writer`` emits are the fields ``kml_reader`` looks
for, and a test can assert the loop is lossless without reaching across a layer boundary.

★ **An import never fetches anything.** Every reader here takes ``bytes`` that arrived
from an upload. No reader resolves a URL, follows a ``<NetworkLink>``, or contacts a
provider — so an import cannot become a back door to an imagery source the operator did
not choose (``docs/legal/imagery-terms.md`` §1).

★ **Readers do not decide what a record means.** They produce geometry plus whatever
metadata the file carried, and stop. Matching a placemark to an existing GCP, computing
how far it moved, and deciding whether that movement is plausible are policy questions
that belong to the service layer, which knows about projects, accuracy budgets and the
database. A parser that also decided policy could not be tested against a fixture file.
"""

from __future__ import annotations

from gis.imports.kml_reader import (
    KmlReadResult,
    PlacemarkRecord,
    SkippedPlacemark,
    read_kml_bytes,
)

__all__ = [
    "KmlReadResult",
    "PlacemarkRecord",
    "SkippedPlacemark",
    "read_kml_bytes",
]
