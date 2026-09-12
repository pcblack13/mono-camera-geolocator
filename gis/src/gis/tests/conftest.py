"""Shared fixtures for the ``gis`` suite. ★ NO NETWORK, EVER.

**What this module is.** The fixture *provider* for ``gis``: it owns the committed bytes
under ``fixtures/`` and hands them to any test that asks. It owns no assertions — every
``test_*.py`` in this directory belongs to the unit whose obligation it discharges (§3),
and this file must never make one of them pass.

**The no-network guarantee (§13: "No test may require network").** ``_no_network`` is
autouse and covers the whole directory, so the guarantee is a *proof* rather than a
convention: a provider that resolved DNS in ``__init__``, or a cache that quietly dialled
Redis, fails here loudly instead of being merely slow and flaky in CI. It blocks AF_INET
and AF_INET6 only — AF_UNIX is local IPC and is not the network, and blocking it would
break unrelated tooling for no gain.

**Fixture precedence.** A ``test_*.py`` that defines a fixture of the same name shadows the
one here, which is exactly what pytest should do: IU-10 and IU-11 deliberately define local
``ortho_tif`` / ``plain_tif`` that fall back to generating an equivalent when the committed
file is absent, so their suites stay verifiable independently of this unit's landing order.
Nothing here breaks that; it only gives everything else one place to get the real bytes.

**Regenerating the fixtures.** ``python3 gis/src/gis/tests/fixtures/_generate.py``.
★ Never at test time. A fixture the suite regenerates is not a fixture — it is a mirror of
whatever the code does today, and it cannot catch a regression in the code that writes it.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest

FIXTURES_DIR: Final[Path] = Path(__file__).parent / "fixtures"

# --- The committed ortho's mandated geometry ---------------------------------
#
# ★ Re-exported here so future tests have ONE definition to import instead of a fourth
#   hand-copied tuple. These values are NOT free to change: IU-10's test_raster.py and
#   IU-11's test_providers_contract.py each hardcode them and assert against the committed
#   file, and fixtures/_generate.py writes it. Four copies already exist; adding a fifth
#   that disagrees is the failure mode this constant exists to prevent.
ORTHO_GT: Final[tuple[float, float, float, float, float, float]] = (
    500000.0,
    0.5,
    0.0,
    5000000.0,
    0.0,
    -0.5,
)
ORTHO_EPSG: Final[int] = 32633
ORTHO_SIZE: Final[int] = 64

ORTHO_LON: Final[float] = 15.0
ORTHO_LAT: Final[float] = 45.1534772
"""The ortho's top-left corner in EPSG:4326.

500000 E is exactly UTM 33N's central meridian, so the longitude is exactly 15.0 rather
than approximately 15. The committed tiles cover this same ground.
"""

TILE_SIZE: Final[int] = 256

_ENV_VARS: Final[tuple[str, ...]] = (
    "LE_MAPBOX_ACCESS_TOKEN",
    "LE_BING_MAPS_KEY",
    "LE_COPERNICUS_CLIENT_ID",
    "LE_COPERNICUS_CLIENT_SECRET",
    "LE_COPERNICUS_INSTANCE_ID",
    "LE_GOOGLE_MAPS_STATIC_KEY",
    "LE_GOOGLE_TOS_ACKNOWLEDGED",
    "LE_LOCAL_ORTHO_DIR",
    "LE_LOCAL_DEM_DIR",
    "LE_IMAGERY_PROVIDER",
    "LE_IMAGERY_OFFLINE",
    "LE_IMAGERY_STRICT",
    "LE_IMAGERY_TILE_CACHE_DIR",
    "LE_ALLOWED_PROVIDERS",
    "LE_IMAGERY_FALLBACK_CHAIN",
    "LE_REDIS_URL",
)


# =============================================================================
# The no-network guarantee
# =============================================================================


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ Make any IP socket connection an immediate, loud failure. Autouse, suite-wide.

    §13's first line is "No test may require network". This turns that from a claim into a
    proof. ``gis`` is the package that talks to Esri, Mapbox, Bing, Sentinel and Google, so
    it is the package where an accidental fetch is most likely and least visible — a real
    request in CI is a flake; a real request in a contract test is a silent dependency on
    someone else's uptime.

    AF_UNIX is deliberately still permitted: local IPC is not the network.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _is_ip(sock: socket.socket) -> bool:
        return sock.family in (socket.AF_INET, socket.AF_INET6)

    def _blocked(what: str) -> AssertionError:
        return AssertionError(
            f"a gis test touched the network via {what}(). The gis suite is offline by "
            "contract (CONTRACT.md §13): use the committed fixtures under "
            "gis/src/gis/tests/fixtures/, the `fixture` provider, or a local GeoTIFF."
        )

    def _connect(self: socket.socket, *args: Any, **kwargs: Any) -> Any:
        if _is_ip(self):
            raise _blocked("socket.connect")
        return real_connect(self, *args, **kwargs)

    def _connect_ex(self: socket.socket, *args: Any, **kwargs: Any) -> Any:
        if _is_ip(self):
            raise _blocked("socket.connect_ex")
        return real_connect_ex(self, *args, **kwargs)

    def _create_connection(*args: Any, **kwargs: Any) -> Any:
        raise _blocked("socket.create_connection")

    def _getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        raise _blocked("socket.getaddrinfo")

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    monkeypatch.setattr(socket, "create_connection", _create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)


# =============================================================================
# The committed fixtures
# =============================================================================


def _committed(name: str) -> Path:
    """Return a committed fixture path, failing with a repair instruction if it is gone."""
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.fail(
            f"the committed fixture {name!r} is missing from {FIXTURES_DIR}. It is required "
            f"by CONTRACT.md §13.2 and is committed to git. Regenerate it with:\n"
            f"    python3 gis/src/gis/tests/fixtures/_generate.py",
            pytrace=False,
        )
    return path


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """The committed fixture directory."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def ortho_tif() -> Path:
    """★ The committed 64x64 EPSG:32633 GeoTIFF with a known geotransform (§13.2).

    Geotransform ``(500000.0, 0.5, 0.0, 5000000.0, 0.0, -0.5)`` — 0.5 m pixels, top-left at
    500000 E / 5000000 N in UTM 33N, which is exactly 15.0000000 E, 45.1534772 N. Three
    uint8 bands. ★ No nodata value is declared, and IU-10 asserts that.

    Backs ``LocalOrthophotoProvider``, ``detect_georeferencing()`` and the offline gis suite.
    """
    return _committed("synthetic_ortho.tif")


@pytest.fixture(scope="session")
def plain_tif() -> Path:
    """★★ A TIFF with NO georeferencing — the identity-transform trap (§13.2).

    GDAL returns ``(0, 1, 0, 0, 0, 1)`` for this file: a documented default, not a bug.
    Believing it places the image at 0N 0E with one-degree pixels — the Gulf of Guinea, at
    continental scale — and marks every scanned TIFF as georeferenced.

    **This fixture is the difference between ``is_geotiff`` meaning something and meaning
    nothing**, and in this build it is what decides whether an upload short-circuits to
    exact GCPs or goes to the surveyor for manual placement.
    """
    return _committed("plain.tif")


@pytest.fixture(scope="session")
def fixture_tiles_dir() -> Path:
    """The committed ``tiles/{z}/{x}/{y}.png`` set backing ``FixtureProvider``.

    256x256 PNGs over the same ground as ``synthetic_ortho.tif``, so the offline demo scene
    and the ortho are one place rather than two unrelated synthetic worlds. Pass it as
    ``FixtureProvider(tile_dir=...)``; any tile not committed is generated procedurally by
    the provider itself, so the set does not need to be complete.
    """
    return _committed("tiles")


@pytest.fixture(scope="session")
def slippy_goldens() -> dict[str, Any]:
    """§13.3's golden tile numbers and quadkeys, as committed JSON.

    ★ Computed from the PUBLISHED OSM/Bing reference formulae, never from ``gis.tiles`` — a
    golden recomputed by the code under test proves only that the code agrees with itself.

    ★ The ``London`` entry is ``x=2046``, not §13.3's printed ``2047``. The contract's own
    formula gives ``(-0.1278 + 180) / 360 * 4096 = 2046.5459…``, and tile 2046 spans lon
    ``[-0.17578125, -0.087890625)``, which contains -0.1278. See ``fixtures/_generate.py``.
    """
    return json.loads(_committed("slippy_goldens.json").read_text(encoding="utf-8"))


# =============================================================================
# Environment hygiene
# =============================================================================


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every LandExplorer imagery/credential variable from the environment.

    ★ Without this, "unconfigured" means "unconfigured on *this* developer's shell", and the
    suite passes or fails depending on whose laptop it runs on. L10 guarantees every setting
    has a working default; this fixture is how the suite actually exercises that path.
    """
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def ortho_dir(tmp_path: Path, ortho_tif: Path) -> Iterator[Path]:
    """A directory containing exactly the committed ortho, for ``LocalOrthophotoProvider``.

    Copied rather than pointed at the fixtures directory, so a provider that writes an index
    or a sidecar cannot mutate a committed file and leave the tree dirty.
    """
    directory = tmp_path / "orthophotos"
    directory.mkdir()
    (directory / ortho_tif.name).write_bytes(ortho_tif.read_bytes())
    yield directory
