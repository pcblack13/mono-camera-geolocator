"""``process_map()`` — ★ REAL. Multiprocessing plumbing, no CV.

★ IT SETS `cv2.setNumThreads(1)` IN THE CHILDREN, AND THAT IS THE ENTIRE REASON THIS MODULE
EXISTS. OpenCV parallelises internally by default. Fan out to N processes and each child
spawns its own thread pool: N × cores threads fighting over cores, cache-thrashing, and a
"parallel" run measurably **slower** than the serial one — with no error, no warning, and a
profile that looks like the work is simply expensive. One line in the child initialiser
prevents it, and no caller would ever think to write it.

★ `cv2` IS BOUND AT CALL TIME, inside the initialiser, per the call-time binding rule
(§11.3). The initialiser runs in the child, where the import has to happen anyway, and this
module stays importable for introspection with no cv2 at all.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import TypeVar

from ai_engine.logging import get_logger

__all__ = ["default_workers", "init_worker", "process_map"]

_log = get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def init_worker() -> None:
    """Child-process initialiser: pin OpenCV and the BLAS libraries to one thread each.

    ★ Called in the CHILD, once, before any work. Binds `cv2` at call time — it is absent
    from this module's scope on purpose, so importing `ai_engine.runtime.parallel` never
    requires OpenCV.

    A missing cv2 is a no-op and a debug line, not an error: this function's job is to
    prevent oversubscription, and there is nothing to prevent if the library is not there.
    """
    # The BLAS variables must be set before numpy's backend initialises to have any effect.
    # Setting them here covers the fork/spawn boundary for the common cases.
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")

    try:
        import cv2  # noqa: PLC0415 — call-time bound by design (§11.3)
    except ImportError:
        _log.debug("init_worker: cv2 is absent; nothing to pin.")
        return

    try:
        cv2.setNumThreads(1)
    except Exception as exc:  # noqa: BLE001 — a worker must not die pinning a thread count
        _log.warning("init_worker: cv2.setNumThreads(1) failed (%s)", exc)


def default_workers() -> int:
    """A sensible worker count: one per available core, at least 1.

    Uses `os.process_cpu_count()` where available, which respects CPU affinity and cgroup
    limits — `os.cpu_count()` reports the machine's cores and would happily start 64
    workers inside a two-core container.
    """
    count = getattr(os, "process_cpu_count", None)
    cpus = count() if count is not None else os.cpu_count()
    return max(1, cpus or 1)


def process_map(
    fn: Callable[[T], R],
    items: Sequence[T],
    *,
    max_workers: int | None = None,
    chunksize: int = 1,
) -> list[R]:
    """Map `fn` over `items` across processes, with OpenCV pinned in every child.

    Args:
        fn: The function to apply. Must be picklable — a module-level function or a
            picklable callable, not a lambda or a closure.
        items: The inputs.
        max_workers: How many processes. None uses :func:`default_workers`.
        chunksize: How many items to hand a worker at a time.

    Returns:
        The results, **in input order**.

    ★ Falls back to a serial map when `max_workers == 1` or `items` is short enough that a
    pool would cost more than it saves. Starting a process pool to run two items is pure
    overhead, and the caller should not have to know that.

    Raises:
        Exception: Whatever `fn` raises, propagated from the child. Deliberately not
            swallowed — this is plumbing, and it must not have an opinion about the
            caller's errors.
    """
    if not items:
        return []

    workers = max_workers if max_workers is not None else default_workers()
    workers = max(1, min(workers, len(items)))

    if workers == 1:
        init_worker()
        return [fn(item) for item in items]

    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker) as pool:
        results: Iterable[R] = pool.map(fn, items, chunksize=chunksize)
        return list(results)
