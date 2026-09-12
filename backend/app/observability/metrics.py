"""Prometheus metrics — the §9.10 required set, and nothing invented beside it.

Every metric below is named in §9.10. They are declared once, at module scope,
because a Prometheus collector must be registered exactly once per process — a
metric constructed per request raises ``Duplicated timeseries`` on the second one.

★ **``model_fallbacks_total`` is deliberately a metric and not just a log line**
(§9.10). A fleet-wide spike in fallbacks means somebody's weight volume did not
mount — *that should page, not hide in INFO*. It is the metric that proves L1 is
working in production rather than merely being specified in a document.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "REGISTRY",
    "gcp_adjustments_total",
    "http_request_duration_seconds",
    "http_requests_total",
    "imagery_tile_requests_total",
    "imagery_upstream_errors_total",
    "job_duration_seconds",
    "job_queue_depth",
    "model_fallbacks_total",
    "ratelimit_failopen_total",
    "ratelimit_rejections_total",
    "render_metrics",
    "unhandled_exceptions_total",
]

#: A private registry rather than prometheus_client's global default.
#:
#: The default registry is process-global and implicitly shared with anything else
#: that imports prometheus_client — including libraries that register their own
#: collectors on import. Owning the registry means /metrics contains what §9.10 says
#: it contains, and a test can build a fresh one instead of fighting leftover state
#: from the previous test's counters.
REGISTRY: Final = CollectorRegistry()


# ── HTTP ──────────────────────────────────────────────────────────────────────
#
# ★ `route` is the route TEMPLATE ("/api/v1/images/{image_id}"), never the resolved
# path. A label whose value is a UUID has unbounded cardinality: one time series per
# image, forever, and an OOM in Prometheus rather than in us — which is worse,
# because it takes the monitoring down at the moment it is needed.

http_requests_total: Final = Counter(
    "http_requests_total",
    "HTTP requests by route template, method and status.",
    labelnames=("route", "method", "status"),
    registry=REGISTRY,
)

http_request_duration_seconds: Final = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency by route template.",
    labelnames=("route",),
    # Tuned for this API's shape rather than the library default. The interesting
    # range is 5 ms (a cached tile) to 2 s (a stitched static map); the default
    # buckets top out at 10 s and waste half their resolution above 1 s where nothing
    # of ours lives. The 30 s bucket exists for the long-poll on GET /jobs/{id}.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=REGISTRY,
)

unhandled_exceptions_total: Final = Counter(
    "unhandled_exceptions_total",
    "Exceptions that reached the 500 handler, by route template.",
    labelnames=("route",),
    registry=REGISTRY,
)


# ── Jobs ──────────────────────────────────────────────────────────────────────

job_duration_seconds: Final = Histogram(
    "job_duration_seconds",
    "Job wall-clock duration by type and terminal status.",
    labelnames=("type", "status"),
    # Jobs are minutes, not milliseconds: a match fetches hundreds of tiles and runs
    # SIFT on CPU. The top bucket sits above LE_CELERY_TASK_TIME_LIMIT (900 s) so a
    # job killed by the hard limit still lands somewhere finite.
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1800.0),
    registry=REGISTRY,
)

job_queue_depth: Final = Gauge(
    "job_queue_depth",
    "Tasks waiting in each Celery queue.",
    labelnames=("queue",),
    registry=REGISTRY,
)


# ── Imagery ───────────────────────────────────────────────────────────────────

imagery_tile_requests_total: Final = Counter(
    "imagery_tile_requests_total",
    "Tile requests by provider and cache outcome.",
    # `cache` is hit|miss|bypass. The hit ratio is the number that decides whether
    # LE_IMAGERY_TILE_CACHE_BACKEND=redis is earning its keep in prod, and it is the
    # first thing to look at when a provider starts rate-limiting us.
    labelnames=("provider", "cache"),
    registry=REGISTRY,
)

imagery_upstream_errors_total: Final = Counter(
    "imagery_upstream_errors_total",
    "Upstream imagery provider errors, by provider.",
    labelnames=("provider",),
    registry=REGISTRY,
)


# ── Models ────────────────────────────────────────────────────────────────────

model_fallbacks_total: Final = Counter(
    "model_fallbacks_total",
    "Component fallbacks: a requested backend was unavailable and another was used.",
    # requested="superglue", effective="flann", reason="weights_missing".
    # `reason` is a small closed set (weights_missing, weights_corrupt,
    # package_missing, device_unavailable, deferred) — not a free-form message, which
    # would be unbounded cardinality and unaggregatable.
    labelnames=("requested", "effective", "reason"),
    registry=REGISTRY,
)


# ── GCPs ──────────────────────────────────────────────────────────────────────

gcp_adjustments_total: Final = Counter(
    "gcp_adjustments_total",
    "Manual GCP adjustments committed by a surveyor.",
    registry=REGISTRY,
)


# ── Rate limiting ─────────────────────────────────────────────────────────────

ratelimit_rejections_total: Final = Counter(
    "ratelimit_rejections_total",
    "Requests rejected by the rate limiter, by scope.",
    labelnames=("scope",),
    registry=REGISTRY,
)

ratelimit_failopen_total: Final = Counter(
    "ratelimit_failopen_total",
    "Requests allowed because the rate limiter's backend was unreachable.",
    # ★ The metric that makes §6.5's fail-open honest. Rate limiting fails open when
    # Redis is down — a protection mechanism must not convert a Redis blip into a
    # total outage — but "we stopped enforcing limits" is not something that may
    # happen silently. This is the counter that says it out loud.
    registry=REGISTRY,
)


def render_metrics() -> tuple[bytes, str]:
    """Render the registry for the ``LE_METRICS_PATH`` endpoint.

    Returns:
        ``(body, content_type)`` — ready for a ``Response``.
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
