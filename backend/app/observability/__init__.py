"""``app.observability`` — metrics and tracing.

Imports ``prometheus-client`` and ``structlog`` and **no domain module** (§10.2).
That direction is the point: telemetry observes the domain, so anything here that
imported a service would put a metric in the position of being able to break a
survey.
"""

from __future__ import annotations

from app.observability.metrics import REGISTRY, render_metrics
from app.observability.tracing import configure_tracing, span, tracing_available

__all__ = [
    "REGISTRY",
    "configure_tracing",
    "render_metrics",
    "span",
    "tracing_available",
]
