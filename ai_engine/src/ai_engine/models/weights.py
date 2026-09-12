"""Weight-file resolution — **never downloads, never raises**.

Two absolute rules, and both are about failure modes rather than tidiness:

1. **NEVER DOWNLOAD.** A silent multi-hundred-megabyte fetch inside a Celery worker, on a
   machine that may be air-gapped, triggered by a surveyor clicking "Match", is an
   unacceptable surprise and an unacceptable failure mode. `scripts/download_models.py`
   is the only downloader; it is opt-in, it prints each model's licence, and it is never
   invoked at build or at boot.
2. **NEVER RAISE.** Every function here answers a question. A missing weight file is the
   *default, supported state* of this repository (§9.8: `LE_AI_MODEL_WEIGHTS_DIR` is
   empty by default and that is fine), so it is data, not an exception.

★ **A corrupt weight is treated exactly like a missing one.** A half-downloaded `.pth`
that imports and then emits garbage is far worse than one that is simply absent: the
absent one degrades loudly to the classical path, the corrupt one produces confident
nonsense. `WeightStatus.ok` collapses the two, deliberately.

★ **THE SHIPPED MANIFEST CARRIES NO CHECKSUMS, AND THAT IS AN HONESTY DECISION.**
Every backend that needs a weight is deferred in this build (`docs/architecture/SCOPE.md`)
— no weight has ever been downloaded here, and there is no network with which to learn a
digest. Inventing a plausible-looking sha256 would be strictly worse than admitting we do
not know one: it would reject a *legitimately* downloaded checkpoint as "corrupt" the
first time someone ran `download_models.py`, and the failure would look exactly like the
tampering the checksum exists to detect. So `sha256` is `None`, `verify()` says
`"checksum unknown"` in its reason, and `download_models.py` owns populating it from the
publisher at the moment it fetches the file.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_engine.logging import get_logger

__all__ = [
    "DEFAULT_MANIFEST",
    "WEIGHTS_DIR_ENV_VAR",
    "WeightManifest",
    "WeightSpec",
    "WeightStatus",
    "default_weights_dir",
    "resolve_weight_path",
    "sha256_of",
    "weight_status",
]

_log = get_logger(__name__)

#: The environment variable consulted when no `weights_dir` is configured (§9.8).
WEIGHTS_DIR_ENV_VAR = "LE_AI_MODEL_WEIGHTS_DIR"

#: Read in 1 MiB blocks: a SAM ViT-H checkpoint is ~2.4 GB and must not be slurped whole.
_HASH_BLOCK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class WeightSpec:
    """One logical weight: what file to look for and how to know it is intact.

    Attributes:
        key: The logical name a `ComponentSpec.requires_weights` entry carries. Stable
            across filename and version changes — that indirection is the point.
        filename: The file's basename, searched for under each candidate directory.
        sha256: The expected lowercase hex digest, or None when this build does not know
            it. None means "cannot verify", never "verified".
        size_bytes: The expected size, or None if unknown. A cheap pre-check that catches
            a truncated download without hashing gigabytes.
        license: The licence the weight ships under. Recorded because it is an obligation
            that travels with the file, and `download_models.py` prints it before fetching.
        source: The upstream project the weight comes from. Human-readable provenance.
        url: The download URL, or None when this build does not have a verified one.
            Nothing here ever fetches it; `download_models.py` is the only consumer.
    """

    key: str
    filename: str
    sha256: str | None = None
    size_bytes: int | None = None
    license: str = "unknown"
    source: str = "unknown"
    url: str | None = None


@dataclass(frozen=True, slots=True)
class WeightStatus:
    """The answer to "can this weight be used?", with the reason attached.

    Attributes:
        key: The logical weight key asked about.
        path: Where the file was found, or None if it was not found at all.
        ok: True only if the file exists AND passed every verification this build can
            perform. This is the single boolean `resolve_with_fallback` branches on.
        reason: Why not, when `ok` is False. None when `ok` is True. Human-readable and
            destined for a `WarningItem`, a log line and `GET /capabilities`.
        verified: True only if a checksum was actually compared and matched. ★ Distinct
            from `ok`: a file present with no known checksum is usable (`ok=True`) but
            unverified (`verified=False`), and conflating the two would let this module
            claim an integrity guarantee it did not check.
    """

    key: str
    path: Path | None
    ok: bool
    reason: str | None = None
    verified: bool = False


class WeightManifest:
    """The logical-key → :class:`WeightSpec` table, and the search for the files.

    Search order (§4.14), first hit wins:

    1. the explicitly configured ``weights_dir`` (``AiEngineConfig.weights_dir``);
    2. ``$LE_AI_MODEL_WEIGHTS_DIR``;
    3. ``~/.cache/landexplorer/weights``.

    Nothing is created, nothing is fetched, nothing raises.
    """

    def __init__(self, specs: Mapping[str, WeightSpec] | None = None) -> None:
        """Build a manifest.

        Args:
            specs: key → spec. Defaults to :data:`DEFAULT_MANIFEST`'s entries. Tests
                inject their own table — which is how `test_registry_fallback.py` can
                exercise the truncated-checkpoint path with a checksum it controls,
                despite the shipped manifest carrying none.
        """
        self._specs: dict[str, WeightSpec] = dict(specs) if specs is not None else {}

    def __contains__(self, key: object) -> bool:
        return key in self._specs

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._specs.values())

    def keys(self) -> tuple[str, ...]:
        """Every logical weight key this manifest knows, sorted for stable reporting."""
        return tuple(sorted(self._specs))

    def get(self, key: str) -> WeightSpec | None:
        """Return the spec for `key`, or None if the manifest has no such entry."""
        return self._specs.get(key)

    def add(self, spec: WeightSpec) -> None:
        """Register `spec` under its own key, replacing any previous entry."""
        self._specs[spec.key] = spec

    def search_dirs(self, weights_dir: Path | str | None = None) -> tuple[Path, ...]:
        """Return the directories that will be searched, in order, deduplicated.

        Non-existent directories are **kept** in the returned tuple: they are part of the
        honest answer to "where did you look?", which is what makes a "weights missing"
        message actionable rather than mystifying.
        """
        candidates: list[Path] = []
        if weights_dir is not None:
            candidates.append(Path(weights_dir))

        env_dir = os.environ.get(WEIGHTS_DIR_ENV_VAR, "").strip()
        if env_dir:
            candidates.append(Path(env_dir))

        candidates.append(default_weights_dir())

        seen: set[str] = set()
        ordered: list[Path] = []
        for path in candidates:
            try:
                resolved = path.expanduser()
            except (OSError, RuntimeError):
                # An un-expandable path (no home directory, for instance) is a directory
                # we simply cannot search. Skipping it beats raising out of a lookup.
                continue
            marker = str(resolved)
            if marker not in seen:
                seen.add(marker)
                ordered.append(resolved)
        return tuple(ordered)

    def locate(self, key: str, weights_dir: Path | str | None = None) -> Path | None:
        """Find the file for `key` without verifying it. None if absent or unknown."""
        spec = self.get(key)
        if spec is None:
            return None
        for directory in self.search_dirs(weights_dir):
            candidate = directory / spec.filename
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                # An unreadable directory is a place the file is not. Keep looking.
                continue
        return None

    def verify(self, key: str, weights_dir: Path | str | None = None) -> WeightStatus:
        """Locate and check the weight for `key`. **Never raises.**

        Checks, in increasing cost — the cheap ones exist so a truncated 2.4 GB
        checkpoint is caught without hashing 2.4 GB:

        1. the manifest knows `key` at all;
        2. the file exists in one of the search directories;
        3. `size_bytes` matches, when the manifest declares one;
        4. `sha256` matches, when the manifest declares one.

        A file that exists but whose digest is unknown to this build is reported
        ``ok=True, verified=False`` with a WARNING — usable, but do not claim it was
        checked.

        Returns:
            A :class:`WeightStatus`. `ok=False` is an ordinary, expected outcome and is
            the default state of this repository.
        """
        spec = self.get(key)
        if spec is None:
            return WeightStatus(
                key=key,
                path=None,
                ok=False,
                reason=(
                    f"unknown weight key {key!r}: it is not in the manifest, so nothing "
                    f"can be looked for. Known keys: {list(self.keys())}"
                ),
            )

        path = self.locate(key, weights_dir)
        if path is None:
            searched = ", ".join(str(d) for d in self.search_dirs(weights_dir))
            return WeightStatus(
                key=key,
                path=None,
                ok=False,
                reason=(
                    f"weights missing: {spec.filename} (key {key!r}) was not found in any "
                    f"of [{searched}]. Weights are never downloaded automatically; run "
                    f"scripts/download_models.py to fetch it."
                ),
            )

        if spec.size_bytes is not None:
            try:
                actual_size = path.stat().st_size
            except OSError as exc:
                return WeightStatus(
                    key=key,
                    path=path,
                    ok=False,
                    reason=f"weights unreadable: {path} could not be stat'ed ({exc})",
                )
            if actual_size != spec.size_bytes:
                return WeightStatus(
                    key=key,
                    path=path,
                    ok=False,
                    reason=(
                        f"weights corrupt: {path} is {actual_size} bytes, expected "
                        f"{spec.size_bytes}. A truncated checkpoint is treated exactly "
                        f"like a missing one — it would load and then produce garbage."
                    ),
                )

        if spec.sha256 is None:
            _log.warning(
                "Weight %r was found at %s but the manifest carries no checksum for it, "
                "so its integrity has NOT been verified. This build ships without "
                "checksums because it has never downloaded a weight; see %s.",
                key,
                path,
                "ai_engine/models/weights.py",
            )
            return WeightStatus(
                key=key,
                path=path,
                ok=True,
                reason=None,
                verified=False,
            )

        digest = sha256_of(path)
        if digest is None:
            return WeightStatus(
                key=key,
                path=path,
                ok=False,
                reason=f"weights unreadable: {path} could not be read to compute a digest",
            )
        if digest.lower() != spec.sha256.lower():
            return WeightStatus(
                key=key,
                path=path,
                ok=False,
                reason=(
                    f"weights corrupt: {path} has sha256 {digest} but the manifest "
                    f"expects {spec.sha256}. Treated exactly like a missing weight — a "
                    f"checkpoint that loads and then emits garbage is the worse failure."
                ),
            )

        return WeightStatus(key=key, path=path, ok=True, reason=None, verified=True)


def default_weights_dir() -> Path:
    """The last-resort search directory: ``~/.cache/landexplorer/weights``.

    Returned whether or not it exists, and **never created** — this module does not have
    side effects on the filesystem.
    """
    try:
        home = Path.home()
    except (OSError, RuntimeError):
        # No resolvable home (some container users). Fall back to a relative path rather
        # than raising out of what is supposed to be a lookup.
        return Path(".cache/landexplorer/weights")
    return home / ".cache" / "landexplorer" / "weights"


def sha256_of(path: Path, *, block_bytes: int = _HASH_BLOCK_BYTES) -> str | None:
    """Return `path`'s lowercase hex sha256, or None if it cannot be read.

    Streams the file: the largest checkpoint in the manifest is ~2.4 GB and must never be
    loaded into memory to be hashed.
    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(block_bytes):
                digest.update(chunk)
    except OSError as exc:
        _log.warning("Could not read %s to compute its sha256 (%s)", path, exc)
        return None
    return digest.hexdigest()


#: ★ The shipped manifest. Every entry here belongs to a DEFERRED backend
#: (`docs/architecture/SCOPE.md`) — the entries exist so that `GET /capabilities` can
#: truthfully enumerate what the engine KNOWS ABOUT versus what it can RUN, and so the
#: fallback policy has something real to probe. `sha256` and `url` are None throughout;
#: the module docstring explains why inventing them would be worse than admitting them.
DEFAULT_MANIFEST = WeightManifest(
    {
        spec.key: spec
        for spec in (
            WeightSpec(
                key="superpoint_v1",
                filename="superpoint_v1.pth",
                license="Non-commercial research use (MagicLeap)",
                source="magicleap/SuperPointPretrainedNetwork",
            ),
            WeightSpec(
                key="dinov2_v1",
                filename="dinov2_vits14.pth",
                license="Apache-2.0",
                source="facebookresearch/dinov2",
            ),
            WeightSpec(
                key="superglue_outdoor_v1",
                filename="superglue_outdoor.pth",
                license="Non-commercial research use (MagicLeap)",
                source="magicleap/SuperGluePretrainedNetwork",
            ),
            WeightSpec(
                key="lightglue_v1",
                filename="lightglue_superpoint.pth",
                license="Apache-2.0",
                source="cvg/LightGlue",
            ),
            WeightSpec(
                key="loftr_outdoor_v1",
                filename="loftr_outdoor.ckpt",
                license="Apache-2.0",
                source="zju3dv/LoFTR",
            ),
            WeightSpec(
                key="sam_vit_h_v1",
                filename="sam_vit_h_4b8939.pth",
                license="Apache-2.0",
                source="facebookresearch/segment-anything",
            ),
        )
    }
)


def resolve_weight_path(
    key: str,
    *,
    weights_dir: Path | str | None = None,
    manifest: WeightManifest | None = None,
) -> Path | None:
    """Return the path to the weight named `key`, or None if it is not usable.

    ★ **NEVER downloads. NEVER raises.** "Not usable" covers absent, unknown, unreadable
    and corrupt alike; use :func:`weight_status` when you need to say *which*.

    Args:
        key: A logical manifest key, e.g. ``"superpoint_v1"``.
        weights_dir: The highest-priority directory to search. Usually
            `AiEngineConfig.weights_dir`.
        manifest: The table to resolve against. Defaults to :data:`DEFAULT_MANIFEST`.

    Returns:
        A path to a verified-as-far-as-possible file, or None.
    """
    status = weight_status(key, weights_dir=weights_dir, manifest=manifest)
    return status.path if status.ok else None


def weight_status(
    key: str,
    *,
    weights_dir: Path | str | None = None,
    manifest: WeightManifest | None = None,
) -> WeightStatus:
    """Full verification result for `key` — the reason included. **Never raises.**

    This is what `resolve_with_fallback` step 3 calls, and the `reason` it returns is what
    reaches the operator as ``WarningItem{code:"MODEL_WEIGHTS_MISSING", ...}``.
    """
    table = manifest if manifest is not None else DEFAULT_MANIFEST
    return table.verify(key, weights_dir)
