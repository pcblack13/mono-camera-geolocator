"""Cross-package test fixtures. ★ NO NETWORK, EVER.

`tests/` is the only suite that may see more than one package at once (§2.8). Everything
here is therefore shared vocabulary — the committed photographs, the offline provider, and
the environment hygiene that keeps a result from depending on whose laptop ran it.

**The three tiers, and what each needs (§13.1 IU-31):**

| Directory | Needs | Runs on this machine? |
|---|---|---|
| `contract/` | nothing but the source files | ★ **yes, today** |
| `e2e/` | `gis` (+ the backend, for the API-driven half) | ★ the offline half runs today |
| `integration/` | a live PostgreSQL + PostGIS | no — `@pytest.mark.db`, auto-skipped |

★ **`integration/` skips automatically when `LE_DATABASE_URL` is unset**, so `pytest tests/`
on the dev machine is green rather than red-with-excuses. §13.1 IU-31 mandates exactly that.
A suite that is red by default trains everyone to ignore red.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FIXTURES_DIR: Final[Path] = Path(__file__).parent / "fixtures"

GIS_FIXTURES_DIR: Final[Path] = REPO_ROOT / "gis" / "src" / "gis" / "tests" / "fixtures"
"""IU-14's committed rasters and tiles. Reused here rather than duplicated — they describe
the same ground as `field_photo.jpg` (15.0000000 E, 45.1534772 N)."""

#: ★ The one place these coordinates are written down for the cross-package suite.
#: `field_photo.jpg`'s EXIF GPS, `synthetic_ortho.tif`'s top-left corner and the committed
#: fixture tiles all name this point. 500000 E in UTM 33N is exactly the central meridian,
#: so the longitude is exactly 15.0 rather than approximately 15.
SCENE_LON: Final[float] = 15.0
SCENE_LAT: Final[float] = 45.1534772

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
# The db marker — auto-skip (§13.1 IU-31)
# =============================================================================


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip every `@pytest.mark.db` test unless `LE_DATABASE_URL` is set.

    ★ §13.1 IU-31: *"Skipped automatically when `LE_DATABASE_URL` is unset, so `pytest` on
    the dev machine is green."* Done here rather than with a `skipif` on each test, so a new
    DB test cannot forget it — the marker IS the opt-in.
    """
    if os.environ.get("LE_DATABASE_URL"):
        return
    skip_db = pytest.mark.skip(
        reason="needs PostgreSQL + PostGIS; set LE_DATABASE_URL to run (§13.4 rule 1)"
    )
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)


# =============================================================================
# The no-network guarantee
# =============================================================================


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ Make any IP socket connection an immediate, loud failure. Autouse, suite-wide.

    §13's first line: *"No test may require network."* `tests/e2e/` exists to prove the
    product works end to end **offline** — with the `fixture` provider, no weights and no
    GPU — so a stray fetch here would silently invalidate the exact claim the tier is making.

    AF_UNIX is still permitted: local IPC is not the network, and a live-DB run
    (`LE_DATABASE_URL`, `integration/`) legitimately needs a real socket — see
    `_allow_db_socket`.
    """
    if os.environ.get("LE_DATABASE_URL"):
        # A DB tier was explicitly opted into; it needs a real connection.
        return

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _is_ip(sock: socket.socket) -> bool:
        return sock.family in (socket.AF_INET, socket.AF_INET6)

    def _blocked(what: str) -> AssertionError:
        return AssertionError(
            f"a cross-package test touched the network via {what}(). tests/ is offline by "
            "contract (CONTRACT.md §13): use the committed fixtures under tests/fixtures/ "
            "and gis/src/gis/tests/fixtures/, or the `fixture` imagery provider."
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


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every LandExplorer imagery/credential variable from the environment.

    L2 promises a working satellite search with an empty `.env`; L10 promises `Settings()`
    never raises with no environment at all. Neither claim is tested by a suite that
    inherits the developer's shell.
    """
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# =============================================================================
# The committed photographs (§13.2 tests/fixtures/)
# =============================================================================


def _committed(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.fail(
            f"the committed fixture {name!r} is missing from {FIXTURES_DIR}. It is required "
            f"by CONTRACT.md §13.2 and is committed to git. Regenerate it with:\n"
            f"    python3 tests/fixtures/_generate.py",
            pytrace=False,
        )
    return path


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """The committed cross-package fixture directory."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def scene_lonlat() -> tuple[float, float]:
    """★ `(lon, lat)` of the one place every committed fixture describes.

    A fixture rather than an import: `tests/` is not a package (§2.8 lists no `__init__.py`),
    so `from tests.conftest import SCENE_LON` depends on the repo root happening to be on
    `sys.path` — true under some pytest invocations and not others. The fixture always works.
    """
    return (SCENE_LON, SCENE_LAT)


@pytest.fixture(scope="session")
def field_photo() -> Path:
    """★ A ground-level field photo WITH EXIF GPS (§13.2).

    640x480 JPEG, ~20 KB. Its EXIF places it at 15.0000000 E, 45.1534772 N — the top-left
    corner of `synthetic_ortho.tif`. Exercises ingest -> prior -> search end to end.

    ★ A ground-level **oblique**, on purpose: SCOPE.md §2 names that geometry as the reason
    automatic matching is deferred, so the fixture that stands for "a real upload" must have
    it. A nadir fixture would quietly flatter every algorithm that touches it.
    """
    return _committed("field_photo.jpg")


@pytest.fixture(scope="session")
def field_photo_no_gps() -> Path:
    """★ The same photo with no EXIF GPS (§13.2).

    The normal case, not the edge case: most field photographs have no GPS. Exercises
    `422 SEARCH_HINT_REQUIRED` and the map-click hint path.
    """
    return _committed("field_photo_no_gps.jpg")


@pytest.fixture(scope="session")
def field_photo_rotated() -> Path:
    """★ The same photo carrying EXIF `Orientation = 6` (§13.2).

    Stored 640x480; **displays** 480x640. Proves ingest normalises the rotation and that
    `width`/`height` are stored **post-rotation**. Orientation is a geometric fact, not a
    display preference: get it wrong and every pixel coordinate the surveyor places is
    transposed against the coordinate the export claims.
    """
    return _committed("field_photo_rotated.jpg")


# =============================================================================
# The offline imagery provider
# =============================================================================


@pytest.fixture(scope="session")
def gis_fixtures_dir() -> Path:
    """IU-14's committed GeoTIFF + tile directory."""
    if not GIS_FIXTURES_DIR.is_dir():
        pytest.fail(f"missing {GIS_FIXTURES_DIR}", pytrace=False)
    return GIS_FIXTURES_DIR


@pytest.fixture(scope="session")
def synthetic_ortho(gis_fixtures_dir: Path) -> Path:
    """The committed 64x64 EPSG:32633 ortho, reused across packages."""
    return gis_fixtures_dir / "synthetic_ortho.tif"


@pytest.fixture
def fixture_provider(gis_fixtures_dir: Path, clean_env: None) -> Any:
    """★ The `fixture` imagery provider, backed by the committed tiles. NO NETWORK.

    L2's keyless default is Esri, which needs the network. This is the provider that makes
    the offline claim real — and it is deliberately not "test-only": it is the front door of
    `LE_IMAGERY_OFFLINE=true` and of `make seed && make up` (§11.5).
    """
    from gis.imagery.providers.fixture import FixtureProvider

    return FixtureProvider(tile_dir=gis_fixtures_dir / "tiles")
