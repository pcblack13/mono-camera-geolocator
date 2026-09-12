"""LandExplorer backend — FastAPI + Celery.

The only home of fastapi / sqlalchemy / celery / pydantic (CONTRACT.md §2.4).

This module is deliberately empty of imports. ``app`` is the root package of six
layers with a strict, CI-enforced dependency order (§10.1)::

    app  ->  gis  ->  ai_engine

Importing anything here would give every layer a transitive dependency on
whatever it touched, and the layer stack is the only thing keeping twelve
parallel units compatible. It never inverts.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
