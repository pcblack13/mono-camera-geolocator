"""An in-process ring buffer of recent log lines — what powers ``GET /health/logs``.

★ WHY IT EXISTS. The desktop app has no terminal: when something fails in the field,
the operator's only window into the process is the app itself. The buffer sits on the
ROOT logger beside the stdout handler, so it sees exactly the lines a terminal would —
uvicorn's, SQLAlchemy's and our own — after the SAME processor chain, **scrubbing
included** (§9.10). A log surface that bypassed the scrubber would be the one place
a connection string escapes to a screenshot.

★ BOUNDED, ALWAYS. A ``deque(maxlen=…)`` cannot grow without limit; a flood of
errors evicts old lines instead of eating the process. ``seq`` is a monotonically
increasing cursor, so a poller asks "everything after N" and eviction never makes it
re-read or miss what it already has (it can only mean lines were dropped, which
``dropped_before`` makes visible instead of silent).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "DEFAULT_CAPACITY",
    "LEVEL_NAMES",
    "LogRingBuffer",
    "RingBufferLogHandler",
    "get_log_buffer",
    "install_ring_buffer_handler",
    "level_to_number",
]

DEFAULT_CAPACITY: Final = 2000

#: The wire vocabulary for ``?level=`` — stdlib numbers, lowercase names (§7).
LEVEL_NAMES: Final[dict[str, int]] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def level_to_number(name: str) -> int:
    """``"warning"`` → 30. An unknown name means "no filter", never a 500."""
    return LEVEL_NAMES.get(name.lower(), logging.DEBUG)


class LogRingBuffer:
    """The store: a bounded deque of ``(seq, levelno, entry)``, thread-safe.

    Log emission happens on request threads, worker threads and the event loop at
    once; the lock covers every read and write of the deque and the counter.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        """A bounded store; ``capacity`` is the most lines it will ever hold."""
        self.capacity = capacity
        self._entries: deque[tuple[int, int, dict[str, Any]]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def append(self, levelno: int, entry: dict[str, Any]) -> None:
        """Store one entry, stamping it with the next ``seq``."""
        with self._lock:
            self._seq += 1
            entry["seq"] = self._seq
            self._entries.append((self._seq, levelno, entry))

    @property
    def last_seq(self) -> int:
        """The cursor of the newest line ever seen — filter-independent."""
        with self._lock:
            return self._seq

    def dropped_before(self) -> int:
        """The seq below which lines have been evicted — 0 when nothing has been."""
        with self._lock:
            return self._entries[0][0] - 1 if self._entries else self._seq

    def snapshot(
        self,
        *,
        after: int = 0,
        min_levelno: int = logging.DEBUG,
        contains: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """The newest ``limit`` entries matching ``seq > after`` and the filters.

        The TAIL, deliberately: when more lines match than fit, the operator wants
        the latest ones — the failure they are looking at — not last hour's.
        """
        with self._lock:
            candidates = [
                e for (seq, lvl, e) in self._entries if seq > after and lvl >= min_levelno
            ]
        if contains:
            needle = contains.lower()
            candidates = [
                e
                for e in candidates
                if needle in json.dumps(e, default=str, ensure_ascii=False).lower()
            ]
        return candidates[-limit:]

    def clear(self) -> None:
        """Tests only — the cursor survives so pollers never see time run backwards."""
        with self._lock:
            self._entries.clear()


class RingBufferLogHandler(logging.Handler):
    """Formats every record through the structlog chain and stores the parsed dict.

    The formatter's renderer is a ``JSONRenderer`` (``ProcessorFormatter`` requires a
    string), so ``format`` → ``json.loads`` round-trips the event dict — with
    ``default=str`` a Path, a UUID or an exception in a field becomes its string
    rather than a serialisation error that loses the one line that mattered.
    """

    def __init__(self, buffer: LogRingBuffer) -> None:
        """Capture into ``buffer``; level gating is the root logger's job."""
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 — logging API
        try:
            formatted = self.format(record)
            try:
                parsed = json.loads(formatted)
                entry: dict[str, Any] = (
                    parsed if isinstance(parsed, dict) else {"event": str(parsed)}
                )
            except ValueError:
                entry = {"event": str(formatted)}
            entry.setdefault("level", record.levelname.lower())
            entry.setdefault("logger", record.name)
            entry.setdefault("timestamp", datetime.now(tz=UTC).isoformat())
            self._buffer.append(record.levelno, entry)
        except Exception:  # a log line must never take a request down
            self.handleError(record)


#: The process-wide buffer. A singleton on purpose: ``configure_logging`` is
#: idempotent and replaces every handler, but the LINES must survive a reconfigure.
_BUFFER = LogRingBuffer()


def get_log_buffer() -> LogRingBuffer:
    """The buffer ``GET /health/logs`` reads."""
    return _BUFFER


def install_ring_buffer_handler(
    pre_chain: list[Any],
    scrubber: Callable[..., Any],
) -> logging.Handler:
    """A handler for the root logger that captures into :func:`get_log_buffer`.

    ``pre_chain`` is ``configure_logging``'s shared chain (timestamp, level, logger
    name, **scrub**) — foreign records (uvicorn, SQLAlchemy) go through it here just
    as they do for stdout. ``scrubber`` runs AGAIN after ``format_exc_info``, because
    a traceback materialised after the pre-chain would otherwise be the one string
    never scrubbed — the exact trap ``configure_logging``'s own comment describes.
    """
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            scrubber,
            structlog.processors.JSONRenderer(default=str, ensure_ascii=False),
        ],
    )
    handler = RingBufferLogHandler(_BUFFER)
    handler.setFormatter(formatter)
    return handler
