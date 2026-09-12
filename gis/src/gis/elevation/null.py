"""The keyless, offline, terminal default elevation provider (§4.27).

★★ THIS IS THE DEFAULT. ``LE_ELEVATION_PROVIDER=none``.

It returns ``ElevationSample(None, None, None)`` for every point, and that is the whole
point of it. **Honest beats absent.** The alternative — plumbing an ``elevation_source``
enum end to end with no module behind it — ships a survey deliverable that claims a third
coordinate it does not have.

Because this provider is TERMINAL it has no fallback, requires no key, needs no network
and cannot fail. It is what makes ``docker compose up`` with an empty ``.env`` produce a
working, honest system.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from gis.elevation.base import ElevationProvider, ElevationSample
from gis.types import LonLat

__all__ = ["NullElevationProvider"]


class NullElevationProvider(ElevationProvider):
    """Reports, truthfully, that we have no elevation data.

    ★ TERMINAL · KEYLESS · OFFLINE · THE DEFAULT.
    """

    name: ClassVar[str] = "none"

    def is_configured(self) -> bool:
        """Always True.

        Being unable to produce an elevation is this provider's *function*, not its
        failure — so it is always ready to do it. Returning False here would make the
        registry look for a fallback that does not exist and cannot exist.
        """
        return True

    def sample(self, points: Sequence[LonLat]) -> list[ElevationSample]:
        """Return an empty sample per point — never a guess, never a zero.

        Args:
            points: Positions to sample. Used only for its length.

        Returns:
            ``[ElevationSample(None, None, None)] * len(points)``. Note ``source`` is
            None, not ``"none"``: no source ran, so naming one would be a lie the DB's
            ``ck_gcps_elevation_source_consistent`` constraint exists to catch.
        """
        return [ElevationSample(None, None, None) for _ in points]
