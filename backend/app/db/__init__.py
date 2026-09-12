"""``app.db`` — sessions and ALL SQL (CONTRACT.md §10.2).

``session.py`` and ``types.py`` are IU-15; ``repositories/`` is IU-18. **Every
``select()`` in the system lives under ``repositories/``** — a ``select()`` in a
router is a defect (L6).

Deliberately re-exports nothing, so that this package's ``__init__`` never becomes a
reason for ``app.db.repositories`` and ``app.db.session`` to import each other.
"""

from __future__ import annotations
