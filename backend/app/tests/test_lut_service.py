"""``lut_service`` — the gate in front of the vendored LUT core.

★ These tests pin the REFUSALS, not the maths (the vendored core carries its own
15-test suite, run against the vendored copy in CI): a build that cannot succeed
must be refused before its thread starts, with the fix named in the message.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.services.lut_service import (
    GcpPoint,
    LutBuildError,
    LutBuildInputs,
    sanitize_site_name,
    validate_inputs,
)


def _inputs(tmp_path: Path, **over) -> LutBuildInputs:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"not-a-real-tif")  # existence is what validate_inputs checks
    gcps = tuple(
        GcpPoint(u=100.0 * i, v=80.0 * i, lat=34.11 + i * 1e-4, lon=36.02 + i * 1e-4, elevation_m=1380.0 + i)
        for i in range(1, 5)
    )
    base = dict(
        image_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        site_name="yammone_124_200m",
        image_width=4032,
        image_height=2268,
        fx=2799.7, fy=2800.5, cx=2025.5, cy=1125.9,
        k1=0.0, k2=0.0, p1=0.0, p2=0.0, k3=0.0,
        cam_lat=34.113, cam_lon=36.02, cam_height_m=2.0,
        gcps=gcps,
        dem_path=dem,
        output_dir=tmp_path / "out",
    )
    base.update(over)
    return LutBuildInputs(**base)


class TestSanitizeSiteName:
    def test_spaces_and_punctuation_become_underscores(self) -> None:
        assert sanitize_site_name("yammone 124 (200m)!") == "yammone_124_200m"

    def test_never_empty(self) -> None:
        assert sanitize_site_name("///") == "site"

    def test_length_capped(self) -> None:
        assert len(sanitize_site_name("x" * 200)) <= 64


class TestValidateInputs:
    def test_a_complete_request_passes(self, tmp_path: Path) -> None:
        validate_inputs(_inputs(tmp_path))  # must not raise

    def test_missing_intrinsics_name_the_fields(self, tmp_path: Path) -> None:
        with pytest.raises(LutBuildError, match="fx.*settings page"):
            validate_inputs(_inputs(tmp_path, fx=None))

    def test_missing_position_names_the_fix(self, tmp_path: Path) -> None:
        with pytest.raises(LutBuildError, match="no position"):
            validate_inputs(_inputs(tmp_path, cam_lat=None, cam_lon=None))

    def test_fewer_than_four_gcps_is_refused_with_the_count(self, tmp_path: Path) -> None:
        few = _inputs(tmp_path)
        with pytest.raises(LutBuildError, match="only 2"):
            validate_inputs(_inputs(tmp_path, gcps=few.gcps[:2]))

    def test_missing_dem_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(LutBuildError, match="no DEM under this photograph"):
            validate_inputs(_inputs(tmp_path, dem_path=tmp_path / "absent.tif"))


# ─────────────────────────────────────────────────────────────────────────────
# Importing a bundle the app did not build
# ─────────────────────────────────────────────────────────────────────────────
#
# ★ THE REFUSALS ARE THE FEATURE. A LUT is believed absolutely downstream — every
# mark on the map is one array read — so a table of the wrong shape, dtype or UNITS
# would not fail loudly, it would place detections somewhere plausible and wrong.
# These tests pin exactly that, plus the two structural promises: an archive can
# never write outside the bundle folder, and a refused import leaves nothing behind.


def _write_arrays(folder: Path, *, h: int = 8, w: int = 10, scale: float = 1.0) -> None:
    import numpy as np

    folder.mkdir(parents=True, exist_ok=True)
    lat = np.full((h, w), 34.1 * scale)
    lon = np.full((h, w), 36.0 * scale)
    lat[0, 0] = np.nan  # sky — a real LUT has NaN holes
    lon[0, 0] = np.nan
    np.save(folder / "lat.npy", lat)
    np.save(folder / "lon.npy", lon)


def _zip(source: Path, archive: Path, prefix: str = "") -> Path:
    import zipfile

    with zipfile.ZipFile(archive, "w") as zf:
        for f in sorted(source.iterdir()):
            zf.write(f, f"{prefix}{f.name}")
    return archive


POSE_MANIFEST = {
    "site_name": "arsal",
    "built_utc": "2026-01-02T03:04:05Z",
    "image": {"width": 10, "height": 8},
    "pose": {
        "R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "C": [1, 2, 3],
        "K": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "image_width": 10,
        "image_height": 8,
    },
    "dem": {"epsg": 32636},
    "validation": {"passed": True, "max_error_m": 0.12},
}


class TestExportArchive:
    def test_the_export_zip_carries_the_whole_bundle(self, tmp_path: Path) -> None:
        """★ The export includes the manifest (owner ask 2026-09-03).

        A zip without it loses the camera pose on re-import — the "no pose in
        its manifest" bundle that cannot serve the drift monitor.
        """
        import json as json_mod
        import zipfile

        from app.services.lut_service import _write_export_archive

        bundle = tmp_path / "arsal_lut"
        _write_arrays(bundle)
        (bundle / "manifest.json").write_text(json_mod.dumps(POSE_MANIFEST), encoding="utf-8")
        (bundle / "pi_lookup.py").write_text("# reader", encoding="utf-8")

        archive = _write_export_archive(bundle)
        names = sorted(zipfile.ZipFile(archive).namelist())
        # README/adopted_correction are optional and absent here — not invented.
        assert names == ["lat.npy", "lon.npy", "manifest.json", "pi_lookup.py"]

    def test_an_exported_bundle_reimports_with_its_pose(self, tmp_path: Path) -> None:
        """★ The round trip that used to lose the pose.

        Export → import → the bundle still serves the drift monitor
        (`has_pose` True, nothing synthesised).
        """
        import json as json_mod

        from app.services.lut_service import _write_export_archive, import_bundle

        bundle = tmp_path / "arsal_lut"
        _write_arrays(bundle)
        (bundle / "manifest.json").write_text(json_mod.dumps(POSE_MANIFEST), encoding="utf-8")
        archive = _write_export_archive(bundle)

        entry = import_bundle(
            output_dir=tmp_path / "lib", source=archive, origin_name="arsal_lut.zip",
            site_name=None,
        )
        assert entry["has_pose"] is True
        assert entry["validation_passed"] is True
        assert entry["imported"]["manifest"] != "synthesised"


class TestImportBundle:
    def test_the_apps_own_payload_only_export_round_trips(self, tmp_path: Path) -> None:
        """The app's own payload-only export imports back in.

        ★ What it hands out is `lat.npy` + `lon.npy` at the zip ROOT, so that is the
        file a surveyor actually has in their hand.
        """
        from app.services.lut_service import import_bundle

        payload = tmp_path / "payload"
        _write_arrays(payload)
        archive = _zip(payload, tmp_path / "yammone_lut.zip")

        entry = import_bundle(
            output_dir=tmp_path / "lib", source=archive, origin_name="yammone_lut.zip",
            site_name=None,
        )

        assert entry["site_name"] == "yammone"  # `_lut` stripped from the file name
        assert entry["image"] == {"width": 10, "height": 8}
        bundle = tmp_path / "lib" / "yammone_lut"
        # The folder is complete: every consumer reads manifest.json, and the field
        # unit's own reader travels with an imported bundle as with a built one.
        assert (bundle / "manifest.json").is_file()
        assert (bundle / "pi_lookup.py").is_file()
        assert (tmp_path / "lib" / "yammone_lut.zip").is_file()

    def test_a_payload_only_import_is_honest_about_having_no_pose(self, tmp_path: Path) -> None:
        """A payload-only import is honest about having no pose.

        ★ It can place detections; it cannot serve the drift monitor. `has_pose` lets
        that page say so while the surveyor is still choosing.
        """
        from app.services.lut_service import import_bundle

        payload = tmp_path / "payload"
        _write_arrays(payload)
        entry = import_bundle(
            output_dir=tmp_path / "lib", source=_zip(payload, tmp_path / "b.zip"),
            origin_name="b.zip", site_name="thin",
        )

        assert entry["has_pose"] is False
        assert entry["validation_passed"] is None  # absent validation is NOT "passed"
        assert entry["imported"]["manifest"] == "synthesised"

    def test_a_full_bundle_keeps_its_own_provenance(self, tmp_path: Path) -> None:
        """A full bundle keeps its own provenance.

        ★ Pose, DEM checksum and validation report are what make a bundle deployable —
        the import must carry them through, and never invent them.
        """
        import json

        from app.services.lut_service import import_bundle

        full = tmp_path / "raw" / "arsal_lut"
        _write_arrays(full)
        (full / "manifest.json").write_text(json.dumps(POSE_MANIFEST), encoding="utf-8")
        archive = _zip(full, tmp_path / "arsal.zip", prefix="arsal_lut/")

        entry = import_bundle(
            output_dir=tmp_path / "lib", source=archive, origin_name="arsal.zip", site_name=None,
        )

        assert entry["site_name"] == "arsal"  # from the manifest, not the file name
        assert entry["has_pose"] is True
        assert entry["validation_passed"] is True
        assert entry["max_error_m"] == 0.12

    def test_the_arrays_outrank_a_manifest_that_disagrees_about_size(self, tmp_path: Path) -> None:
        """The arrays outrank a manifest that disagrees about the image size.

        ★ `GeoLut.scale_from` scales every detection by that size, so a manifest at
        odds with the arrays would silently mis-place marks on a resized stream. The
        MEASURED size wins, and the note says it did.
        """
        import json

        from app.services.lut_service import import_bundle

        full = tmp_path / "raw" / "arsal_lut"
        _write_arrays(full)
        (full / "manifest.json").write_text(
            json.dumps({**POSE_MANIFEST, "image": {"width": 4032, "height": 2268}}),
            encoding="utf-8",
        )

        entry = import_bundle(
            output_dir=tmp_path / "lib", source=full, origin_name="arsal_lut", site_name=None,
        )

        assert entry["image"] == {"width": 10, "height": 8}
        assert "measured" in entry["imported"]["note"]

    def test_projected_metres_are_refused_as_not_degrees(self, tmp_path: Path) -> None:
        """Projected metres are refused as not being degrees.

        ★ The check that matters: a UTM table would place every mark plausibly and
        wrongly. Nothing about it is malformed — only the units are.
        """
        from app.services.lut_service import LutImportError, import_bundle

        folder = tmp_path / "utm_lut"
        _write_arrays(folder, scale=1000.0)

        with pytest.raises(LutImportError, match=r"not decimal degrees|decimal degrees"):
            import_bundle(
                output_dir=tmp_path / "lib", source=folder, origin_name="utm_lut",
                site_name="utm",
            )
        # ★ And it left NOTHING behind — staged, validated, only then swapped in.
        lib = tmp_path / "lib"
        assert not (lib / "utm_lut").exists()
        assert [p.name for p in lib.iterdir()] == []

    def test_mismatched_arrays_are_refused(self, tmp_path: Path) -> None:
        import numpy as np

        from app.services.lut_service import LutImportError, import_bundle

        folder = tmp_path / "odd_lut"
        _write_arrays(folder)
        np.save(folder / "lon.npy", np.full((4, 4), 36.0))

        with pytest.raises(LutImportError, match="same view"):
            import_bundle(
                output_dir=tmp_path / "lib", source=folder, origin_name="odd_lut", site_name="odd",
            )

    def test_an_all_nan_table_is_refused(self, tmp_path: Path) -> None:
        import numpy as np

        from app.services.lut_service import LutImportError, import_bundle

        folder = tmp_path / "sky_lut"
        folder.mkdir(parents=True)
        np.save(folder / "lat.npy", np.full((8, 10), np.nan))
        np.save(folder / "lon.npy", np.full((8, 10), np.nan))

        with pytest.raises(LutImportError, match=r"maps no pixel"):
            import_bundle(
                output_dir=tmp_path / "lib", source=folder, origin_name="sky_lut", site_name="sky",
            )

    def test_an_archive_can_never_write_outside_the_bundle(self, tmp_path: Path) -> None:
        """An archive can never write outside the bundle folder.

        ★ Zip-slip has nowhere to land: only whitelisted BASENAMES are taken, and each
        is written to a path this code built.
        """
        import zipfile

        from app.services.lut_service import import_bundle

        payload = tmp_path / "payload"
        _write_arrays(payload)
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.write(payload / "lat.npy", "lat.npy")
            zf.write(payload / "lon.npy", "lon.npy")
            zf.writestr("../../pwned.txt", "nope")
            zf.writestr("/etc/pwned.txt", "nope")

        import_bundle(
            output_dir=tmp_path / "lib", source=archive, origin_name="evil.zip", site_name="safe",
        )

        assert not (tmp_path / "pwned.txt").exists()
        assert sorted(p.name for p in (tmp_path / "lib" / "safe_lut").iterdir()) == [
            "lat.npy", "lon.npy", "manifest.json", "pi_lookup.py",
        ]

    def test_a_name_already_in_the_library_is_refused_unless_confirmed(self, tmp_path: Path) -> None:
        from app.services.lut_service import LutImportError, import_bundle

        folder = tmp_path / "site_lut"
        _write_arrays(folder)
        lib = tmp_path / "lib"
        import_bundle(output_dir=lib, source=folder, origin_name="site_lut", site_name="ridge")

        with pytest.raises(LutImportError, match="already holds a bundle"):
            import_bundle(output_dir=lib, source=folder, origin_name="site_lut", site_name="ridge")

        entry = import_bundle(
            output_dir=lib, source=folder, origin_name="site_lut", site_name="ridge",
            overwrite=True,
        )
        assert entry["site_name"] == "ridge"

    def test_a_zip_holding_two_bundles_is_refused(self, tmp_path: Path) -> None:
        import zipfile

        from app.services.lut_service import LutImportError, import_bundle

        payload = tmp_path / "payload"
        _write_arrays(payload)
        archive = tmp_path / "both.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for prefix in ("a_lut/", "b_lut/"):
                zf.write(payload / "lat.npy", f"{prefix}lat.npy")
                zf.write(payload / "lon.npy", f"{prefix}lon.npy")

        with pytest.raises(LutImportError, match="one at a time"):
            import_bundle(
                output_dir=tmp_path / "lib", source=archive, origin_name="both.zip",
                site_name=None,
            )

    def test_the_library_scan_reports_the_same_row_the_import_returned(
        self, tmp_path: Path
    ) -> None:
        """The library scan reports the same row the import returned.

        ★ One row shape, one code path: a scan that disagreed with the import response
        would make the library lie for exactly one refresh.
        """
        from app.services.lut_service import import_bundle, scan_library

        folder = tmp_path / "site_lut"
        _write_arrays(folder)
        lib = tmp_path / "lib"
        entry = import_bundle(
            output_dir=lib, source=folder, origin_name="site_lut", site_name="ridge"
        )

        scanned = next(e for e in scan_library(lib) if e["site_name"] == "ridge")
        assert scanned == entry

    def test_an_imported_bundle_is_readable_by_the_consumers_reader(self, tmp_path: Path) -> None:
        """An imported bundle is readable by the consumers' own reader.

        ★ The point of the whole feature: the detection pages open the folder with
        `GeoLut`, which needs a manifest and the two arrays. An import that produced a
        folder it could not read would list fine and fail at run time.
        """
        from app.services.lut_service import import_bundle
        from app.services.detection.lut import GeoLut

        folder = tmp_path / "site_lut"
        _write_arrays(folder)
        import_bundle(
            output_dir=tmp_path / "lib", source=folder, origin_name="site_lut", site_name="ridge"
        )

        lut = GeoLut(str(tmp_path / "lib" / "ridge_lut"))
        assert lut.site == "ridge"
        assert (lut.width, lut.height) == (10, 8)
        assert lut.lookup(5, 5, scale=False)[0] == pytest.approx(34.1)
