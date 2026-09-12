"""``app.core`` — settings, logging, errors, constants.

The bottom of the backend's layer stack (§10.2). It imports ``pydantic-settings``,
``structlog`` and the standard library, and **nothing** from ``app.models``,
``app.schemas``, ``app.db``, ``app.services``, ``app.tasks``, ``app.api``,
``ai_engine`` or ``gis``. Everything else may import it; it may import nothing back.

Deliberately re-exports nothing. ``core.config`` is the only module in the backend
permitted to read the environment, ``core.constants`` is the sole home of the
job-stage vocabulary, and ``core.queue`` is a Protocol whose implementation lives in
another unit — flattening those into a package namespace would make each of them look
like an interchangeable part of one module. Import the module you mean.
"""

from __future__ import annotations
