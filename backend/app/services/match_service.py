"""``match_service`` — fronts the DEFERRED automatic matching engine.

★★ **SCOPE.md §1: the automatic matching engine is DEFERRED in this build.** Feature
extraction, matching, RANSAC, pose, semantics, scoring and heatmaps are ABCs and stubs.
So the *run* path here does exactly one thing: it raises
:class:`~app.core.exceptions.FeatureDeferredError`, which the API layer renders as
``501 Not Implemented`` with ``feature: "deferred"``.

★ It does **not** enqueue a job. §2.4 v1.0 had this service build a ``MatchJobSpec`` and
``JobQueue.submit()`` it — but a deferred worker task will never complete, so submitting
one produces a row stuck at ``pending`` and a surveyor watching a spinner that never
resolves, which is precisely what SCOPE.md §4 rule 4 forbids. **The pre-flight ladder and
the ``JobSpec`` construction are kept only where the work is real (ingest / export).** When
the engine is re-enabled, this method builds the spec and submits it, and *nothing else in
the stack changes* (SCOPE.md §7) — which is why the ``JobQueue`` is already injected.

The **reads** are real: ``match_results`` holds no rows in this build, but the table, the
repository and the seam are exact (``result_service`` owns selection). A surveyor placing
manual GCPs never touches this service.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import FeatureDeferredError
from app.core.queue import JobQueue, NullJobQueue

__all__ = ["MatchService"]

#: The deferred component this service fronts, named in the 501 body and the logs.
_COMPONENT = "ai_engine.pipeline.orchestrator"

_DEFERRED_MESSAGE = (
    "Automatic matching is not enabled in this build — place GCPs manually. The surveyor "
    "marks a landmark in the photograph and clicks the same point on the satellite map, "
    "and the coordinate is recorded as a direct observation."
)


class MatchService:
    """The automatic-matching entry point. Its run path is deferred (501).

    Args:
        session: The request's session — held for the real reads and for the day the run
            path is re-enabled.
        settings: The backend settings.
        queue: The injected job queue. Present so re-enabling the engine (SCOPE.md §7)
            requires no signature change; unused while matching is deferred, because a
            deferred job would never complete.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        queue: JobQueue | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._queue = queue if queue is not None else NullJobQueue()

    def start_match(self, image_id: uuid.UUID, *args: object, **kwargs: object) -> None:
        """``POST /images/{id}/match`` (30) — **DEFERRED**.

        Raises:
            FeatureDeferredError: always, in this build (501, ``feature: "deferred"``).
                No job is enqueued and no result is fabricated.
        """
        raise FeatureDeferredError(_DEFERRED_MESSAGE, component=_COMPONENT)
