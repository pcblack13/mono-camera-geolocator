"""Exception hierarchy for the ``gis`` package (CONTRACT.md §4.17).

Every error raised across a ``gis`` public boundary is one of these. Providers wrap
their transport libraries' exceptions so that callers never learn our stack.

``TileNotAvailableError`` vs ``ProviderTransportError`` is the distinction that matters
operationally: a 404 over open ocean is a *permanent* answer worth caching as a
negative; a 503 is transient and must be retried with backoff.
"""

from __future__ import annotations

__all__ = [
    "AreaTooLargeError",
    "CrsBackendUnavailable",
    "CrsError",
    "ExportError",
    "GisError",
    "ImportParseError",
    "NonMetricCrsError",
    "OutOfCoverage",
    "OutsideUtmError",
    "ProviderDisabledError",
    "ProviderError",
    "ProviderNotConfiguredError",
    "ProviderRateLimitError",
    "ProviderTransportError",
    "RasterBackendUnavailable",
    "SearchHintRequired",
    "TileNotAvailableError",
    "TileOutOfRangeError",
    "UnknownProviderError",
]


class GisError(Exception):
    """Base class for every error this package raises."""


class ProviderError(GisError):
    """Base class for imagery/elevation provider failures.

    Attributes:
        provider: Registry name of the provider that failed. ``""`` when unknown.
        retryable: Whether a caller may sensibly retry the same call.
    """

    retryable: bool = False

    def __init__(self, message: str = "", *, provider: str = "") -> None:
        super().__init__(message)
        self.provider: str = provider

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = super().__str__()
        if self.provider:
            return f"[{self.provider}] {base}" if base else f"[{self.provider}]"
        return base


class UnknownProviderError(ProviderError):
    """A provider name that is not registered. A typo'd config — fail loud."""


class ProviderNotConfiguredError(ProviderError):
    """The provider exists but has no key/path/credential to work with."""


class ProviderDisabledError(ProviderError):
    """The provider is registered and configured but not in the operator allow-list."""


class TileOutOfRangeError(ProviderError):
    """z outside [min_zoom, max_zoom], or x/y outside ``2**z``. A caller bug — NEVER retry."""


class TileNotAvailableError(ProviderError):
    """The provider legitimately has no imagery here (ocean, gap, cloud).

    A permanent answer: cache the NEGATIVE rather than re-asking.
    """


class AreaTooLargeError(ProviderError):
    """The requested area exceeds the tile/pixel budget guard."""


class RasterBackendUnavailable(ProviderError):
    """Neither ``rasterio`` nor ``osgeo.gdal`` could be bound at call time."""


class ProviderRateLimitError(ProviderError):
    """The provider is throttling us. Retryable after ``retry_after`` seconds."""

    retryable = True

    def __init__(
        self,
        message: str = "",
        *,
        provider: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after: float | None = retry_after


class ProviderTransportError(ProviderError):
    """A transient network/transport failure. Retry with jittered backoff."""

    retryable = True


class OutOfCoverage(GisError):
    """The provider has no imagery for the requested AOI at all."""


class SearchHintRequired(GisError):
    """No area of interest could be resolved. A hint is a hard input requirement."""


class ExportError(GisError):
    """An export writer failed to produce its bundle."""


class ImportParseError(GisError):
    """An uploaded exchange file could not be parsed into records.

    ★ Raised for a file that is malformed *as a file* — unreadable XML, an archive with
    no document inside, a document that is not the format it claims. A file that parses
    but yields nothing useful is NOT an error: it returns zero records plus the reasons,
    because "your file is fine and matched nothing" and "your file is broken" are
    different answers and the operator needs to be told which one they have.
    """


class CrsError(GisError):
    """A coordinate reference system could not be resolved, parsed, or used."""


class CrsBackendUnavailable(CrsError):
    """No CRS backend can serve the requested transform.

    Raised at CALL time (never at import), naming the dependency that would fix it.
    The closed-form NumPy fallback covers EPSG:4326 <-> EPSG:3857 only; anything else
    needs ``pyproj`` or ``osgeo.osr``.
    """


class NonMetricCrsError(CrsError):
    """A ``*_m`` function was handed a CRS whose linear unit is not the metre.

    Degrees are not a length unit and Web Mercator metres are not ground metres.
    Every function that returns a distance, area or RMSE gates on this.
    """


class OutsideUtmError(CrsError):
    """``|lat| > 84``: outside the UTM domain (use UPS)."""
