"""``ProgressReporter`` — the throttled progress writer and the cancel poll (§5.5, §5.9).

★ **``STAGE_WEIGHTS`` is imported from ``core.constants``, never redefined here.** v1.0
put it in both files; two units, one symbol, guaranteed to drift. ``percent`` is a
*weighted blend* of stages — not ``stage_index / n_stages`` — so the bar tracks wall clock
(tile fetch dominates a match; decoding dominates an ingest), and the weights that encode
that live in exactly one place.

Two invariants the UI depends on and this class enforces:

* **Monotonic within an attempt.** ``percent`` never goes backwards; a bar that rewinds is
  read as a bug. It resets only when the job is re-run (a new attempt starts at the
  ``pending`` weight, i.e. 0).
* **Throttled and out-of-band.** Writes are ≥ 250 ms apart and each is a plain ``UPDATE``
  on its **own** session/transaction — progress is telemetry and must never hold a lock a
  matcher needs, nor ride inside a long domain transaction (§5.9). A stage change or a
  terminal 100% always writes, throttle notwithstanding, because those are the ticks a
  human is actually waiting to see.

The cancel poll reads ``cancel_requested`` and raises :class:`~app.tasks.base.JobCancelled`;
callers invoke it at every stage boundary and inside the tile-fetch loop. There is no hard
kill (``revoke(terminate=True)`` is never used), so cooperative polling is the only
cancellation path.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Final

from celery import Task

from app.core.constants import stage_weights_for, stages_for
from app.core.logging import get_logger
from app.db.repositories.jobs import SyncJobRepository
from app.db.session import sync_session
from app.models.base import Base
from app.tasks.base import JobCancelled

__all__ = ["ProgressReporter"]

log = get_logger(__name__)

#: Minimum spacing between throttled progress writes (§5.9).
_THROTTLE_S: Final = 0.25


class ProgressReporter:
    """Computes weighted percent and writes it, subject to the throttle and monotonicity.

    Args:
        task: The bound task (for logging context only).
        model: The concrete job table.
        job_id: The job row.
        job_type: A ``JobType`` member or its wire value — selects the stage list and
            weight map.
    """

    __slots__ = (
        "_task",
        "_model",
        "_job_id",
        "_weights",
        "_cum_before",
        "_stage",
        "_percent",
        "_last_write_at",
    )

    def __init__(self, task: Task, model: type[Base], job_id: uuid.UUID, job_type: Any) -> None:
        self._task = task
        self._model = model
        self._job_id = job_id
        self._weights = stage_weights_for(job_type)

        # Cumulative weight of every stage strictly *before* each stage, in order. The
        # percent at ``fraction`` through ``stage`` is ``cum_before[stage] +
        # weight[stage] * fraction`` — a blend, so ``done`` lands on exactly 1.0.
        cum = 0.0
        cum_before: dict[str, float] = {}
        for stage in stages_for(job_type):
            key = str(stage)
            cum_before[key] = cum
            cum += float(self._weights[stage])
        self._cum_before = cum_before

        self._stage: str | None = None
        self._percent = 0.0
        self._last_write_at = 0.0

    # ── stage / fraction API ──────────────────────────────────────────────────

    def set_stage(
        self,
        stage: Any,
        *,
        message: str | None = None,
        fraction: float = 0.0,
        **counters: Any,
    ) -> None:
        """Enter ``stage`` (optionally already ``fraction`` into it) and force a write.

        A stage change is always worth showing, so it bypasses the throttle. It also polls
        cancellation first, so a job cancelled mid-flight stops at the next boundary rather
        than starting the next stage.
        """
        self.check_cancelled()
        self._stage = str(stage)
        self._write(self._percent_for(self._stage, fraction), message, counters, force=True)

    def advance(
        self,
        fraction: float,
        *,
        message: str | None = None,
        **counters: Any,
    ) -> None:
        """Report ``fraction`` (0–1) of progress through the *current* stage.

        Subject to the throttle. Does nothing meaningful before a stage has been set.
        """
        if self._stage is None:
            return
        self._write(self._percent_for(self._stage, fraction), message, counters, force=False)

    # ── cancellation ──────────────────────────────────────────────────────────

    def check_cancelled(self) -> None:
        """Raise :class:`JobCancelled` if the row's ``cancel_requested`` is set.

        Its own short-lived session: the flag is set by the API on a different connection,
        and reading it must see that commit, not a snapshot from the worker's domain
        transaction.
        """
        with sync_session() as db:
            if SyncJobRepository(db).is_cancel_requested(self._model, self._job_id):
                raise JobCancelled(f"job {self._job_id} was cancelled")

    # ── internals ─────────────────────────────────────────────────────────────

    def _percent_for(self, stage: str, fraction: float) -> float:
        frac = 0.0 if fraction < 0.0 else 1.0 if fraction > 1.0 else fraction
        base = self._cum_before.get(stage, self._percent)
        weight = float(self._weights.get(stage, 0.0)) if hasattr(self._weights, "get") else 0.0
        return base + weight * frac

    def _write(
        self,
        percent: float,
        message: str | None,
        counters: dict[str, Any],
        *,
        force: bool,
    ) -> None:
        # Monotonic within the attempt — never rewind the bar.
        percent = max(self._percent, min(percent, 1.0))
        now = time.monotonic()
        if not force and percent < 1.0 and (now - self._last_write_at) < _THROTTLE_S:
            self._percent = percent
            return

        self._percent = percent
        self._last_write_at = now
        try:
            with sync_session() as db:
                SyncJobRepository(db).write_progress(
                    self._model,
                    self._job_id,
                    progress=percent,
                    stage=self._stage,
                    message=message,
                    **counters,
                )
        except Exception as exc:  # noqa: BLE001 — telemetry must never fail the job
            # A progress write that fails is a lost tick, not a lost job. Log and continue;
            # the next tick or the terminal transition will correct the displayed state.
            log.warning(
                "progress.write_failed",
                job_id=str(self._job_id),
                stage=self._stage,
                error=str(exc),
            )
