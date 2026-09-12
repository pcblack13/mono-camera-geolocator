"""IU-01 — ★ `ai_engine.types` is CHEAP, and this test is why anyone may rely on it.

`gis.candidates` is permitted exactly ONE cross-package import — `ai_engine.types` — and
the entire justification is that this package costs only numpy + stdlib: it "cannot drag
in cv2 or torch". That claim is load-bearing for three separate rules (the layering
contract, the `gis-purity` import-linter contract, and `cd gis && pytest` collecting at
all) and, before this file, it was asserted nowhere.

It must run in a FRESH INTERPRETER. Inside the pytest process cv2 or torch may already be
in `sys.modules` — imported by a sibling test, a plugin, or a conftest — so an in-process
`assert "cv2" not in sys.modules` would either fail for reasons unrelated to this property
or pass by luck depending on test ORDER. A subprocess is the only honest way to ask.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

# Modules that importing `ai_engine.types` must NOT pull in, and what each would break.
FORBIDDEN = {
    "cv2": "the algorithm layer — gis would inherit every extractor's import cost",
    "torch": "a ~2 s import and CUDA init, for a package of dataclasses (L8)",
    "ai_engine.models": "the registry — the cycle that forced provenance.py into types/",
    "scipy": "the numerics layer; types is numpy + stdlib only",
}


def _run_probe(body: str) -> subprocess.CompletedProcess[str]:
    """Execute `body` in a fresh interpreter with this repo's `ai_engine` importable."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_importing_types_leaves_the_heavy_modules_absent() -> None:
    """★ THE PROPERTY §10.3 RELIES ON, asserted on a fresh interpreter."""
    proc = _run_probe(
        """
        import sys

        assert "cv2" not in sys.modules, "cv2 was already imported before the probe ran"
        assert "torch" not in sys.modules, "torch was already imported before the probe ran"

        import ai_engine.types  # noqa: F401  — the module under test

        leaked = [
            name
            for name in ("cv2", "torch", "scipy", "ai_engine.models")
            if name in sys.modules
        ]
        assert not leaked, f"ai_engine.types leaked heavy imports: {leaked}"
        print("OK")
        """
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    assert "OK" in proc.stdout


def test_the_whole_public_type_surface_stays_cheap() -> None:
    """Touching every re-exported name must not trigger a lazy heavy import.

    A dataclass whose default is built on first access could smuggle one in.
    """
    proc = _run_probe(
        """
        import sys

        import ai_engine.types as t

        for name in t.__all__:
            getattr(t, name)

        leaked = [n for n in ("cv2", "torch", "scipy", "ai_engine.models") if n in sys.modules]
        assert not leaked, f"touching the type surface leaked: {leaked}"
        assert len(t.__all__) > 40, "the re-export surface looks truncated"
        print("OK")
        """
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    assert "OK" in proc.stdout


def test_importing_the_package_root_stays_cheap() -> None:
    """★ THE PEP 562 PROPERTY. `from ai_engine.types import CandidateWindow` executes
    `ai_engine/__init__.py` first — package `__init__` always runs before a submodule
    import. So if the root imported the pipeline at module scope, gis's sanctioned import
    would drag in cv2, scipy and every extractor, and the permission for that import would
    evaporate. The root must be `__getattr__`-lazy."""
    proc = _run_probe(
        """
        import sys

        import ai_engine
        from ai_engine.types import CandidateWindow  # noqa: F401  — gis's sanctioned import

        leaked = [
            name
            for name in ("cv2", "torch", "scipy", "ai_engine.models", "ai_engine.pipeline")
            if name in sys.modules
        ]
        assert not leaked, f"importing the package root leaked: {leaked}"

        # The lazy surface must still be reachable and correct...
        assert ai_engine.version() == ai_engine.__version__
        assert "run_match_job" in dir(ai_engine)

        # ...and asking for a name that does not exist must raise AttributeError, not
        # ImportError or KeyError — __getattr__ has to behave like an attribute lookup.
        try:
            ai_engine.definitely_not_a_real_name
        except AttributeError:
            pass
        else:
            raise AssertionError("expected AttributeError for an unknown attribute")
        print("OK")
        """
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    assert "OK" in proc.stdout


def test_errors_and_version_are_importable_without_numpy_types() -> None:
    """`ai_engine.errors` is stdlib-only: `types/features.py` imports it, so anything it
    imported at module scope would be a cycle. The backend also imports
    `NotImplementedDeferred` to map deferred endpoints onto 501, and must not pay for the
    engine to do it."""
    proc = _run_probe(
        """
        import sys

        from ai_engine.errors import NotImplementedDeferred
        from ai_engine.version import version

        leaked = [n for n in ("cv2", "torch", "scipy", "ai_engine.models") if n in sys.modules]
        assert not leaked, f"ai_engine.errors leaked: {leaked}"

        exc = NotImplementedDeferred("ai_engine.extractors.sift", feature="SIFT extraction")
        assert exc.module == "ai_engine.extractors.sift"
        assert "SCOPE.md" in str(exc), "a deferred error must point at the scope ruling"
        assert isinstance(version(), str)
        print("OK")
        """
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    assert "OK" in proc.stdout
