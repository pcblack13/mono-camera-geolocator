"""PDF report — reportlab, DEGRADES (CONTRACT.md §4.21, 40-imagery §8.6).

The client-facing artifact: the file that gets emailed, printed, filed, and believed. Three
pages — summary, GCP table, provenance — on A4 portrait via reportlab platypus.

Two things here are not cosmetic:

★ **The method badge is the first thing on page 1.** It determines how much to trust
everything below it, so it is not buried in a metadata appendix.

★ **The accuracy statement is GENERATED from the context, never hand-written per template**
(:meth:`ExportContext.accuracy_statement`). A report that quietly omits *"this is ±15 m"*
is the document that gets forwarded to a client and believed.

★ **The map figure is omitted, with an explanation, when ``ctx.chip is None``** — which is
what a provider forbidding derivative export looks like from in here (§11.5). Coordinates
still export; pixels do not. The omission goes in :attr:`ExportBundle.warnings` and on the
page, never silently.

★ **Call-time bound** (§11.3): ``reportlab`` is imported inside
:meth:`PdfReportWriter.write`. Pillow is in this package's base install and is bound at
call time too, only because there is no reason to pay an image library's import on
``import gis.exports``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from gis.exports.base import (
    ACCURACY_DECIMALS,
    CONFIDENCE_DECIMALS,
    LONLAT_DECIMALS,
    ExportBundle,
    ExportContext,
    ExportWriter,
    format_number,
    format_timestamp,
    include_attribution,
    missing_dependency_reason,
    record_provenance,
)

if TYPE_CHECKING:
    from gis.types import SatelliteChip

__all__ = ["PdfReportWriter"]


_METHOD_BADGE: Final[dict[str, str]] = {
    "direct_georeference": "DIRECT GEOREFERENCE — coordinates read from the source file",
    "assisted": "MANUAL SURVEY — coordinates placed by a surveyor",
    "matched": "AUTOMATIC MATCH — coordinates inferred by image matching",
}

_CONFIDENCE_HIGH: Final[float] = 80.0
_CONFIDENCE_MEDIUM: Final[float] = 50.0

_MAX_FIGURE_PX: Final[int] = 1600
"""Longest edge of the embedded map figure. A 4000px chip in a PDF is a 30 MB email
attachment nobody can open; 1600px is beyond what A4 at 300 dpi can resolve anyway."""


class PdfReportWriter(ExportWriter):
    """The GCP report. Requires reportlab; degrades to ``(False, "requires reportlab")``."""

    format_id = "pdf"
    label = "PDF Report"
    media_type = "application/pdf"
    file_extension = ".pdf"
    is_stdlib_only = False
    supports_target_srid = False
    supports_imagery = True

    def is_available(self) -> tuple[bool, str | None]:
        """Report whether ``reportlab`` can be bound here.

        reportlab is NOT installed on the dev machine (§0.1), so this MUST degrade rather
        than crash the export endpoint.

        Returns:
            ``(True, None)`` or ``(False, "requires reportlab")``. Never raises.
        """
        missing = missing_dependency_reason("reportlab")
        if missing is not None:
            return (False, missing)
        return (True, None)

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Render the report.

        Args:
            ctx: The assembled context.
            out_path: Destination ``.pdf``.

        Returns:
            The bundle. ``warnings`` says so when the map figure was omitted.

        Raises:
            ExportError: If reportlab is absent, or a record is not serialisable.
        """
        self._prepare(ctx, out_path)

        # ★ CALL-TIME BINDING (§11.3).
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Image,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        attribution_on = include_attribution()
        warnings: list[str] = []
        warnings.extend(self._srid_warning(ctx))
        warnings.extend(self._attribution_warnings(ctx, included=attribution_on))

        styles = getSampleStyleSheet()
        body = ParagraphStyle(
            "LEBody",
            parent=styles["BodyText"],
            alignment=TA_LEFT,
            fontSize=9,
            leading=12,
        )
        badge = ParagraphStyle(
            "LEBadge",
            parent=styles["Heading2"],
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#1a3a5c"),
        )
        small = ParagraphStyle(
            "LESmall", parent=styles["BodyText"], fontSize=7.5, leading=10
        )

        story: list[Any] = []

        # ── Page 1 — summary ────────────────────────────────────────────────
        story.append(Paragraph(f"{ctx.project_name} — GCP Report", styles["Title"]))
        story.append(
            Paragraph(
                _METHOD_BADGE.get(
                    ctx.method, f"UNRECOGNISED METHOD ({ctx.method}) — accuracy unknown"
                ),
                badge,
            )
        )
        story.append(Spacer(1, 4 * mm))

        summary_rows = [
            ("Ground control points", str(len(ctx.gcps))),
            ("Coordinate reference system", "EPSG:4326 (WGS 84)"),
            ("Source image", ctx.image_filename or "—"),
            ("Generated", format_timestamp(ctx.generated_at)),
            ("Export id", str(ctx.export_id)),
        ]
        story.append(self._kv_table(summary_rows, Table, TableStyle, colors, mm))
        story.append(Spacer(1, 5 * mm))

        story.append(Paragraph("Accuracy", styles["Heading3"]))
        story.append(Paragraph(ctx.accuracy_statement(), body))
        story.append(Spacer(1, 5 * mm))

        figure, figure_note = self._map_figure(ctx, Image, mm)
        if figure is None:
            warnings.append(figure_note)
            story.append(Paragraph("Map figure", styles["Heading3"]))
            story.append(Paragraph(figure_note, body))
        else:
            story.append(Paragraph("Map figure", styles["Heading3"]))
            story.append(figure)
            story.append(Paragraph(self._figure_caption(ctx, attribution_on), small))

        # ── Page 2 — the GCP table ──────────────────────────────────────────
        story.append(PageBreak())
        story.append(Paragraph("Ground control points", styles["Heading2"]))
        story.append(Spacer(1, 3 * mm))
        story.append(self._gcp_table(ctx, Table, TableStyle, colors, mm))
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                "An empty cell means the value is genuinely unknown; it never means zero. "
                f"Coordinates are EPSG:4326 decimal degrees at {LONLAT_DECIMALS} decimal "
                "places, longitude before latitude.",
                small,
            )
        )

        # ── Page 3 — provenance ─────────────────────────────────────────────
        story.append(PageBreak())
        story.append(Paragraph("Metadata and provenance", styles["Heading2"]))
        story.append(Spacer(1, 3 * mm))
        story.append(
            self._kv_table(
                [
                    (key.replace("_", " "), value or "—")
                    for key, value in ctx.metadata_items(
                        include_attribution_value=attribution_on
                    )
                ],
                Table,
                TableStyle,
                colors,
                mm,
            )
        )
        if ctx.chip is not None:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Imagery", styles["Heading3"]))
            story.append(
                self._kv_table(
                    self._imagery_rows(ctx), Table, TableStyle, colors, mm
                )
            )
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Accuracy statement", styles["Heading3"]))
        story.append(Paragraph(ctx.accuracy_statement(), body))

        doc = SimpleDocTemplate(
            str(out_path),
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=20 * mm,
            title=f"{ctx.project_name} — GCP Report",
            author=f"LandExplorer {ctx.software_version}".strip(),
            subject="Ground control point survey report",
        )
        footer = self._make_footer(ctx, attribution_on, mm, colors)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)

        return self._bundle(out_path, warnings)

    # ── internals ───────────────────────────────────────────────────────────

    def _kv_table(
        self,
        rows: list[tuple[str, str]],
        table_cls: Any,
        table_style_cls: Any,
        colors: Any,
        mm: float,
    ) -> Any:
        """Render a two-column key/value table."""
        table = table_cls(
            [[key, value] for key, value in rows],
            colWidths=[55 * mm, 119 * mm],
            hAlign="LEFT",
        )
        table.setStyle(
            table_style_cls(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#dddddd")),
                ]
            )
        )
        return table

    def _gcp_table(
        self,
        ctx: ExportContext,
        table_cls: Any,
        table_style_cls: Any,
        colors: Any,
        mm: float,
    ) -> Any:
        """Render the GCP table, colour-banded by confidence.

        The columns are the ones SCOPE.md §3 mandates — Point ID, Image X, Image Y,
        Latitude, Longitude, Confidence — plus the elevation and the headline accuracy,
        because a control point without its accuracy is not a control point.
        """
        header = [
            "ID",
            "Image X",
            "Image Y",
            "Longitude",
            "Latitude",
            "Elev (m)",
            "Conf",
            "CE90 (m)",
        ]
        data: list[list[Any]] = [header]
        for gcp in ctx.gcps:
            data.append(
                [
                    gcp.code or gcp.label or gcp.gcp_id[:8],
                    format_number(gcp.pixel_col, 1),
                    format_number(gcp.pixel_row, 1),
                    format_number(gcp.lon, LONLAT_DECIMALS),
                    format_number(gcp.lat, LONLAT_DECIMALS),
                    # ★ None -> an explicit empty cell. Never 0, never "None".
                    format_number(gcp.elevation_m, ACCURACY_DECIMALS),
                    format_number(gcp.confidence, CONFIDENCE_DECIMALS),
                    format_number(gcp.total_ce90_m, ACCURACY_DECIMALS),
                ]
            )

        table = table_cls(
            data,
            colWidths=[22 * mm, 18 * mm, 18 * mm, 27 * mm, 27 * mm, 20 * mm, 16 * mm, 20 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        style: list[tuple[Any, ...]] = [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        # Colour-band the confidence cell to match the KML writer, so two exports of one
        # dataset never disagree about the same point.
        for index, gcp in enumerate(ctx.gcps, start=1):
            # ★ SCOPE.md §5 — band each row by ITS OWN confidence basis, so a row whose
            #   source we cannot explain is greyed rather than coloured like the export.
            prov = record_provenance(gcp, ctx)
            if prov.confidence_basis == "unknown":
                colour = colors.HexColor("#eeeeee")
            elif gcp.confidence >= _CONFIDENCE_HIGH:
                colour = colors.HexColor("#d6f0d6")
            elif gcp.confidence >= _CONFIDENCE_MEDIUM:
                colour = colors.HexColor("#fdeecd")
            else:
                colour = colors.HexColor("#f8d7da")
            style.append(("BACKGROUND", (6, index), (6, index), colour))
        table.setStyle(table_style_cls(style))
        return table

    def _map_figure(self, ctx: ExportContext, image_cls: Any, mm: float) -> tuple[Any, str]:
        """Return ``(flowable, caption)``, or ``(None, explanation)``.

        ★ ``ctx.chip is None`` is the designed signal that the imagery provider's terms
        forbid derivative export (§11.5). The figure is omitted and the reason is stated —
        the coordinates are unaffected.
        """
        if ctx.chip is None:
            return (
                None,
                "The map figure was omitted from this report: no imagery was supplied to "
                "the export. This is the expected result when the imagery provider's "
                "terms do not permit derivative export. The coordinates in this report "
                "are unaffected.",
            )
        try:
            buffer = self._chip_png(ctx.chip)
        except Exception as exc:  # noqa: BLE001 — a bad chip must not lose the report
            return (
                None,
                f"The map figure could not be rendered ({exc}). The coordinates in this "
                "report are unaffected.",
            )

        width, height = ctx.chip.size
        display_width = 174 * mm
        display_height = display_width * (height / width) if width else display_width
        max_height = 150 * mm
        if display_height > max_height:
            display_width *= max_height / display_height
            display_height = max_height
        return (image_cls(buffer, width=display_width, height=display_height), "")

    def _chip_png(self, chip: SatelliteChip) -> Any:
        """Encode the chip's pixels as an in-memory PNG.

        Pillow is in this package's base install (see ``gis/pyproject.toml``), so this is a
        hard dependency of the PDF path only in the sense that reportlab already is.
        """
        from io import BytesIO

        from PIL import Image as PILImage

        image = PILImage.fromarray(chip.image, mode="RGB")
        longest = max(image.size)
        if longest > _MAX_FIGURE_PX:
            scale = _MAX_FIGURE_PX / longest
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                PILImage.LANCZOS,
            )
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)
        return buffer

    def _figure_caption(self, ctx: ExportContext, attribution_on: bool) -> str:
        """Build the figure caption. Attribution here is a licence condition."""
        chip = ctx.chip
        parts = []
        if attribution_on and ctx.attribution.strip():
            parts.append(f"Imagery: {ctx.attribution}.")
        parts.append(f"Provider: {ctx.provider_name}.")
        if chip is not None:
            parts.append(f"Ground sample distance: {format_number(chip.gsd_m, 3)} m/pixel.")
            if chip.zoom is not None:
                parts.append(f"Zoom: {chip.zoom}.")
        captured = format_timestamp(ctx.imagery_captured_at)
        parts.append(f"Captured: {captured or 'not stated by the provider'}.")
        parts.append(f"Retrieved: {format_timestamp(ctx.retrieved_at)}.")
        if attribution_on and ctx.terms_url.strip():
            parts.append(f"Terms: {ctx.terms_url}")
        return " ".join(parts)

    def _imagery_rows(self, ctx: ExportContext) -> list[tuple[str, str]]:
        """Build the imagery detail rows for the provenance page."""
        chip = ctx.chip
        if chip is None:
            return []
        rows = [
            ("ground sample distance", f"{format_number(chip.gsd_m, 3)} m/pixel"),
            ("chip size", f"{chip.size[0]} × {chip.size[1]} px"),
            ("chip crs", chip.crs),
            ("basemap kind", str(chip.kind)),
            (
                "provider georeferencing ce90",
                f"{format_number(chip.georef_ce90_m, ACCURACY_DECIMALS)} m",
            ),
            (
                "authoritative georeferencing",
                "yes" if chip.is_authoritative else "no",
            ),
        ]
        if chip.zoom is not None:
            rows.append(("zoom", str(chip.zoom)))
        if chip.placeholder_fraction > 0:
            rows.append(
                (
                    "placeholder pixels",
                    f"{chip.placeholder_fraction * 100:.1f}% of the figure is a "
                    "placeholder, not imagery",
                )
            )
        return rows

    def _make_footer(
        self, ctx: ExportContext, attribution_on: bool, mm: float, colors: Any
    ) -> Any:
        """Build the per-page footer callback.

        The attribution goes on EVERY page, not just the figure's: a page torn out of a
        report is still a distribution of the derived output.
        """
        credit = ctx.attribution.strip() if attribution_on else ""
        provider = ctx.provider_name

        def _draw(canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(colors.HexColor("#666666"))
            left = doc.leftMargin
            baseline = 12 * mm
            line = f"Imagery: {credit}" if credit else f"Imagery provider: {provider}"
            canvas.drawString(left, baseline, line[:160])
            canvas.drawString(
                left,
                baseline - 4 * mm,
                f"LandExplorer {ctx.software_version} · {format_timestamp(ctx.generated_at)} "
                f"· export {ctx.export_id}"[:160],
            )
            canvas.drawRightString(
                doc.pagesize[0] - doc.rightMargin, baseline, f"Page {doc.page}"
            )
            canvas.restoreState()

        return _draw
