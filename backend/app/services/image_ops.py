"""``image_ops`` — pure pixel operations on encoded image bytes (resize / rescale).

★ **This module is deliberately free of DB, storage, and FastAPI.** It is a small set
of pure functions over ``bytes``: give it the encoded bytes of a JPEG/PNG/TIFF and a
target size, get back the encoded bytes of the resized image plus its actual dimensions.
That keeps the arithmetic that governs a *survey-critical* rescale (a wrong scale factor
corrupts every GCP on the photo) testable with no infrastructure at all, and lets both
the upload path and the ``/rescale`` endpoint share exactly one resizer.

The resize is Pillow's ``Image.resize((w, h), LANCZOS)`` — the highest-quality resampling
filter Pillow ships — re-encoded in the **same container format** the source used, so a
JPEG stays a JPEG and a PNG stays a PNG. GeoTIFFs are refused *upstream* (a resize drops
the geotransform); this module never has to reason about georeferencing.
"""

from __future__ import annotations

from io import BytesIO

from app.core.exceptions import ValidationError

__all__ = ["MAX_DIMENSION", "MAX_PIXELS", "dimensions_of_bytes", "resize_image_bytes"]

#: Per-axis ceiling. 20000 px is comfortably past any real survey photograph or drone
#: frame, and it is the same bound the ``ImageRescaleRequest`` schema enforces on the
#: wire — restated here because the upload path reaches this helper through raw ``Form``
#: fields that pydantic never range-checks.
MAX_DIMENSION: int = 20000

#: Total-pixel ceiling — Pillow's decompression-bomb budget. 200 MP is ~20000×10000, a
#: generous cap that still refuses a target crafted to exhaust memory (``w*h*channels``
#: bytes are allocated by ``resize``). Below the two per-axis caps this is what stops a
#: ``19999×19999`` (≈400 MP) target.
MAX_PIXELS: int = 200_000_000

#: ``mime hint`` → Pillow save format, for the rare source Pillow opens without a
#: ``.format`` (raw streams). The opened image's own ``.format`` is preferred; this is
#: only the fallback.
_MIME_TO_FORMAT = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/tiff": "TIFF",
    "image/tif": "TIFF",
}


def _validate_target(width: int, height: int) -> None:
    """Guard the target size — a clean 422, never a 500 out of Pillow."""
    if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
        raise ValidationError(
            f"target size {width}x{height} is out of range; each axis must be in "
            f"[1, {MAX_DIMENSION}]."
        )
    if width * height > MAX_PIXELS:
        raise ValidationError(
            f"target size {width}x{height} is {width * height} pixels, over the "
            f"{MAX_PIXELS}-pixel limit."
        )


def dimensions_of_bytes(data: bytes) -> tuple[int, int]:
    """Read ``(width, height)`` from encoded image bytes — header only, no full decode.

    Raises:
        ValidationError: the bytes are not a decodable image.
    """
    from PIL import Image as PILImage

    try:
        with PILImage.open(BytesIO(data)) as im:
            width, height = im.size
    except Exception as exc:  # noqa: BLE001 — any decode failure is bad input, not a 500
        raise ValidationError(
            "the image could not be read; its dimensions could not be determined."
        ) from exc
    return int(width), int(height)


def resize_image_bytes(
    data: bytes, width: int, height: int, *, mime: str | None = None
) -> tuple[bytes, int, int]:
    """Resize encoded image bytes to exactly ``width``×``height``, same format.

    Args:
        data: The encoded source bytes (JPEG/PNG/TIFF).
        width: Target width in pixels. Guarded to ``[1, MAX_DIMENSION]``.
        height: Target height in pixels.
        mime: The declared MIME, used only to pick the save format when Pillow opens the
            source without a ``.format`` of its own.

    Returns:
        ``(encoded_bytes, actual_width, actual_height)`` — the re-encoded image and the
        dimensions it actually has (``Image.resize`` to an exact size makes these equal
        to the requested ones, but the caller records what the file *is*, not what was
        asked for).

    Raises:
        ValidationError: the target is out of range / over the pixel budget, or the
            source bytes cannot be decoded. **Never a bare 500** — a rescale of a bad
            file is bad input.
    """
    from PIL import Image as PILImage

    _validate_target(width, height)

    try:
        with PILImage.open(BytesIO(data)) as im:
            fmt = (im.format or _MIME_TO_FORMAT.get((mime or "").lower()))
            if fmt is None:
                raise ValidationError(
                    "could not determine the image format to re-encode the resized image."
                )
            im.load()
            resized = im.resize((width, height), PILImage.LANCZOS)

            save_kwargs: dict[str, object] = {}
            if fmt == "JPEG":
                # JPEG has no alpha channel and no palette; a resized RGBA/P image must be
                # flattened or Pillow raises on save.
                if resized.mode in ("RGBA", "LA", "P"):
                    resized = resized.convert("RGB")
                save_kwargs["quality"] = 90

            out = BytesIO()
            resized.save(out, format=fmt, **save_kwargs)
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 — a decode/encode failure is bad input
        raise ValidationError(
            "the image could not be resized; it may be corrupt or an unsupported format."
        ) from exc

    return out.getvalue(), int(resized.width), int(resized.height)
