"""Elevation from a Copernicus DEM service (§4.27). Opt-in, keyed, online.

★ NOT a default. ``LE_ELEVATION_PROVIDER=copernicus_dem`` + ``LE_COPERNICUS_DEM_URL``.

Unconfigured means ``is_configured() -> False`` and the provider self-skips — never a
crash and never a silent zero (L11).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, ClassVar, Final

from gis.elevation.base import ElevationProvider, ElevationSample
from gis.errors import (
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTransportError,
)
from gis.types import LonLat

__all__ = ["CopernicusDemProvider"]

_log = logging.getLogger("gis.elevation.copernicus_dem")

_COPERNICUS_VERTICAL_CE90_M: Final[float] = 6.6
"""Copernicus GLO-30's published vertical accuracy, CE90 metres.

The mission specifies < 4 m LE90 for GLO-30; the value used here is deliberately more
conservative because we sample a resampled service rather than the source tiles, and
because a reported error bar should not be tighter than our knowledge of the pipeline that
produced it.
"""

_BATCH_SIZE: Final[int] = 100
"""Points per request. Batching is the whole reason ``sample`` takes a sequence."""


class CopernicusDemProvider(ElevationProvider):
    """Samples elevation from a Copernicus DEM HTTP service.

    ★ KEYED · ONLINE · opt-in. Construction never raises and never touches the network.
    """

    name: ClassVar[str] = "copernicus_dem"

    def __init__(
        self,
        service_url: str = "",
        *,
        api_key: str = "",
        timeout_s: float = 15.0,
        user_agent: str = "LandExplorer/1.0 (+https://example.invalid)",
    ) -> None:
        """Construct the provider. NEVER raises on a missing URL or key.

        Args:
            service_url: The DEM service endpoint. ``LE_COPERNICUS_DEM_URL``. Empty means
                unconfigured.
            api_key: Optional bearer token, if the deployment's service needs one.
            timeout_s: Per-request timeout in seconds.
            user_agent: Sent on every request. Operators should set a real contact.
        """
        self._service_url = service_url.strip()
        self._api_key = api_key.strip()
        self._timeout_s = float(timeout_s)
        self._user_agent = user_agent

    def is_configured(self) -> bool:
        """True iff a service URL is set AND httpx can be bound.

        PURE LOCAL CHECK — no network, never raises. ``httpx`` is checked with
        ``find_spec`` rather than imported, so this stays free.
        """
        if not self._service_url:
            return False
        from importlib.util import find_spec

        try:
            return find_spec("httpx") is not None
        except (ImportError, ValueError):  # pragma: no cover - malformed install
            return False

    def sample(self, points: Sequence[LonLat]) -> list[ElevationSample]:
        """Sample elevation for each point, in batches.

        Args:
            points: Positions to sample, EPSG:4326.

        Returns:
            One sample per input point, in input order. Points the service declines to
            answer get ``ElevationSample(None, None, None)`` rather than being dropped.

        Raises:
            ProviderNotConfiguredError: If no service URL is set or httpx is absent.
            ProviderRateLimitError: On HTTP 429, carrying ``retry_after``.
            ProviderTransportError: On any other transport or protocol failure.
        """
        if not points:
            return []
        if not self._service_url:
            raise ProviderNotConfiguredError(
                "LE_COPERNICUS_DEM_URL is not set", provider=self.name
            )

        # ★ httpx bound at CALL time (§11.3): importing gis.elevation must succeed with
        #   httpx absent, or the whole registry dies at collection.
        try:
            import httpx
        except ImportError as exc:
            raise ProviderNotConfiguredError(
                "the copernicus_dem provider requires httpx", provider=self.name
            ) from exc

        results: list[ElevationSample] = []
        headers = {"User-Agent": self._user_agent}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            with httpx.Client(timeout=self._timeout_s, headers=headers) as client:
                for start in range(0, len(points), _BATCH_SIZE):
                    batch = points[start : start + _BATCH_SIZE]
                    results.extend(self._sample_batch(client, batch))
        except httpx.HTTPError as exc:
            raise ProviderTransportError(
                f"copernicus DEM request failed: {exc}", provider=self.name
            ) from exc
        return results

    def _sample_batch(self, client: Any, batch: Sequence[LonLat]) -> list[ElevationSample]:
        """Request one batch and map the response back onto the input order."""
        import httpx

        payload = {"locations": [{"longitude": p.lon, "latitude": p.lat} for p in batch]}
        response = client.post(self._service_url, json=payload)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                "copernicus DEM rate limit",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        try:
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderTransportError(
                f"copernicus DEM returned an unusable response: {exc}", provider=self.name
            ) from exc

        entries = body.get("results") or body.get("locations") or []
        out: list[ElevationSample] = []
        for i in range(len(batch)):
            value = None
            if i < len(entries) and isinstance(entries[i], dict):
                raw = entries[i].get("elevation")
                if raw is not None:
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        value = None
            if value is None:
                # ★ The service had no answer here. Say so; do not interpolate a neighbour.
                out.append(ElevationSample(None, None, None))
            else:
                out.append(
                    ElevationSample(
                        elevation_m=value,
                        source="copernicus_dem",
                        vertical_ce90_m=_COPERNICUS_VERTICAL_CE90_M,
                    )
                )
        if len(entries) != len(batch):
            _log.warning(
                "copernicus DEM returned %d results for %d points; the shortfall is "
                "reported as unavailable rather than misaligned",
                len(entries),
                len(batch),
            )
        return out
