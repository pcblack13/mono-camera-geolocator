"""★ THE CORRESPONDENCE SEAM — the interface the pipeline actually depends on.

Neither `Matcher` nor `DetectorFreeMatcher` appears in a single pipeline signature. The
pipeline asks a `CorrespondenceSource` for `Correspondences` and does not care whether a
detector ran, whether two models were ensembled, or which of them found what. That is what
lets §4.14.2's source-selection table exist at all::

    cfg.detector_free   cfg.matcher   -> MatchContext.source
    ---------------------------------------------------------------------
    None                set           -> DetectBasedSource(extractor, matcher)
    set                 set           -> EnsembleSource([DetectBased, DetectorFree])
    set                 None          -> DetectorFreeSource(detector_free)
    None                None          -> ConfigurationError

★ THE PROTOCOL IS REAL AND COMPLETE. The three concrete sources are DEFERRED
(``docs/architecture/SCOPE.md``) — with one deliberate exception: **their constructors are
real**, because a constructor assertion is not an algorithm, and the one on
`DetectBasedSource` is load-bearing (see below).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ai_engine.errors import NotImplementedDeferred
from ai_engine.extractors.base import FeatureExtractor
from ai_engine.matchers.base import DetectorFreeMatcher, Matcher
from ai_engine.models import params_hash as _params_hash
from ai_engine.types import Correspondences, CorrespondenceRequest

__all__ = [
    "CorrespondenceSource",
    "DetectBasedSource",
    "DetectorFreeSource",
    "EnsembleSource",
]


@runtime_checkable
class CorrespondenceSource(Protocol):
    """★ THE seam the pipeline depends on. Anything that can produce `Correspondences`.

    Structural, not nominal: an implementation satisfies this by having the members, not
    by inheriting. `runtime_checkable` lets a test assert conformance with `isinstance` —
    with the usual caveat that it checks member *presence*, not signatures, so static
    checking remains the real proof.
    """

    name: str

    def correspond(self, req: CorrespondenceRequest) -> Correspondences:
        """Produce correspondences for the pair described by `req`."""
        ...

    def params_hash(self) -> str:
        """A stable digest of this source's parameters — a cache-key input."""
        ...


class DetectBasedSource:
    """extractor + matcher → `Correspondences`. The classical path's source.

    ★ ITS CONSTRUCTOR IS REAL, AND ITS ASSERTION IS THE POINT OF THE CLASS. `LoFTRAsMatcher`
    is a `Matcher` by type and a lie by construction — it synthesises feature indices for a
    model that has none. Wiring it in here would not raise, would not log, and would not
    fail a type check; it would just quietly degrade every match the pipeline made. The
    `requires_images` flag exists so that this constructor can reject it, and this
    constructor exists so that the flag is checked exactly once, at composition time,
    rather than never.
    """

    def __init__(self, extractor: FeatureExtractor, matcher: Matcher) -> None:
        """Bind an extractor to a matcher.

        Args:
            extractor: Produces `FeatureSet`s from images.
            matcher: Matches those `FeatureSet`s.

        Raises:
            TypeError: `matcher.requires_images` is True — i.e. it is a detector-free shim
                masquerading as a `Matcher`. See the class docstring.
        """
        if matcher.requires_images:
            raise TypeError(
                f"{type(matcher).__name__} sets requires_images=True: it is a lossy "
                f"detector-free shim and MUST NOT be used as a detector-based matcher. "
                f"It invents feature indices for a model that has none, which degrades "
                f"every match silently. Use DetectorFreeSource with the underlying "
                f"DetectorFreeMatcher instead."
            )
        self.extractor = extractor
        self.matcher = matcher
        self.name = f"detect:{extractor.name}+{matcher.name}"

    def correspond(self, req: CorrespondenceRequest) -> Correspondences:
        """Extract both sides (or reuse `req.features_*`), match, and materialise points.

        Raises:
            NotImplementedDeferred: Always, in this build. Every step it would perform —
                `extractor.extract`, `matcher.match`, `MatchSet.to_correspondences` — is
                itself deferred, so a body here would be unreachable code that could never
                be exercised or tested. See ``docs/architecture/SCOPE.md``.
        """
        raise NotImplementedDeferred(
            __name__, feature="detector-based correspondence generation"
        )

    def params_hash(self) -> str:
        """The digest of both halves — either one changing must invalidate the cache."""
        return _params_hash(
            {
                "source": "detect_based",
                "extractor": self.extractor.name,
                "extractor_version": self.extractor.version,
                "extractor_params": self.extractor.params_hash(),
                "matcher": self.matcher.name,
                "matcher_version": self.matcher.version,
                "matcher_params": self.matcher.params_hash(),
            }
        )


class DetectorFreeSource:
    """A `DetectorFreeMatcher` → `Correspondences`. A natural fit; no adaptation, no loss.

    Contrast `LoFTRAsMatcher`, which forces the same model through the detector-based
    interface and loses information doing it. This is why two ABCs are better than one.
    """

    def __init__(self, matcher: DetectorFreeMatcher) -> None:
        """Bind a detector-free matcher.

        Args:
            matcher: The detector-free model.
        """
        self.matcher = matcher
        self.name = f"detector_free:{matcher.name}"

    def correspond(self, req: CorrespondenceRequest) -> Correspondences:
        """Match `req.image_a` against `req.image_b` directly.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(
            __name__, feature="detector-free correspondence generation"
        )

    def params_hash(self) -> str:
        """The digest of the underlying model's identity and parameters."""
        return _params_hash(
            {
                "source": "detector_free",
                "matcher": self.matcher.name,
                "matcher_version": self.matcher.version,
            }
        )


class EnsembleSource:
    """The union of several sources, deduplicated by `Correspondences.merge()`.

    ★ THE RECOMMENDED DEEP CONFIGURATION, and the reasoning is worth keeping: LoFTR finds
    correspondence in the low-texture field interior where SIFT finds nothing, and SIFT
    nails the high-frequency corners LoFTR's 1/8-resolution coarse stage misses. **They
    fail in complementary places** — which is the only good reason to ensemble anything.
    Two matchers that fail on the same images just cost twice as much.
    """

    def __init__(
        self,
        sources: Sequence[CorrespondenceSource],
        *,
        dedupe_px: float = 2.0,
    ) -> None:
        """Bind several sources.

        Args:
            sources: The sources to union. Must be non-empty.
            dedupe_px: Two correspondences are duplicates iff BOTH endpoints fall within
                this distance; the higher-weight one survives.

        Raises:
            ValueError: `sources` is empty — an ensemble of nothing produces nothing, and
                would report it as "no matches found" rather than as a configuration bug.
        """
        if not sources:
            raise ValueError(
                "EnsembleSource needs at least one source. An empty ensemble returns no "
                "correspondences, which is indistinguishable from a genuine no-match."
            )
        self.sources = tuple(sources)
        self.dedupe_px = dedupe_px
        self.name = "ensemble:" + "+".join(s.name for s in self.sources)

    def correspond(self, req: CorrespondenceRequest) -> Correspondences:
        """Run every source and merge the results.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(
            __name__, feature="ensemble correspondence generation"
        )

    def params_hash(self) -> str:
        """The digest of every member's digest, plus the dedupe radius."""
        return _params_hash(
            {
                "source": "ensemble",
                "dedupe_px": self.dedupe_px,
                "members": [s.params_hash() for s in self.sources],
            }
        )
