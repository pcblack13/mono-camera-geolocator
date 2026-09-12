"""GeoJSON export — stdlib ``json``, ALWAYS available (CONTRACT.md §4.21, 40-imagery §8.3).

**RFC 7946, strictly.** Two consequences that are easy to get wrong and are both asserted
by IU-13:

* **Positions are ``[lon, lat]``** — longitude first. RFC 7946 §3.1.1.
* **There is no ``crs`` member.** It existed in the 2008 draft and was REMOVED by RFC 7946
  §4, which fixes the coordinate reference system as WGS 84 (CRS84) for all conforming
  documents. Emitting one is non-conformant *and* ignored, which is the worst pair: it
  looks like it did something. We therefore always emit EPSG:4326 and report a requested
  ``target_srid`` as unhonoured rather than pretending.

Provenance rides in a top-level ``metadata`` foreign member. RFC 7946 §6.1 explicitly
permits foreign members on any GeoJSON object; parsers that do not understand it ignore it
harmlessly, and it is the least-bad place for information that must not be lost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gis.exports.base import (
    ACCURACY_DECIMALS,
    ExportBundle,
    ExportContext,
    ExportWriter,
    format_timestamp,
    include_attribution,
    provenance_for,
    record_provenance,
)

__all__ = ["GeoJsonExportWriter"]


def _round(value: float | None, decimals: int) -> float | None:
    """Round for JSON, preserving None.

    ★ ``None`` stays ``None`` so it serialises to an explicit JSON ``null``. The key is
    always emitted; a missing elevation is *visibly* missing rather than absent (§4.27).
    """
    if value is None:
        return None
    return round(float(value), decimals)


class GeoJsonExportWriter(ExportWriter):
    """RFC 7946 FeatureCollection, one Point Feature per GCP. Stdlib only."""

    format_id = "geojson"
    label = "GeoJSON"
    media_type = "application/geo+json"
    file_extension = ".geojson"
    is_stdlib_only = True
    supports_target_srid = False
    supports_imagery = False

    def is_available(self) -> tuple[bool, str | None]:
        """Always ``(True, None)``.

        Returns:
            ``(True, None)``.
        """
        return (True, None)

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write an RFC 7946 FeatureCollection.

        Args:
            ctx: The assembled context.
            out_path: Destination ``.geojson``.

        Returns:
            The bundle.

        Raises:
            ExportError: If a record carries a non-finite coordinate.
        """
        self._prepare(ctx, out_path)

        attribution_on = include_attribution()
        prov = provenance_for(ctx)
        warnings: list[str] = []
        warnings.extend(self._srid_warning(ctx))
        warnings.extend(self._attribution_warnings(ctx, included=attribution_on))

        features: list[dict[str, Any]] = [
            self._feature(ctx, index) for index in range(len(ctx.gcps))
        ]

        document: dict[str, Any] = {
            "type": "FeatureCollection",
            # ★ NO "crs" member. RFC 7946 §4 removed it; CRS84 is implied and mandatory.
            "features": features,
            "metadata": {
                key: value
                for key, value in ctx.metadata_items(
                    include_attribution_value=attribution_on
                )
            },
        }
        document["metadata"]["accuracy_statement"] = ctx.accuracy_statement()
        document["metadata"]["coordinate_order"] = "lon,lat"
        document["metadata"]["confidence_scale"] = "0-100"
        document["metadata"]["confidence_basis"] = prov.confidence_basis

        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")

        return self._bundle(out_path, warnings)

    def _feature(self, ctx: ExportContext, index: int) -> dict[str, Any]:
        """Build one Point Feature.

        The position carries elevation as an optional third element when — and only when —
        an elevation producer actually ran (RFC 7946 §3.1.1 permits it). ``properties``
        always carries ``elevation_m`` explicitly, ``null`` included, because the position
        array cannot express "unknown" and the properties can.
        """
        gcp = ctx.gcps[index]
        # ★ SCOPE.md §5 — per ROW, not per export. An automatic coordinate in a mixed export
        #   must not inherit a manual row's "observed" label.
        prov = record_provenance(gcp, ctx)

        position: list[float] = [
            round(gcp.lon, 8),
            round(gcp.lat, 8),
        ]
        if gcp.elevation_m is not None:
            position.append(round(float(gcp.elevation_m), ACCURACY_DECIMALS))

        properties: dict[str, Any] = {
            "gcp_id": gcp.gcp_id,
            "code": gcp.code,
            "label": gcp.label,
            "elevation_m": _round(gcp.elevation_m, ACCURACY_DECIMALS),
            "elevation_source": gcp.elevation_source,
            "pixel_col": _round(gcp.pixel_col, 3),
            "pixel_row": _round(gcp.pixel_row, 3),
            "satellite_pixel_x": _round(gcp.satellite_pixel_x, 3),
            "satellite_pixel_y": _round(gcp.satellite_pixel_y, 3),
            "confidence": _round(gcp.confidence, 2),
            # ★ SCOPE.md §5 — the two facts that stop a consumer from mistaking a
            #   surveyor's judgement for a computed score, or an observation for an
            #   inference. Derived from the row's own source; never fabricated.
            "confidence_basis": prov.confidence_basis,
            "source": prov.source,
            "coordinate_kind": "observed" if prov.is_observation else "inferred",
            "method": ctx.method,
            "horizontal_accuracy_m": _round(gcp.horizontal_accuracy_m, ACCURACY_DECIMALS),
            "total_ce90_m": _round(gcp.total_ce90_m, ACCURACY_DECIMALS),
            "relative_ce90_m": _round(gcp.relative_ce90_m, ACCURACY_DECIMALS),
            "georef_ce90_m": _round(gcp.georef_ce90_m, ACCURACY_DECIMALS),
            "accuracy_dominant_term": gcp.accuracy_dominant_term,
            "residual_px": _round(gcp.residual_px, 3),
            "manually_adjusted": gcp.manually_adjusted,
            "adjustment_offset_m": _round(gcp.adjustment_offset_m, ACCURACY_DECIMALS),
            "landmark_kind": gcp.landmark_kind,
            "provider": ctx.provider_name,
            "imagery_captured_at": format_timestamp(ctx.imagery_captured_at) or None,
            "rmse_m": _round(ctx.rmse_m, ACCURACY_DECIMALS),
        }
        if include_attribution():
            properties["attribution"] = ctx.attribution
            properties["terms_url"] = ctx.terms_url

        return {
            "type": "Feature",
            "id": gcp.gcp_id,
            "geometry": {"type": "Point", "coordinates": position},
            "properties": properties,
        }
