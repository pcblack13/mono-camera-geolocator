"""★ THE ONLY MODULE IN `ai_engine` THAT MAY IMPORT `torch` (L8).

Everywhere else, torch is reached through :func:`try_import_torch`, which returns the
module or ``None`` and **never raises**. That is the whole mechanism behind L11: a box
with no torch, a broken CUDA driver, or a half-installed wheel produces a warning and a
classical path, not a traceback at import time.

Why a single site rather than a convention:

* **It is greppable and lintable.** `.importlinter`'s `torch-single-entry` contract and
  a one-line grep both check exactly one file. A convention spread over nine modules is
  checked by nobody.
* **Importing torch is not free.** It costs seconds and can initialise CUDA. Every other
  module in the package must be able to decide *whether* it needs torch without paying
  for the answer — hence :func:`torch_is_installed`, which uses `importlib.util.find_spec`
  and imports nothing.
* **`+cu130` in the wheel name means nothing.** torch 2.11.0+cu130 is installed on the
  verified box and `torch.cuda.is_available()` is False. The device layer asks; it never
  infers.

★ In this build nothing calls into torch at all: every deep component is deferred (see
``docs/architecture/SCOPE.md``). This module is nonetheless real and complete, because it
is the seam the deep components will bind through when they are implemented, and because
:func:`cuda_available` in `device.py` needs an honest answer to report in the
`PreflightReport` rather than an assumed one.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec
from types import ModuleType

from ai_engine.logging import get_logger

__all__ = ["TORCH_MODULE_NAME", "torch_is_installed", "try_import_torch"]

_log = get_logger(__name__)

#: The module name probed and imported. Named once so the grep gates and the
#: `requires_packages` entries on every deep `ComponentSpec` cannot drift apart.
TORCH_MODULE_NAME = "torch"


def torch_is_installed() -> bool:
    """Report whether `torch` is importable **without importing it**.

    Uses `importlib.util.find_spec`, so there are no module side effects, no CUDA
    initialisation, and no multi-second import just to discover we will not use it. This
    is what `models.policy` probes with (§4.14 step 2), and `test_registry_fallback.py`
    asserts via a `sys.modules` probe that a chain falling back before it reaches a deep
    backend leaves `torch` unimported.

    Returns:
        True if a spec for `torch` can be found on the current path.
    """
    try:
        return find_spec(TORCH_MODULE_NAME) is not None
    except (ImportError, ValueError):
        # ValueError: the module is present in sys.modules but has no __spec__ — which is
        # exactly what a test's sys.modules sentinel looks like. Treat it as absent
        # rather than propagating: this function's entire job is to answer, not to raise.
        return False


@lru_cache(maxsize=1)
def try_import_torch() -> ModuleType | None:
    """Import `torch` and return the module, or return None if it cannot be had.

    ★ NEVER RAISES, AND NEVER PARTIALLY SUCCEEDS. A missing torch, a torch that raises on
    import (a mismatched CUDA runtime does exactly this), or any other import-time
    explosion all produce the same thing: ``None`` and one WARNING line. The caller's job
    is then to fall back, which is L11.

    The result is cached for the process: importing torch costs seconds, and the answer
    cannot change under a running interpreter.

    Returns:
        The `torch` module, or None if it is not installed or failed to import.
    """
    if not torch_is_installed():
        _log.info(
            "torch is not installed; deep backends are unavailable and the engine will "
            "use its classical path. This is a supported configuration, not an error."
        )
        return None

    try:
        import torch  # noqa: PLC0415 — the guarded, deliberate, single import site (L8)
    except Exception as exc:  # noqa: BLE001 — an import that raises must still fall back
        _log.warning(
            "torch is installed but failed to import (%s: %s); deep backends are "
            "unavailable and the engine will use its classical path.",
            type(exc).__name__,
            exc,
        )
        return None

    _log.debug("torch %s imported", getattr(torch, "__version__", "unknown"))
    return torch
