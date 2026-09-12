"""GCP import — reading a KML/KMZ the operator refined in an external viewer.

Two endpoints, deliberately:

* ``POST /projects/{id}/gcps/import/kml/preview``  parse + match, **writes nothing**
* ``POST /projects/{id}/gcps/import/kml/apply``    commit the moves

★ **The split is the safety property, not an ergonomic nicety.** An import edits the
coordinates in a survey deliverable. The preview is where the operator sees which points
move and by how far; the apply is where they consent to it. Collapsing the two into one
call would mean a mis-picked file silently rewrites a project's GCPs.

★ **These are not deferred endpoints.** Everything here runs for real — there is no 501
on this path and no placeholder. The honest limits are stated in the responses: a placemark
that matches nothing is reported unmatched rather than invented into a new GCP, and an
altitude under a non-absolute ``altitudeMode`` is reported rather than written.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api import deps
from app.core.exceptions import ImageTooLarge, ValidationError
from app.schemas.imports import (
    KmlImportApplyRequest,
    KmlImportApplyResponse,
    KmlImportPreview,
)
from app.services.kml_import_service import KmlImportService

__all__ = ["router"]

_log = logging.getLogger("app.api.imports")

router = APIRouter()

#: Largest upload this path accepts, before parsing (8 MiB).
#:
#: ★ A KML of GCPs is small — our own writer emits roughly 2 KB per point, so this holds
#: several thousand of them with room to spare. The cap exists because the alternative is
#: reading an unbounded request body into memory to find out it was never KML. The reader
#: applies its own, separate decompression caps to a KMZ (``gis.imports.kml_reader``).
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    """Read the upload with a hard ceiling.

    Reads one byte past the cap so an oversized file is detected without trusting the
    client-declared ``size``, which is a hint and not a fact.
    """
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ImageTooLarge(
            f"KML upload exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB. A GCP file is "
            "normally a few kilobytes — check you picked the right file."
        )
    if not data:
        raise ValidationError("The uploaded file is empty.")
    return data


@router.post(
    "/projects/{project_id}/gcps/import/kml/preview",
    response_model=KmlImportPreview,
    status_code=status.HTTP_200_OK,
    summary="Preview a KML/KMZ GCP import",
)
async def preview_kml_import(
    project_id: UUID,
    file: Annotated[UploadFile, File(description="A .kml or .kmz file of placemarks.")],
    service: KmlImportService = Depends(deps.get_kml_import_service),
) -> KmlImportPreview:
    """Report what importing this file would change. **Writes nothing.**

    Every placemark in the file appears in exactly one of ``matched``, ``unmatched`` or
    ``skipped``, and every GCP the file did not mention is counted in
    ``untouched_gcp_count`` — so the totals account for the whole project and the whole
    file, and nothing can go missing between them unremarked.
    """
    data = await _read_upload(file)
    preview = await service.preview(project_id=project_id, data=data, filename=file.filename)
    _log.info(
        "kml_import.preview project=%s file=%s matched=%d unmatched=%d skipped=%d",
        project_id,
        file.filename,
        len(preview.matched),
        len(preview.unmatched),
        len(preview.skipped),
    )
    return preview


@router.post(
    "/projects/{project_id}/gcps/import/kml/apply",
    response_model=KmlImportApplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply a previewed KML/KMZ GCP import",
)
async def apply_kml_import(
    project_id: UUID,
    file: Annotated[UploadFile, File(description="The same .kml/.kmz that was previewed.")],
    expected_match_count: Annotated[
        int | None,
        Form(
            ge=0,
            description=(
                "The `matched` count from the preview the operator confirmed. A "
                "disagreement means the file changed between preview and apply and the "
                "import is refused with 409 IMPORT_FILE_CHANGED."
            ),
        ),
    ] = None,
    apply_elevation: Annotated[
        bool,
        Form(
            description=(
                "Write altitudes the file carries, as `elevation_source='manual'` with a "
                "NULL vertical CE90. False moves points horizontally only."
            )
        ),
    ] = True,
    note: Annotated[
        str | None,
        Form(max_length=500, description="Adjustment note stored on every moved GCP."),
    ] = None,
    service: KmlImportService = Depends(deps.get_kml_import_service),
) -> KmlImportApplyResponse:
    """Commit the moves this file implies.

    Each moved GCP goes through the ordinary adjustment path, so ``original_geom`` is
    preserved, ``manually_adjusted`` is set, and ``adjustment_offset_m`` is measured by
    PostGIS in true ground metres. Re-applying the same unchanged file is a no-op: every
    match reports under ``unchanged_count`` and nothing is written.
    """
    data = await _read_upload(file)
    body = KmlImportApplyRequest(
        expected_match_count=expected_match_count,
        apply_elevation=apply_elevation,
        note=note,
    )
    return await service.apply(
        project_id=project_id, data=data, body=body, filename=file.filename
    )
