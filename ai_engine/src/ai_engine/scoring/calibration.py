"""Score calibration — Platt and isotonic. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ THE SHIPPED CALIBRATION IS THE IDENTITY, AND IT SAYS SO. `default-v1.json` declares
``"calibrated": false``, `LE_AI_CALIBRATION_ID` defaults to ``"identity"``, and
`ScoreResult.calibrated` rides on the wire so the UI can refuse to print a percentage. This
is the whole posture of the product in one default: a calibration curve fitted to no data
is a lie with a probability attached, and the surveyor cannot tell it from a real one.
Calibration is earned from the ground-truth dataset that manual GCP surveying produces —
which is, per SCOPE §2, one of the reasons manual mode is the *correct* thing to build
first: it generates exactly the labelled correspondences an automatic engine would have to
be measured against.

★ `calibrate(0.0)` MUST RETURN `0.0` FOR EVERY CALIBRATOR. The gate is multiplicative and
zero means "the degeneracy validator rejected this fit". A curve that maps 0 to anything
else resurrects a rejected fit, and `logit(0)` is `NaN`, not 0 — so the naive Platt
implementation does exactly that, and an identity-only test never notices.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = [
    "Calibrator",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "load_calibration",
]


@runtime_checkable
class Calibrator(Protocol):
    """Maps a raw `[0,1]` score onto a calibrated `[0,1]` one.

    Structural, so the identity calibrator can be a plain object rather than a subclass.
    """

    calibration_id: str
    calibrated: bool

    def __call__(self, raw: float) -> float:
        """Calibrate one score. MUST map 0.0 to 0.0 — see the module docstring."""
        ...


class PlattCalibrator:
    """Sigmoid calibration: ``1 / (1 + exp(A·raw + B))``. **DEFERRED.**"""

    def __init__(self, a: float, b: float, *, calibration_id: str = "platt") -> None:
        """Bind the fitted parameters.

        Args:
            a: The slope.
            b: The intercept.
            calibration_id: The identifier recorded on every `ScoreResult`.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="Platt score calibration")

    def __call__(self, raw: float) -> float:
        """Calibrate one raw score.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="Platt score calibration")


class IsotonicCalibrator:
    """Monotone piecewise-constant calibration from a fitted step function. **DEFERRED.**"""

    def __init__(
        self,
        thresholds: np.ndarray,
        values: np.ndarray,
        *,
        calibration_id: str = "isotonic",
    ) -> None:
        """Bind the fitted step function.

        Args:
            thresholds: `(S,)` ascending raw-score breakpoints.
            values: `(S,)` the calibrated value on each step. Must be non-decreasing —
                a non-monotone "calibration" reorders candidates, which is not calibration.
            calibration_id: The identifier recorded on every `ScoreResult`.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="isotonic score calibration")

    def __call__(self, raw: float) -> float:
        """Calibrate one raw score.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="isotonic score calibration")


def load_calibration(calibration_id: str, *, search_dir: Path | None = None) -> Calibrator:
    """Load a calibrator by id.

    Args:
        calibration_id: ``"identity"`` (the default and the shipped state),
            ``"default-v1"``, or a custom id resolvable under `search_dir`.
        search_dir: Where to look. Defaults to `scoring/calibration/`.

    Returns:
        A `Calibrator`. ★ An unknown id must resolve to the IDENTITY with a WARNING rather
        than raise (L11): a missing calibration file is a degradation in the number's
        precision, not a reason to refuse a surveyor their coordinate. What it must never
        do is silently substitute a *different* curve.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(__name__, feature="score calibration loading")
