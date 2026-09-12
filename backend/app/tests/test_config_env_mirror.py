"""``_mirror_env_file_into_environ`` — the ``.env`` → ``os.environ`` bridge.

★ WHY THIS FILE EXISTS. The gis imagery providers read credentials from ``os.environ``
directly; pydantic-settings reads ``.env`` into the ``Settings`` object only. The mirror
is the bridge, and it must span BOTH deployments:

- dev / web: the API runs from ``backend/``, keys live in ``backend/.env``;
- packaged desktop: the API runs from the app-data ``work/`` dir and ``backend/`` is a
  read-only installer image, so ``work/.env`` (the cwd file) is the only writable spot —
  it is exactly what installation.md §8 tells the user to create.

The desktop half regressed once already: only the source-anchored file was mirrored, so
a key in ``work/.env`` reached ``Settings`` and stopped, and ``google_map_tiles`` stayed
hidden in the basemap menu. These tests pin both halves.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import _mirror_env_file_into_environ


@pytest.fixture(autouse=True)
def _pristine_environ() -> Iterator[None]:
    """Snapshot and restore ``os.environ`` around every test.

    ★ The function under test WRITES the real process environment (that is its job), and
    ``monkeypatch`` cannot undo writes it did not make itself. A full snapshot can.
    """
    saved = os.environ.copy()
    for key in ("LE_GOOGLE_MAPS_STATIC_KEY", "LE_GOOGLE_TOS_ACKNOWLEDGED"):
        os.environ.pop(key, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _write(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_cwd_env_alone_is_mirrored(tmp_path: Path) -> None:
    """★ THE PACKAGED-DESKTOP CASE: no ``backend/.env`` exists, only ``work/.env``."""
    work = tmp_path / "work"
    work.mkdir()
    cwd_env = _write(
        work / ".env",
        "LE_GOOGLE_MAPS_STATIC_KEY=desktop-key",
        "LE_GOOGLE_TOS_ACKNOWLEDGED=true",
    )

    _mirror_env_file_into_environ(cwd_env=cwd_env, backend_env=tmp_path / "absent" / ".env")

    assert os.environ["LE_GOOGLE_MAPS_STATIC_KEY"] == "desktop-key"
    assert os.environ["LE_GOOGLE_TOS_ACKNOWLEDGED"] == "true"


def test_desktop_env_file_enables_the_google_provider(tmp_path: Path) -> None:
    """★ THE ACTUAL INTEGRATION: after the mirror runs, the provider's double opt-in
    passes and ``google_map_tiles`` reports configured — which is the exact signal the
    frontend's basemap menu keys on."""
    from gis.imagery.providers.google_map_tiles import GoogleMapTilesProvider

    cwd_env = _write(
        tmp_path / ".env",
        "LE_GOOGLE_MAPS_STATIC_KEY=desktop-key",
        "LE_GOOGLE_TOS_ACKNOWLEDGED=true",
    )
    assert GoogleMapTilesProvider().is_configured() is False

    _mirror_env_file_into_environ(cwd_env=cwd_env, backend_env=tmp_path / "absent" / ".env")

    assert GoogleMapTilesProvider().is_configured() is True


def test_backend_env_still_mirrored(tmp_path: Path) -> None:
    """The original dev/web path keeps working when only ``backend/.env`` exists."""
    backend_env = _write(tmp_path / ".env", "LE_GOOGLE_MAPS_STATIC_KEY=backend-key")

    _mirror_env_file_into_environ(
        cwd_env=tmp_path / "elsewhere" / ".env", backend_env=backend_env
    )

    assert os.environ["LE_GOOGLE_MAPS_STATIC_KEY"] == "backend-key"


def test_real_environment_wins_over_both_files(tmp_path: Path) -> None:
    """``setdefault`` semantics: container/systemd deployments that pass real env are
    never overridden by a stray file."""
    os.environ["LE_GOOGLE_MAPS_STATIC_KEY"] = "real-env-key"
    cwd_env = _write(tmp_path / "a.env", "LE_GOOGLE_MAPS_STATIC_KEY=cwd-key")
    backend_env = _write(tmp_path / "b.env", "LE_GOOGLE_MAPS_STATIC_KEY=backend-key")

    _mirror_env_file_into_environ(cwd_env=cwd_env, backend_env=backend_env)

    assert os.environ["LE_GOOGLE_MAPS_STATIC_KEY"] == "real-env-key"


def test_cwd_file_wins_on_conflict(tmp_path: Path) -> None:
    """★ On a key present in both files, the cwd file wins — because pydantic's
    ``env_file=".env"`` resolves against cwd, so this is the only order in which
    ``os.environ`` and ``Settings`` agree."""
    cwd_env = _write(tmp_path / "a.env", "LE_GOOGLE_MAPS_STATIC_KEY=cwd-key")
    backend_env = _write(tmp_path / "b.env", "LE_GOOGLE_MAPS_STATIC_KEY=backend-key")

    _mirror_env_file_into_environ(cwd_env=cwd_env, backend_env=backend_env)

    assert os.environ["LE_GOOGLE_MAPS_STATIC_KEY"] == "cwd-key"


def test_same_file_at_both_anchors_reads_once(tmp_path: Path) -> None:
    """Dev mode: cwd IS ``backend/``, so both anchors resolve to one file. No error,
    values land once."""
    env = _write(tmp_path / ".env", "LE_GOOGLE_MAPS_STATIC_KEY=dev-key")

    _mirror_env_file_into_environ(cwd_env=env, backend_env=env)

    assert os.environ["LE_GOOGLE_MAPS_STATIC_KEY"] == "dev-key"


def test_missing_files_are_a_supported_state(tmp_path: Path) -> None:
    """L10: no ``.env`` anywhere must not raise — every Settings field has a default."""
    _mirror_env_file_into_environ(
        cwd_env=tmp_path / "no" / ".env", backend_env=tmp_path / "nope" / ".env"
    )
    assert "LE_GOOGLE_MAPS_STATIC_KEY" not in os.environ


def test_only_le_lines_and_quotes_stripped(tmp_path: Path) -> None:
    """Comments, blanks and non-``LE_`` lines are ignored; surrounding quotes drop."""
    cwd_env = _write(
        tmp_path / ".env",
        "# comment",
        "",
        "PATH=/tmp/evil",
        "not a kv line",
        'LE_GOOGLE_MAPS_STATIC_KEY="quoted-key"',
    )
    path_before = os.environ.get("PATH")

    _mirror_env_file_into_environ(cwd_env=cwd_env, backend_env=tmp_path / "x" / ".env")

    assert os.environ["LE_GOOGLE_MAPS_STATIC_KEY"] == "quoted-key"
    assert os.environ.get("PATH") == path_before
