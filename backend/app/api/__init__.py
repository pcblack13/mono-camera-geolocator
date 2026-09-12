"""``app.api`` — the HTTP layer (IU-21).

★ **The import law this package lives under** (§6.4, §10.4). The import-linter
contract ``api-not-db`` sets ``source_modules = app.api.v1`` — the *routers* — and forbids
them ``app.db``, ``app.models``, ``ai_engine``, ``gis`` and ``cv2``. Routers validate,
delegate to ``app.services`` and serialise; they never touch the database and never do CV
(L5, L6).

Two modules in this package sit *outside* ``app.api.v1`` and are therefore **not** bound by
that contract, exactly as §6.4 carves out ``app.api.deps``:

* :mod:`app.api.deps` — the composition root of the HTTP layer. ``Depends(get_db)`` is how a
  session enters a request at all, so it must reach ``app.db``/``app.models``/``gis``.
* :mod:`app.api.presenters` — the one place an ORM entity becomes a wire schema. Decoding a
  ``geography`` column to ``lat``/``lon`` needs ``app.db.types`` (a dependency-free EWKB
  reader), and a router may not import it. The same mechanical carve-out as ``deps`` applies:
  ``presenters`` is ``app.api`` but not ``app.api.v1``, so the router contract does not bite
  it. This module is an addition to §2.4's tree, flagged in IU-21's report.
"""

from __future__ import annotations

__all__: list[str] = []
