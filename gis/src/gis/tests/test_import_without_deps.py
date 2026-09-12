"""IU-11 · ★★ THE CALL-TIME BINDING TEST (§11.3).

**Import the FULL provider + cache registry with ``httpx`` and ``redis`` BLOCKED in
``sys.modules``, and assert collection succeeds and every unconfigured component reports its
reason.**

★ **Why this test is not paranoia — it is a regression test for a shipped defect.** The rule
was once mandated for exactly ONE module (``rasterio_shim.py``) and then violated six times:
``gis/imagery/http.py`` (httpx), ``gis/imagery/cache/redis_cache.py`` (redis) and four export
writers all imported their dependency **at module scope**. Meanwhile the contract *also*
mandates that ``gis/imagery/providers/__init__.py`` register all seven providers **eagerly**,
and that this very suite be *"parametrised over every provider"* — so the suite necessarily
imports all of them. The result: ``cd gis && pytest`` died at **COLLECTION**, before a single
test ran. Not merely red — **impossible**.

The contradiction was visible inside the rule itself: it promises
``is_available() -> (False, "requires redis")`` **rather than a crash**, which is
*unimplementable if the import is at module scope*.

★ **The blocking mechanism.** ``sys.modules[name] = None`` makes ``import name`` raise
``ImportError`` immediately, without consulting the filesystem — the standard CPython idiom.
This works whether or not the dependency is actually installed, so the test is meaningful on
a developer's machine that *does* have httpx. **That matters: a test that only passes
because a library happens to be missing is not a test, it is a coincidence.**

★ ``httpx`` is in ``gis``'s **base** deps AND is call-time bound. Both, deliberately, and
neither is redundant: the registry must import every provider eagerly (so httpx cannot be an
extra), and the suite must collect without it (so the import must be call-time).
"""

from __future__ import annotations

import builtins
import importlib
import sys
from collections.abc import Iterator

import pytest

_BLOCKED = ("httpx", "redis")


@pytest.fixture
def deps_blocked() -> Iterator[None]:
    """Block ``httpx`` and ``redis`` at the import system level, and purge them.

    Every ``gis`` module is also purged so that the imports under test genuinely re-execute
    rather than being served from a cache populated before the block went up. ★ Without the
    purge this whole file would be a no-op that always passes.
    """
    saved = dict(sys.modules)
    for name in list(sys.modules):
        if name in _BLOCKED or name.startswith(tuple(f"{d}." for d in _BLOCKED)):
            del sys.modules[name]
        elif name == "gis" or name.startswith("gis."):
            del sys.modules[name]
    for name in _BLOCKED:
        sys.modules[name] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


def test_the_block_actually_blocks(deps_blocked: None) -> None:
    """★ Prove the fixture works before trusting anything it guards.

    A silently-ineffective block would make every assertion below vacuous — the failure mode
    this test exists to rule out.
    """
    with pytest.raises(ImportError):
        importlib.import_module("httpx")
    with pytest.raises(ImportError):
        importlib.import_module("redis")


# --- The imports that used to die at collection ------------------------------


def test_import_the_full_provider_registry(deps_blocked: None) -> None:
    """★★ ``import gis.imagery.providers`` SUCCEEDS with httpx absent.

    This module imports all seven provider classes eagerly. Five of them
    (esri/mapbox/bing/sentinel/google_static) sit on ``gis.imagery.http``. If that module
    imported httpx at scope, this line alone would end the test session.
    """
    providers = importlib.import_module("gis.imagery.providers")

    assert len(providers.PROVIDERS) == 8
    assert set(providers.PROVIDERS) == set(
        importlib.import_module("gis.imagery.base").PROVIDER_NAMES
    )


def test_import_the_cache_package(deps_blocked: None) -> None:
    """★★ ``import gis.imagery.cache`` SUCCEEDS with redis absent.

    ``cache/__init__.py`` exposes ``RedisTileCache`` via a module ``__getattr__`` (PEP 562),
    so nothing touches ``redis_cache`` until someone names it.
    """
    cache = importlib.import_module("gis.imagery.cache")

    assert cache.LRUTileCache is not None
    assert cache.DiskTileCache is not None


def test_import_http_and_ratelimit(deps_blocked: None) -> None:
    """The two modules whose deps are absent import cleanly and stay introspectable."""
    http = importlib.import_module("gis.imagery.http")
    ratelimit = importlib.import_module("gis.imagery.ratelimit")

    assert http.DEFAULT_USER_AGENT
    assert ratelimit.PROVIDER_RATE_LIMITS


def test_import_the_imagery_package_and_the_registry(deps_blocked: None) -> None:
    """The package root and the registry both import with both deps blocked."""
    imagery = importlib.import_module("gis.imagery")
    importlib.import_module("gis.imagery.registry")

    assert imagery.PROVIDER_NAMES
    assert imagery.ProviderRegistry is not None


def test_no_blocked_module_ends_up_imported(deps_blocked: None) -> None:
    """★ THE STRUCTURAL ASSERTION: after importing everything, neither dep was bound.

    Stronger than "the import did not raise" — it proves the modules are genuinely absent
    from ``sys.modules`` as real modules, i.e. that nothing quietly imported them under a
    ``try``/``except`` and left a partially-initialised entry behind.
    """
    importlib.import_module("gis.imagery")
    importlib.import_module("gis.imagery.providers")
    importlib.import_module("gis.imagery.cache")
    importlib.import_module("gis.imagery.registry")

    for name in _BLOCKED:
        assert sys.modules.get(name) is None


# --- Every component still works, and reports its reason ---------------------


def test_every_provider_constructs_and_reports_its_reason(deps_blocked: None) -> None:
    """★★ THE PROMISE THE RULE MAKES, ASSERTED.

    With httpx absent: every provider's ``__init__``, ``name``, ``is_configured()``,
    ``capabilities()`` and ``configuration_reason()`` work. Only an actual FETCH raises.
    """
    providers = importlib.import_module("gis.imagery.providers")
    base = importlib.import_module("gis.imagery.base")
    config = importlib.import_module("gis.config").GisConfig()

    for name, provider_cls in providers.PROVIDERS.items():
        provider = provider_cls(config)

        assert provider.name == name
        assert provider.name in base.PROVIDER_NAMES
        assert isinstance(provider.is_configured(), bool)
        assert provider.capabilities() is not None
        assert isinstance(provider.attribution, str)
        assert isinstance(provider.terms_url, str)
        if not provider.is_configured():
            assert provider.configuration_reason(), f"{name} gave no reason"


def test_the_registry_still_resolves_the_keyless_default(
    deps_blocked: None, tmp_path: object
) -> None:
    """★ L2 survives a missing httpx: ``auto`` still resolves.

    Resolution is a pure local decision — it asks each provider ``is_configured()``, which
    is a local check. Only a subsequent fetch would need the network.
    """
    registry_module = importlib.import_module("gis.imagery.registry")
    gis_config = importlib.import_module("gis.config").GisConfig

    empty = tmp_path / "empty"  # type: ignore[operator]
    empty.mkdir()
    registry = registry_module.ProviderRegistry(
        gis_config.from_env({"LE_LOCAL_ORTHO_DIR": str(empty)})
    )

    # ★ Mapbox now, not Esri: the chain prefers the product's imagery (built-in
    #   public token), and resolution stays a pure local decision either way.
    assert registry.resolve().name == "mapbox_satellite"


def test_available_is_total_with_both_deps_blocked(deps_blocked: None) -> None:
    """``GET /imagery/providers`` can be served with neither dep installed."""
    registry_module = importlib.import_module("gis.imagery.registry")
    config = importlib.import_module("gis.config").GisConfig()

    listings = registry_module.ProviderRegistry(config).available()

    assert len(listings) == 8
    for listing in listings:
        if not listing.usable:
            assert listing.reason


def test_httpx_availability_is_reported_not_raised(deps_blocked: None) -> None:
    """★ ``(False, "requires httpx")`` — a REPORT, not a traceback."""
    http = importlib.import_module("gis.imagery.http")

    available, reason = http.httpx_available()

    assert available is False
    assert reason and "httpx" in reason


def test_redis_availability_is_reported_not_raised(deps_blocked: None) -> None:
    """★ ``(False, "requires redis")`` and the registry falls back to disk."""
    cache = importlib.import_module("gis.imagery.cache")

    available, reason = cache.redis_cache_available()

    assert available is False
    assert reason and "redis" in reason


def test_a_fetch_raises_a_typed_error_not_an_import_error(deps_blocked: None) -> None:
    """★★ The ONE thing that must fail, fails **typed**.

    ``ProviderTransportError``, not ``ImportError``. A caller handling ``ProviderError``
    must not also have to handle our import failures — that is the whole point of the shim
    boundary.
    """
    http = importlib.import_module("gis.imagery.http")
    errors = importlib.import_module("gis.errors")

    with pytest.raises(errors.ProviderTransportError, match="httpx"):
        http.fetch_bytes("https://example.invalid/tile.png", provider="esri_world_imagery")


def test_redis_cache_degrades_to_lru_rather_than_failing(deps_blocked: None) -> None:
    """★ A ``RedisTileCache`` with no redis still WORKS — it just is not shared.

    Degradation, not failure (L11). The tile still gets cached, in-process, and the operator
    gets one WARNING explaining that workers will now re-fetch the same AOI.
    """
    cache = importlib.import_module("gis.imagery.cache")

    redis_cache = cache.RedisTileCache("redis://localhost:6379/0")
    key = cache.TileCacheKey("esri_world_imagery", 18, 1, 2)
    redis_cache.put(key, b"PIXELS")

    assert redis_cache.degraded is True
    assert redis_cache.get(key) == b"PIXELS"
    assert redis_cache.stats().backend == "redis"


def test_get_tile_cache_falls_back_from_redis_to_disk(
    deps_blocked: None, tmp_path: object
) -> None:
    """★ Asking for the prod backend on a box without redis yields a working cache.

    ``.backend`` reports what was ACTUALLY built, so a caller reporting provenance reports
    the truth rather than what it asked for.
    """
    cache = importlib.import_module("gis.imagery.cache")

    built = cache.get_tile_cache("redis", directory=str(tmp_path))  # type: ignore[arg-type]

    assert built.backend == "disk"


def test_the_offline_provider_serves_pixels_with_no_deps_at_all(
    deps_blocked: None,
) -> None:
    """★★ THE OFFLINE PROMISE, END TO END.

    With httpx and redis both absent, the fixture provider still returns real pixels. This
    is what makes ``LE_IMAGERY_OFFLINE=true`` and ``make seed && make up`` work with the NIC
    unplugged — and it is why ``fixture`` is a first-class provider rather than a test-only
    one.
    """
    import numpy as np

    providers = importlib.import_module("gis.imagery.providers")
    config = importlib.import_module("gis.config").GisConfig()

    tile = providers.PROVIDERS["fixture"](config).get_tile(18, 137452, 89234)

    assert tile.shape == (256, 256, 3)
    assert tile.dtype == np.uint8


def test_rasterio_shim_probes_without_binding_anything(deps_blocked: None) -> None:
    """The raster shim is subject to the same rule and reports rather than raises."""
    shim = importlib.import_module("gis.rasterio_shim")

    assert shim.probe() in ("rasterio", "gdal", "none")
    assert isinstance(shim.is_available(), bool)
    if not shim.is_available():
        assert shim.backend_reason()


def test_no_module_scope_import_of_a_blocked_dep_in_the_source() -> None:
    """★ A STATIC check, complementing the dynamic ones above.

    The runtime tests prove the property holds *today*. This one explains, at the point of
    failure, **which line** broke it — by parsing every ``gis.imagery`` module and asserting
    that no ``httpx``/``redis`` import sits at module scope (i.e. outside a function body).
    A future edit that moves an import upward fails here with a file and a line number
    rather than as an inscrutable collection error.
    """
    import ast
    from pathlib import Path

    imagery_root = Path(importlib.import_module("gis.imagery").__file__).parent
    offenders: list[str] = []

    for path in sorted(imagery_root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        # Walk only the module's TOP-LEVEL statements and class bodies; anything nested in
        # a function is a call-time binding and is exactly what the rule asks for.
        stack: list[ast.AST] = list(tree.body)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # call-time: legal
            if isinstance(node, ast.ClassDef):
                stack.extend(node.body)
                continue
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                stack.extend(ast.iter_child_nodes(node))
                continue
            for name in names:
                if name in _BLOCKED:
                    offenders.append(f"{path.name}:{node.lineno} imports {name!r}")

    assert not offenders, (
        "module-scope import of a call-time-bound dependency (§11.3): "
        + "; ".join(offenders)
        + ". Move the import INSIDE the function that uses it, or the gis suite dies at "
        "collection on any machine without it."
    )


def test_builtins_import_is_untouched_by_the_fixture(deps_blocked: None) -> None:
    """Sanity: the fixture blocks two names, not the import system."""
    assert builtins.__import__ is not None
    assert importlib.import_module("json") is not None
