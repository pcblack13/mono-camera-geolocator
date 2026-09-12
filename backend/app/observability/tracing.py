"""Optional OpenTelemetry tracing — a no-op when unset (CONTRACT.md §9.10).

``LE_OTEL_EXPORTER_OTLP_ENDPOINT`` empty ⇒ no-op tracer. That is the default and the
overwhelmingly common case, so the no-op path must cost nothing and must not require
opentelemetry to be installed at all.

★ **opentelemetry is bound at call time** (§11.3). It is not in ``requirements.txt``
— it lives in the ``[tracing]`` extra — so a module-scope import would make
``app.observability`` unimportable on every default deployment. Its absence is a
textbook L11 degradation: a WARNING and a no-op tracer, never a traceback, and never
silent.
"""

from __future__ import annotations

from contextlib import contextmanager
from importlib.util import find_spec
from typing import Any, Iterator

from app.core.config import Settings
from app.core.logging import get_logger

__all__ = ["configure_tracing", "get_tracer", "span", "tracing_available"]

log = get_logger(__name__)

_tracer: Any | None = None
_configured = False


def tracing_available() -> bool:
    """Whether the OTEL SDK can be imported, without importing it."""
    return find_spec("opentelemetry.sdk") is not None


def configure_tracing(settings: Settings) -> bool:
    """Set up OTLP tracing if configured and installed. Idempotent.

    Called from ``main.py``'s lifespan. Returns whether tracing is actually active,
    which ``/health/ready`` and ``GET /capabilities`` report — an operator who set the
    endpoint and got no traces deserves to be told which of the two things went wrong,
    rather than staring at an empty Jaeger.

    Never raises. A misconfigured exporter must not stop the API from serving
    coordinates (L11).
    """
    global _tracer, _configured

    if _configured:
        return _tracer is not None

    _configured = True

    if not settings.otel_exporter_otlp_endpoint:
        # The default and the common case. Not a warning: nothing is wrong.
        log.debug("tracing.disabled", reason="LE_OTEL_EXPORTER_OTLP_ENDPOINT is empty")
        return False

    if not tracing_available():
        log.warning(
            "tracing.unavailable",
            reason="opentelemetry is not installed",
            endpoint=settings.otel_exporter_otlp_endpoint,
            remedy="pip install landexplorer-backend[tracing]",
            effect="spans are dropped; the API is unaffected",
        )
        return False

    try:
        # ★ Call-time binding (§11.3).
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": settings.otel_service_name,
                    "deployment.environment": settings.env,
                    "service.version": "1.0.0",
                }
            )
        )
        # Batch, not simple: a SimpleSpanProcessor exports synchronously on span end,
        # putting an HTTP round trip to the collector on the request's critical path.
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(settings.otel_service_name)

        log.info("tracing.enabled", endpoint=settings.otel_exporter_otlp_endpoint)
        return True
    except Exception as exc:  # noqa: BLE001
        # Broad on purpose: OTEL's exporters raise a wide and version-dependent set,
        # and no configuration mistake in an optional telemetry pipeline is worth a
        # failed boot.
        log.warning("tracing.setup_failed", error=str(exc), effect="tracing disabled")
        _tracer = None
        return False


def get_tracer() -> Any | None:
    """The configured tracer, or None. Callers should prefer ``span``."""
    return _tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Trace a block of work. A no-op when tracing is off.

    ::

        with span("gcp.recompute", image_id=str(image_id)):
            ...

    Yields None when disabled, so a caller that wants to set attributes on the span
    must check — but a caller that just wants the timing writes no branch at all,
    which is the common case and the one worth optimising for readability.
    """
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield current
