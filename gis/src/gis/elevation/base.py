"""The elevation provider interface — the FOURTH provider interface (§4.27).

The client brief mandates **lat / lon / elevation / confidence**. Elevation is plumbed end
to end as data — ``gcps.elevation_m``, the ``elevation_source`` enum, CSV column 6 — and
this is the layer that actually produces it.

The honesty rules, normative
----------------------------
* When the resolved provider yields None, ``gcps.elevation_m IS NULL`` **and
  ``elevation_source IS NULL``**. The pair is bound by a DB check constraint, and the job
  appends ``WarningItem{code: "ELEVATION_UNAVAILABLE"}``.
* Every export writer emits an explicit empty cell rather than a silent blank.
* **``elevation_source`` may never name a source that did not run.** A populated source
  beside a NULL elevation implies a measurement that never happened — a survey deliverable
  silently missing its third coordinate while claiming to have it.
* ``vertical_ce90_m`` is honest or it is None. **Never a fabricated 0.**
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from gis.types import LonLat

__all__ = ["ElevationProvider", "ElevationSample"]


@dataclass(frozen=True, slots=True)
class ElevationSample:
    """One point's elevation, or an honest admission that we do not have one.

    Attributes:
        elevation_m: Metres above the vertical datum, or None when unavailable.
        source: ``'local_dem' | 'copernicus_dem' | 'srtm' | 'exif' | 'manual'``, or None.
            ★ MUST be None whenever ``elevation_m`` is None. Naming a source that did not
            run is the failure this type exists to prevent.
        vertical_ce90_m: Vertical error at CE90, metres — honest, or None. ★ Never a
            fabricated 0. A DEM interpolated at 30 m posting has real vertical error and
            reporting 0 would launder an estimate into a measurement.
    """

    elevation_m: float | None
    source: str | None
    vertical_ce90_m: float | None

    def __post_init__(self) -> None:
        if self.elevation_m is None and self.source is not None:
            raise ValueError(
                f"source={self.source!r} names a source that produced no elevation; "
                "elevation_m is None so source MUST be None (see gis.elevation.base)"
            )


class ElevationProvider(abc.ABC):
    """One elevation source, normalised to metres plus an honest error bar.

    Same contract as ``ImageryProvider``:

    * ``__init__`` MUST NOT perform network I/O and MUST NOT raise on a missing
      credential or a missing directory. Construction ALWAYS succeeds; ``is_configured()``
      reports readiness. A provider that throws in its constructor takes down the
      registry, the capabilities endpoint, and the UI that would have told you the key
      was missing.
    * ``sample()`` raises no bare library exceptions — only ``gis.errors`` types.
    * Thread-safe: Celery calls these from a worker pool.
    """

    name: ClassVar[str]
    """Stable registry key, matching a member of ``ELEVATION_PROVIDERS``."""

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True iff this provider can serve RIGHT NOW.

        PURE LOCAL CHECK — no network, and it NEVER raises.
        """

    @abc.abstractmethod
    def sample(self, points: Sequence[LonLat]) -> list[ElevationSample]:
        """Sample elevation at each point.

        ★ Batch by design. A GCP set is sampled at once; a per-point HTTP call to a DEM
        service for 40 GCPs is 40 round trips.

        Args:
            points: Positions to sample, EPSG:4326.

        Returns:
            One ``ElevationSample`` per input point, in the SAME ORDER. Points the
            provider cannot serve get ``ElevationSample(None, None, None)`` rather than
            being dropped — the caller zips this against its GCPs and a short list would
            silently misalign every coordinate after the gap.

        Raises:
            ProviderNotConfiguredError: If called while ``is_configured()`` is False.
            ProviderError: On a transport or backend failure.
        """
