"""Project-folder export — gather a project into one browsable folder (2026-09-03).

★ What these pin: the export root sits in the visible LandExplorer folder, the
folder name is sanitised, and the LUT gather picks EXACTLY the bundles whose
manifest was solved against this project's DEM (never another project's).

The DB-driven assembly (`export_project`) is verified live against the real
database; these cover the file-gathering logic that has no DB.
"""

from __future__ import annotations

import json

from app.core.config import Settings
from app.services import project_export_service as pe


def test_export_root_is_the_visible_landexplorer_folder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # No configured capture dir → the default visible LandExplorer path.
    root = pe.exports_root(Settings(capture_export_dir=None))
    assert root == tmp_path / "Pictures" / "LandExplorer" / "projects"
    assert root.is_dir()
    # A configured capture dir is honoured.
    root2 = pe.exports_root(Settings(capture_export_dir=tmp_path / "cap"))
    assert root2 == tmp_path / "cap" / "projects"


def test_slug_is_filesystem_safe() -> None:
    assert pe._slug("first test") == "first-test"
    assert pe._slug("A/B\\C:*?") == "A-B-C"
    assert pe._slug("") == "project"
    assert pe._slug("...") == "project"


def test_lut_gather_matches_only_this_projects_dem(tmp_path) -> None:
    lut_root = tmp_path / "lut"
    project_id = "5e69abd3-d043-4a3b-80f5-760b4c45c457"

    def bundle(name: str, dem_file: str) -> None:
        d = lut_root / f"{name}_lut"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"dem": {"file": dem_file}}))
        (d / "lat.npy").write_bytes(b"x")  # something to copy

    bundle("MINE", f"{project_id}.tif")  # built from this project's DEM
    bundle("OTHER", "11111111-2222-3333-4444-555555555555.tif")  # a different project
    bundle("NODEM", "")  # an imported bundle with no pose/dem

    dst = tmp_path / "out"
    copied = pe._copy_project_luts(lut_root, project_id, dst)
    assert copied == 1
    assert (dst / "MINE_lut" / "manifest.json").is_file()
    assert not (dst / "OTHER_lut").exists()
    assert not (dst / "NODEM_lut").exists()


def test_lut_gather_is_zero_when_no_lut_dir(tmp_path) -> None:
    assert pe._copy_project_luts(tmp_path / "missing", "any-id", tmp_path / "out") == 0
