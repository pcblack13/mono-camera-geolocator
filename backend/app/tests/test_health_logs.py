"""``GET /health/logs`` and the ring buffer behind it.

★ What these pin: the buffer is bounded and its cursor is monotonic (a poller can
never re-read or silently miss), the handler captures FOREIGN records through the
same chain stdout gets — **scrubbing included**, tracebacks materialised — and the
endpoint's filters (``after`` / ``level`` / ``q`` / ``limit``) do what the app-status
page relies on them doing.
"""

from __future__ import annotations

import logging

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import health as health_router
from app.core import logbuffer
from app.core.logbuffer import (
    LogRingBuffer,
    install_ring_buffer_handler,
    level_to_number,
)
from app.core.logging import scrub_secrets

# ── the store ───────────────────────────────────────────────────────────────────


def test_buffer_seq_is_monotonic_and_capacity_evicts() -> None:
    buf = LogRingBuffer(capacity=3)
    for i in range(5):
        buf.append(logging.INFO, {"event": f"line {i}"})
    assert buf.last_seq == 5
    # Bounded: the two oldest lines were evicted, and that is REPORTED, not silent.
    assert buf.dropped_before() == 2
    got = buf.snapshot()
    assert [e["event"] for e in got] == ["line 2", "line 3", "line 4"]
    assert [e["seq"] for e in got] == [3, 4, 5]


def test_snapshot_filters_after_level_contains_and_tails() -> None:
    buf = LogRingBuffer(capacity=10)
    buf.append(logging.INFO, {"event": "boot"})
    buf.append(logging.WARNING, {"event": "slow tile fetch"})
    buf.append(logging.ERROR, {"event": "db down", "detail": "connect refused"})
    buf.append(logging.INFO, {"event": "recovered"})

    assert [e["event"] for e in buf.snapshot(after=2)] == ["db down", "recovered"]
    assert [e["event"] for e in buf.snapshot(min_levelno=logging.WARNING)] == [
        "slow tile fetch",
        "db down",
    ]
    # ``contains`` searches every field, case-insensitively — not just the message.
    assert [e["event"] for e in buf.snapshot(contains="REFUSED")] == ["db down"]
    # The TAIL wins when limit bites: the newest lines are the failure being read.
    assert [e["event"] for e in buf.snapshot(limit=2)] == ["db down", "recovered"]


def test_level_to_number_never_raises() -> None:
    assert level_to_number("warning") == logging.WARNING
    assert level_to_number("WARNING") == logging.WARNING
    # An unknown name means "no filter", never a 500 from a health surface.
    assert level_to_number("nonsense") == logging.DEBUG


# ── the handler: foreign records, tracebacks, scrubbing ─────────────────────────


@pytest.fixture()
def isolated_capture(monkeypatch: pytest.MonkeyPatch) -> tuple[logging.Logger, LogRingBuffer]:
    """A private logger wired to a FRESH buffer through the real handler + chain."""
    buf = LogRingBuffer(capacity=50)
    monkeypatch.setattr(logbuffer, "_BUFFER", buf)
    pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.UnicodeDecoder(),
        scrub_secrets,
    ]
    handler = install_ring_buffer_handler(pre_chain, scrub_secrets)
    logger = logging.getLogger("test.health.logs.capture")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield logger, buf
    logger.handlers = []


def test_foreign_record_is_captured_with_level_logger_and_timestamp(
    isolated_capture: tuple[logging.Logger, LogRingBuffer],
) -> None:
    logger, buf = isolated_capture
    logger.warning("tile cache at %d%%", 93)
    (entry,) = buf.snapshot()
    assert entry["event"] == "tile cache at 93%"
    assert entry["level"] == "warning"
    assert entry["logger"] == "test.health.logs.capture"
    assert entry["timestamp"]  # ISO string from the pre-chain's TimeStamper


def test_exception_is_materialised_and_scrubbed(
    isolated_capture: tuple[logging.Logger, LogRingBuffer],
) -> None:
    logger, buf = isolated_capture
    try:
        raise RuntimeError("connect failed: Authorization: Bearer sk_live_12345678")
    except RuntimeError:
        logger.error("db down", exc_info=True)
    (entry,) = buf.snapshot()
    assert entry["level"] == "error"
    # The traceback exists as a field — the log monitor's whole reason to exist —
    # and the secret inside it went through the scrubber, not around it (§9.10).
    assert "RuntimeError" in entry["exception"]
    assert "sk_live_12345678" not in entry["exception"]
    assert "Bearer ***" in entry["exception"]


def test_secret_message_is_scrubbed(
    isolated_capture: tuple[logging.Logger, LogRingBuffer],
) -> None:
    logger, buf = isolated_capture
    logger.info("fetching https://user:hunter2@example.com/tiles?key=abc123def")
    (entry,) = buf.snapshot()
    assert "hunter2" not in entry["event"]
    assert "abc123def" not in entry["event"]


# ── the endpoint ────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    buf = LogRingBuffer(capacity=100)
    buf.append(logging.INFO, {"event": "api.started", "timestamp": "t1", "level": "info"})
    buf.append(
        logging.ERROR,
        {
            "event": "job.failed",
            "timestamp": "t2",
            "level": "error",
            "request_id": "01J",
            "exception": "Traceback ...",
            "job_id": "j-1",
        },
    )
    buf.append(logging.INFO, {"event": "api.recovered", "timestamp": "t3", "level": "info"})
    monkeypatch.setattr(logbuffer, "_BUFFER", buf)
    app = FastAPI()
    app.include_router(health_router.router)
    return TestClient(app)


def test_logs_endpoint_returns_entries_and_cursor(client: TestClient) -> None:
    res = client.get("/health/logs")
    assert res.status_code == 200
    body = res.json()
    assert [e["event"] for e in body["entries"]] == ["api.started", "job.failed", "api.recovered"]
    assert body["last_seq"] == 3
    assert body["dropped_before"] == 0
    assert body["capacity"] == 100
    # Known keys are promoted; everything else rides in ``fields``.
    failed = body["entries"][1]
    assert failed["request_id"] == "01J"
    assert failed["exception"] == "Traceback ..."
    assert failed["fields"] == {"job_id": "j-1"}


def test_logs_endpoint_filters(client: TestClient) -> None:
    assert [e["event"] for e in client.get("/health/logs?level=error").json()["entries"]] == [
        "job.failed"
    ]
    assert [e["event"] for e in client.get("/health/logs?after=2").json()["entries"]] == [
        "api.recovered"
    ]
    assert [e["event"] for e in client.get("/health/logs?q=j-1").json()["entries"]] == [
        "job.failed"
    ]
    assert [e["event"] for e in client.get("/health/logs?limit=1").json()["entries"]] == [
        "api.recovered"
    ]
    # A bad level is a 422 (Literal), not a silent full dump.
    assert client.get("/health/logs?level=loud").status_code == 422


def test_configure_logging_wires_the_buffer_to_the_root_logger() -> None:
    """The integration seam.

    After ``configure_logging``, a structlog line lands in ``get_log_buffer()`` —
    the exact path production takes.
    """
    from app.core.config import Settings
    from app.core.logging import configure_logging, get_logger

    configure_logging(Settings())
    marker = "health-logs-integration-marker"
    get_logger("test.health.logs.integration").warning(marker)
    entries = logbuffer.get_log_buffer().snapshot(contains=marker)
    assert entries, "the root logger must feed the ring buffer"
    assert entries[-1]["event"] == marker
    assert entries[-1]["level"] == "warning"
