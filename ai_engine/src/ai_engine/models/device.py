"""Compute placement — the module that **asks** rather than assumes.

``torch 2.11.0+cu130`` is installed on the verified box and ``torch.cuda.is_available()``
is **False**. Inferring a device from a wheel name is therefore a bug that reports itself
as a CUDA error deep inside a worker, hours later. `LE_AI_DEVICE=auto` resolves here, by
asking, to `cpu`.

★ Device unavailability is the SAME failure class as a missing weight file (§11.2), and it
routes through the SAME branch of `resolve_with_fallback` (step 4). It is a WARNING and a
fallback, never a crash. On this machine it is the branch that actually fires.
"""

from __future__ import annotations

from functools import lru_cache

from ai_engine.logging import get_logger
from ai_engine.models.torch_guard import torch_is_installed, try_import_torch
from ai_engine.types.enums import Device

__all__ = ["cuda_available", "describe_device", "device_is_satisfiable", "select_device"]

_log = get_logger(__name__)


@lru_cache(maxsize=1)
def cuda_available() -> bool:
    """Report whether a usable CUDA device exists — by asking torch, not by guessing.

    ★ THE PROBE IS DELIBERATELY LAZY AND CACHED, and both properties are load-bearing:

    * **Lazy.** If torch is not installed the answer is False and *torch is never
      imported* — `find_spec` settles it. This is what lets `resolve_with_fallback` walk
      a chain past a deep backend without paying for a torch import, which
      `test_registry_fallback.py` pins with a `sys.modules` probe.
    * **Cached.** When torch *is* installed the answer costs a multi-second import, and
      it cannot change under a running interpreter. `preflight()` pays it once at boot,
      which is precisely where §11.1 wants that cost paid.

    Returns:
        True only if torch imported successfully AND reports an available CUDA device.
        Any failure to answer is False: an unusable GPU and an unaskable one lead to the
        same place, and that place is the CPU.
    """
    if not torch_is_installed():
        return False

    torch = try_import_torch()
    if torch is None:
        return False

    try:
        return bool(torch.cuda.is_available())
    except Exception as exc:  # noqa: BLE001 — a probe that raises still has to answer
        _log.warning(
            "torch.cuda.is_available() raised (%s: %s); treating CUDA as unavailable and "
            "continuing on the CPU.",
            type(exc).__name__,
            exc,
        )
        return False


def select_device(preference: Device = Device.AUTO) -> Device:
    """Resolve a device *preference* into the device that will actually be used.

    * ``AUTO``  → ``CUDA`` when one is genuinely available, else ``CPU``. On the verified
      box this is ``CPU``.
    * ``CPU``   → ``CPU``. Always satisfiable; never probes torch.
    * ``CUDA``  → ``CUDA`` when available, else **WARN and ``CPU``** (§11.2). Never raises:
      an explicitly requested but absent GPU is a degradation, not a configuration error.

    Args:
        preference: What the caller would like.

    Returns:
        The device that will actually be used. Never ``AUTO`` — this function's entire
        purpose is to collapse that member.
    """
    if preference is Device.CPU:
        return Device.CPU

    if preference is Device.AUTO:
        return Device.CUDA if cuda_available() else Device.CPU

    if preference is Device.CUDA:
        if cuda_available():
            return Device.CUDA
        _log.warning(
            "device=cuda was requested but no usable CUDA device is present "
            "(torch.cuda.is_available() is False — note that a '+cuXXX' wheel name is "
            "not evidence of a GPU). Falling back to the CPU."
        )
        return Device.CPU

    # Unreachable while Device has three members; kept so that adding a fourth fails
    # loudly here rather than silently defaulting something onto the wrong hardware.
    raise ValueError(f"unhandled device preference {preference!r}")


def device_is_satisfiable(preference: Device) -> tuple[bool, str | None]:
    """Report whether `preference` can be honoured **exactly**, and why not if it cannot.

    ★ This is step 4 of `resolve_with_fallback`, and the asymmetry with
    :func:`select_device` is deliberate. `select_device` answers *"where will this run?"*
    and always answers CPU at worst. This answers *"can this component have what it
    asked for?"* — a component pinned to ``CUDA`` on a CPU-only box has NOT had its
    preference met, and the policy layer must fall back to a component that can run,
    rather than silently dragging a GPU-only backend onto the CPU.

    ``AUTO`` and ``CPU`` are always satisfiable and **never probe torch**, which is what
    keeps the classical chain torch-free.

    Args:
        preference: The `ComponentSpec.device_preference` under test.

    Returns:
        ``(True, None)`` when the preference can be met, else ``(False, reason)``.
    """
    if preference in (Device.AUTO, Device.CPU):
        return True, None
    if preference is Device.CUDA:
        if cuda_available():
            return True, None
        return False, "device unavailable: cuda requested but torch reports no usable CUDA device"
    return False, f"device unavailable: unknown device preference {preference!r}"


def describe_device(preference: Device = Device.AUTO) -> str:
    """Return a one-line, human-readable account of the device decision.

    Written for the `PreflightReport.messages` list and the boot log, where an operator
    who expected a GPU needs to learn otherwise in one line rather than by reading code.
    """
    selected = select_device(preference)
    if not torch_is_installed():
        return f"device: {selected} (torch is not installed; deep backends unavailable)"
    if selected is Device.CUDA:
        return f"device: {selected} (a usable CUDA device is present)"
    if preference is Device.CUDA:
        return f"device: {selected} (cuda was requested but is unavailable — degraded to cpu)"
    return f"device: {selected} (torch is installed; torch.cuda.is_available() is False)"
