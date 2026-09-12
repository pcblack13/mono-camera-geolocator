"""Tile-proxy support — the one place ``gis`` imagery errors become HTTP outcomes.

★ **EXEMPT** like :mod:`app.api.deps` / :mod:`app.api.presenters`: it is ``app.api`` but not
``app.api.v1``, so it may import ``gis`` — which a router may not. The tile/static routes
(endpoints 52, 53) are IO and explicitly exempt from L5, but they still must translate
``gis.errors`` at the boundary, and that translation cannot live in the router. Another addition
to §2.4's tree, flagged in IU-21's report.

★ **204 on a valid tile address with no imagery** (ocean, gap) is deliberate — not an error,
and Leaflet renders nothing (§7.2). A ``TileNotAvailableError`` is *not an error* (§6.3).
"""

from __future__ import annotations

from typing import Any

from starlette.responses import Response

from app.core.exceptions import (
    ProviderInvalidResponse,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderUpstreamError,
    StaticImageTooLarge,
    ZoomOutOfRange,
)

__all__ = ["serve_static", "serve_tile"]


def _basemap_kind(kind: str) -> Any:
    from gis.types import BasemapKind

    return BasemapKind(kind)


def serve_tile(service: Any, provider: str, z: int, x: int, y: int, *, kind: str) -> Response:
    """Proxy one tile → ``200`` binary or ``204`` (valid address, no imagery)."""
    from gis.errors import (
        ProviderNotConfiguredError,
        ProviderRateLimitError,
        ProviderTransportError,
        TileNotAvailableError,
        TileOutOfRangeError,
    )

    try:
        data, media_type = service.get_tile_bytes(provider, z, x, y, kind=_basemap_kind(kind))
    except TileNotAvailableError:
        return Response(status_code=204)  # ★ not an error — no imagery here.
    except TileOutOfRangeError as exc:
        raise ZoomOutOfRange(f"Tile {z}/{x}/{y} is outside {provider}'s valid range: {exc}") from exc
    except ProviderRateLimitError as exc:
        retry = getattr(exc, "retry_after", None)
        raise ProviderRateLimited(
            f"{provider} rate-limited the request.",
            headers={"Retry-After": str(int(retry))} if retry else None,
        ) from exc
    except ProviderNotConfiguredError as exc:
        # ★ A CREDENTIAL PROBLEM IS NOT A CRASH, AND MUST NOT ARRIVE AS ONE.
        #   Without this branch the error escapes unhandled and every tile in the
        #   viewport returns a 500 with a stack trace — twenty of them per pan, and the
        #   ACTIONABLE message (which key, which API to enable) buried in server logs the
        #   surveyor never sees. §11.0 makes an explicitly requested unconfigured provider
        #   a 503: the request named this provider, so falling back silently would change
        #   the answer's provenance without saying so.
        raise ProviderNotConfigured(str(exc)) from exc
    except ProviderTransportError as exc:
        raise ProviderUpstreamError(f"{provider} upstream error: {exc}") from exc

    headers = {"X-Imagery-Provider": provider, "Cache-Control": "public, max-age=3600"}
    return Response(content=data, media_type=media_type, headers=headers)


def serve_static(
    service: Any,
    *,
    provider: str | None,
    bbox: tuple[float, float, float, float],
    zoom: int,
    kind: str,
    image_format: str,
) -> Response:
    """Proxy a stitched static chip → ``200`` binary. Over budget → ``422``.

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)``; it is turned into a ``gis.types.BBox``
    here so the router never touches ``gis``.
    """
    from gis.errors import AreaTooLargeError, ProviderTransportError
    from gis.types import BBox as GisBBox

    gis_bbox = GisBBox(west=bbox[0], south=bbox[1], east=bbox[2], north=bbox[3])
    try:
        chip = service.get_static_chip(gis_bbox, zoom, provider_name=provider, kind=_basemap_kind(kind))
    except AreaTooLargeError as exc:
        raise StaticImageTooLarge(
            f"Requested static image exceeds the request-scale budget (LE_MAX_STATIC_*): {exc}. "
            "Use the 202 → GET /jobs/{id} pattern for a job-sized area."
        ) from exc
    except ProviderTransportError as exc:
        raise ProviderUpstreamError(f"{provider or 'default provider'} upstream error: {exc}") from exc

    data = getattr(chip, "rgb_bytes", None) or getattr(chip, "data", None)
    if data is None:
        raise ProviderInvalidResponse("The provider returned a chip with no encodable bytes.")
    media_type = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}.get(image_format, "image/png")
    attribution = getattr(chip, "attribution", None)
    headers = {"X-Imagery-Provider": str(getattr(chip, "provider_name", provider or ""))}
    if attribution:
        headers["X-Imagery-Attribution"] = str(attribution)
    return Response(content=bytes(data), media_type=media_type, headers=headers)
