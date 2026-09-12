"""``app.tasks`` — the Celery worker layer (CONTRACT.md §2.4, IU-20).

This package is the *composition root of the worker*: it is where a broker-crossable
:class:`~app.core.queue.JobSpec` becomes running work. Everything a service enqueues
through the :class:`~app.core.queue.JobQueue` Protocol lands in exactly one task here.

★ **Scope (SCOPE.md).** The automatic matching engine is DEFERRED, so three tasks are
typed-and-registered stubs that raise :class:`ai_engine.errors.NotImplementedDeferred`
rather than fabricate a result: :func:`~app.tasks.matching.match_image_task`,
:func:`~app.tasks.segmentation.segment_image_task` and
:func:`~app.tasks.segmentation.suggest_landmarks_task`. The tasks that are REAL in this
build are ingest (thumbnails/overviews/EXIF/georeferencing), export rendering, the batch
fan-out/aggregate skeleton and the maintenance beat.

This module imports nothing at import time on purpose: importing ``celery_app`` here would
build the Celery app (and read ``Settings``) the instant *any* submodule is imported,
including from the API process that only needs :class:`~app.tasks.queue.CeleryJobQueue`.
The app is built lazily by :func:`app.tasks.celery_app.get_celery_app`.
"""

from __future__ import annotations

__all__: list[str] = []
