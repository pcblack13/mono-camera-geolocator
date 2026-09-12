"""Logging for `ai_engine` — a LIBRARY's logging, which means it configures nothing.

★ THIS MODULE NEVER ADDS A HANDLER, NEVER SETS A LEVEL, AND NEVER TOUCHES THE ROOT
LOGGER. Handler configuration belongs to the application that embeds the engine — the
backend, a notebook, a CLI, a QGIS plugin. A library that configures logging steals a
decision from every one of them, and it does it as an import side effect, which is the
worst possible time.

What this module is actually for: every logger in the package hangs off the single
`ai_engine.*` namespace, so an embedder can silence or raise the whole engine with one
line:

    logging.getLogger("ai_engine").setLevel(logging.WARNING)

The engine's warnings are not noise. L11 requires that a missing weight, a missing key or
an unavailable device is a WARNING and a fallback — never a traceback and NEVER SILENT. A
user who configured SuperPoint and got SIFT learns about it through exactly one channel:
a log line emitted here. Do not lower those to DEBUG.
"""

from __future__ import annotations

import logging

__all__ = ["LOGGER_NAMESPACE", "get_logger"]

#: The single namespace every logger in this package lives under.
LOGGER_NAMESPACE = "ai_engine"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the `ai_engine.<name>` logger.

    Args:
        name: A dotted suffix, conventionally the calling module's `__name__`. A full
            module path under this package (``"ai_engine.extractors.sift"``) is used as
            is; a bare suffix (``"extractors.sift"``) is prefixed. None returns the
            package's root logger.

    Returns:
        A standard `logging.Logger`. No handlers are attached and no level is set, so it
        inherits whatever the embedding application configured. With no configuration at
        all, Python's `lastResort` handler emits WARNING and above to stderr — which is
        the right default for a library: the L11 fallback warnings are visible out of the
        box, and nothing else is.
    """
    if name is None:
        return logging.getLogger(LOGGER_NAMESPACE)
    if name == LOGGER_NAMESPACE or name.startswith(f"{LOGGER_NAMESPACE}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")
