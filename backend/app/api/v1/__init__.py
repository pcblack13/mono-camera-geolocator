"""``app.api.v1`` — the routers. The ``/api/v1`` prefix is applied ONCE, in
:mod:`app.api.v1.router` (§7). These modules may import ``fastapi`` and
``app.{schemas,services,core}`` — and NOT ``app.db``, ``app.models``, ``app.tasks``,
``ai_engine``, ``gis`` or ``cv2`` (§10.4). They receive already-loaded entities from
``app.api.deps`` and build wire models through ``app.api.presenters``.
"""

__all__: list[str] = []
