#!/usr/bin/env python3
"""Opt-in model weight fetcher. CONTRACT.md §2.9.

★★ **READ THIS BEFORE RUNNING IT.**

**In this build, downloading weights accomplishes nothing.** The automatic
matching engine is **DEFERRED** (``docs/architecture/SCOPE.md``): SuperPoint,
SuperGlue, LightGlue, LoFTR, DINOv2 and SAM exist as typed stubs that raise
``NotImplementedDeferred``. There is no code path that will load a ``.pth`` you
fetch. This script is kept, working and honest, because §2.9 mandates it and
because it must be ready the day the engine is implemented — but it will tell you
plainly that the weights will sit unused, rather than implying a capability that
does not exist.

**Three properties this script has, deliberately:**

1. **It is never run at build time or boot time.** Not by a Dockerfile, not by an
   entrypoint, not by an import. Ever. A container that downloads 2.4 GB of
   checkpoints on start is a container that fails to start on a train.
2. **It prints the licence of every weight and requires you to accept it.**
   Model weights are not code and are frequently not licensed like code. SuperGlue
   in particular is **research/non-commercial only** — using it in a commercial
   survey deliverable is a licence violation, and that is a fact a surveyor's
   employer needs before the download, not after.
3. **A downloaded weight requires a WORKER RESTART to take effect.** Availability
   is resolved once, at preflight, and cached on ``app.state`` (§11.1) — because
   re-hashing a 2.4 GB checkpoint per request is not a health check, it is an
   outage. Dropping a file into the volume changes nothing until the worker
   restarts.

Usage::

    python3 scripts/download_models.py --list                 # what exists, what is here
    python3 scripts/download_models.py --model superpoint --accept-license
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# LE_AI_MODEL_WEIGHTS_DIR (§9.8). Empty by default AND THAT IS THE SUPPORTED STATE.
DEFAULT_WEIGHTS_DIR = Path(
    os.environ.get("LE_AI_MODEL_WEIGHTS_DIR", str(REPO_ROOT / "data" / "model_weights"))
)


@dataclass(frozen=True)
class WeightSpec:
    """One downloadable weight file.

    Attributes:
        key: The ``--model`` name; matches the registry component key.
        filename: Destination filename inside the weights dir. The env var that
            points the engine at it is named in ``env_var``.
        url: Upstream source. Empty when the weight cannot be redistributed or
            fetched without an account — stated rather than faked.
        sha256: Expected digest, or ``""`` when upstream publishes none. A weight
            with no published digest is downloaded and reported as UNVERIFIED.
        licence: The licence, named exactly.
        commercial_use: Whether commercial use is permitted by that licence.
        env_var: The §9.8 variable that activates it.
        note: Anything the operator must know before fetching.
    """

    key: str
    filename: str
    url: str
    sha256: str
    licence: str
    commercial_use: bool
    env_var: str
    note: str = ""


# ★ Every entry's `deferred` status is the same in this build: DEFERRED. The
#   registry entries exist (SCOPE.md §4) so that re-enabling requires zero changes
#   outside ai_engine/; the bodies raise NotImplementedDeferred.
WEIGHTS: tuple[WeightSpec, ...] = (
    WeightSpec(
        key="superpoint",
        filename="superpoint_v1.pth",
        url="https://github.com/magicleap/SuperPointPretrainedNetwork/raw/master/superpoint_v1.pth",
        sha256="",
        licence="Magic Leap — RESEARCH / NON-COMMERCIAL ONLY",
        commercial_use=False,
        env_var="LE_AI_SUPERPOINT_WEIGHTS",
        note="Non-commercial licence. Do NOT use for a commercial survey deliverable.",
    ),
    WeightSpec(
        key="superglue",
        filename="superglue_outdoor.pth",
        url="https://github.com/magicleap/SuperGluePretrainedNetwork/raw/master/models/weights/superglue_outdoor.pth",
        sha256="",
        licence="Magic Leap — RESEARCH / NON-COMMERCIAL ONLY",
        commercial_use=False,
        env_var="LE_AI_SUPERGLUE_WEIGHTS",
        note="Non-commercial licence, strictly enforced by its author. The outdoor "
        "variant is the relevant one for aerial/satellite work.",
    ),
    WeightSpec(
        key="lightglue",
        filename="superpoint_lightglue.pth",
        url="https://github.com/cvg/LightGlue/releases/download/v0.1_arxiv/superpoint_lightglue.pth",
        sha256="",
        licence="Apache-2.0",
        commercial_use=True,
        env_var="LE_AI_LIGHTGLUE_WEIGHTS",
        note="Apache-2.0 — commercially usable. Pairs with SuperPoint, whose weights "
        "are NOT (see above). The pair is only as permissive as its stricter half.",
    ),
    WeightSpec(
        key="loftr",
        filename="loftr_outdoor.ckpt",
        url="",
        sha256="",
        licence="Apache-2.0 (code) — weights distributed via Google Drive",
        commercial_use=True,
        env_var="LE_AI_LOFTR_WEIGHTS",
        note="No stable direct URL: upstream ships these through Google Drive, which "
        "cannot be fetched unattended. Download by hand and drop the file in.",
    ),
    WeightSpec(
        key="dinov2",
        filename="dinov2_vits14_pretrain.pth",
        url="https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth",
        sha256="",
        licence="Apache-2.0",
        commercial_use=True,
        env_var="LE_AI_DINOV2_WEIGHTS",
    ),
    WeightSpec(
        key="sam",
        filename="sam_vit_b_01ec64.pth",
        url="https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth",
        sha256="ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912",
        licence="Apache-2.0",
        commercial_use=True,
        env_var="LE_AI_SAM_CHECKPOINT",
        note="~375 MB (vit_b, the smallest). vit_h is ~2.4 GB. LE_AI_SEMANTICS_ENABLED "
        "defaults to false regardless.",
    ),
)

_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _scope_banner() -> None:
    """State the deferral before anything else. Nobody should download 375 MB first."""
    print(f"{_YELLOW}{_BOLD}", end="")
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║  AUTOMATIC MATCHING IS DEFERRED IN THIS BUILD.                           ║")
    print("║                                                                          ║")
    print("║  Every deep backend below is a typed stub that raises                    ║")
    print("║  NotImplementedDeferred. NOTHING WILL LOAD A WEIGHT YOU DOWNLOAD TODAY.  ║")
    print("║  See docs/architecture/SCOPE.md.                                         ║")
    print("║                                                                          ║")
    print("║  This build places GCPs MANUALLY — and that path needs no weights,       ║")
    print("║  no GPU and no network.                                                  ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print(f"{_RESET}", end="")


def _sha256(path: Path) -> str:
    """Hash a file in chunks — these run to gigabytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cmd_list(weights_dir: Path) -> int:
    """Print the manifest, each entry's licence, and whether it is already present."""
    _scope_banner()
    print(f"\nWeights directory: {weights_dir}")
    print(f"  {_DIM}(LE_AI_MODEL_WEIGHTS_DIR — empty by default, and that is supported){_RESET}\n")
    for spec in WEIGHTS:
        path = weights_dir / spec.filename
        if path.exists():
            state = f"{_GREEN}present{_RESET} ({path.stat().st_size:,} B)"
        else:
            state = f"{_DIM}absent{_RESET}"
        licence_colour = _GREEN if spec.commercial_use else _RED
        commercial = "commercial OK" if spec.commercial_use else "NON-COMMERCIAL ONLY"
        print(f"  {_BOLD}{spec.key}{_RESET}  [{state}]")
        print(f"    file    {spec.filename}")
        print(f"    licence {licence_colour}{spec.licence}  ({commercial}){_RESET}")
        print(f"    env     {spec.env_var}")
        if not spec.url:
            print(f"    url     {_YELLOW}none — manual download required{_RESET}")
        if spec.note:
            print(f"    note    {spec.note}")
        print()
    print(f"{_DIM}A downloaded weight requires a WORKER RESTART to take effect: availability{_RESET}")
    print(f"{_DIM}is resolved once at preflight and cached for the process lifetime (§11.1).{_RESET}")
    return 0


def cmd_download(key: str, weights_dir: Path, *, accepted: bool, force: bool) -> int:
    """Fetch one weight after an explicit licence acceptance."""
    spec = next((w for w in WEIGHTS if w.key == key), None)
    if spec is None:
        print(f"unknown model {key!r}. Known: {', '.join(w.key for w in WEIGHTS)}", file=sys.stderr)
        return 2

    _scope_banner()

    if not spec.url:
        print(f"\n{_YELLOW}{spec.key} has no unattended download URL.{_RESET}", file=sys.stderr)
        print(f"  {spec.note}", file=sys.stderr)
        print(f"  Place the file at: {weights_dir / spec.filename}", file=sys.stderr)
        return 1

    print(f"\n{_BOLD}{spec.key}{_RESET}")
    print(f"  licence: {spec.licence}")
    if not spec.commercial_use:
        print(f"  {_RED}{_BOLD}THIS WEIGHT MAY NOT BE USED COMMERCIALLY.{_RESET}")
        print(f"  {_RED}A GCP produced with it must not go into a commercial deliverable.{_RESET}")
    if spec.note:
        print(f"  note: {spec.note}")

    if not accepted:
        print(
            f"\n{_YELLOW}Refusing to download without an explicit licence acceptance.{_RESET}",
            file=sys.stderr,
        )
        print("  Re-run with --accept-license once you have read the licence above.", file=sys.stderr)
        return 1

    destination = weights_dir / spec.filename
    if destination.exists() and not force:
        print(f"\n{_GREEN}already present:{_RESET} {destination}")
        if spec.sha256:
            actual = _sha256(destination)
            ok = actual == spec.sha256
            print(f"  sha256 {'✔ matches' if ok else '✘ MISMATCH'}")
            if not ok:
                print(f"    expected {spec.sha256}\n    actual   {actual}", file=sys.stderr)
                return 1
        print("  Use --force to re-download.")
        return 0

    weights_dir.mkdir(parents=True, exist_ok=True)
    # Download to a temp name and rename only on success, so an interrupted fetch
    # can never leave a truncated file that looks present to the registry.
    temp = destination.with_suffix(destination.suffix + ".partial")
    print(f"\n  fetching {spec.url}")
    try:
        with urllib.request.urlopen(spec.url, timeout=60) as response, temp.open("wb") as handle:  # noqa: S310
            total = int(response.headers.get("Content-Length", 0))
            done = 0
            while chunk := response.read(1024 * 256):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100.0 * done / total
                    print(f"\r  {done:,} / {total:,} B ({pct:5.1f}%)", end="", flush=True)
                else:
                    print(f"\r  {done:,} B", end="", flush=True)
        print()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        temp.unlink(missing_ok=True)
        print(f"\n{_RED}download failed: {exc}{_RESET}", file=sys.stderr)
        print("  This machine has no network guarantee. That is expected, not a bug.", file=sys.stderr)
        return 1

    if spec.sha256:
        actual = _sha256(temp)
        if actual != spec.sha256:
            temp.unlink(missing_ok=True)
            print(f"{_RED}sha256 MISMATCH — discarded.{_RESET}", file=sys.stderr)
            print(f"  expected {spec.sha256}\n  actual   {actual}", file=sys.stderr)
            return 1
        print(f"  {_GREEN}sha256 ✔{_RESET}")
    else:
        print(f"  {_YELLOW}! UNVERIFIED — upstream publishes no digest for this file.{_RESET}")

    temp.rename(destination)
    print(f"\n{_GREEN}✔ {destination}{_RESET}")
    print(f"\n  Point the engine at it:  {spec.env_var}={destination}")
    print(f"  {_BOLD}Then RESTART THE WORKER{_RESET} — preflight is cached for the process")
    print("  lifetime, so a new file is invisible until the process restarts (§11.1).")
    print(f"\n  {_YELLOW}Reminder: nothing loads this in the current build (SCOPE.md).{_RESET}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="download_models.py",
        description="Opt-in model weight fetcher. NEVER run at build or boot time. "
        "NOTE: the deep backends are DEFERRED in this build (docs/architecture/SCOPE.md).",
    )
    parser.add_argument("--list", action="store_true", help="show the manifest and exit")
    parser.add_argument("--model", help=f"one of: {', '.join(w.key for w in WEIGHTS)}")
    parser.add_argument(
        "--accept-license",
        action="store_true",
        help="assert you have read and accept the model's licence. Required to download: "
        "some of these weights are NON-COMMERCIAL and a survey deliverable is commercial.",
    )
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument("--weights-dir", type=Path, default=DEFAULT_WEIGHTS_DIR)
    args = parser.parse_args(argv)

    if args.list or not args.model:
        return cmd_list(args.weights_dir)
    return cmd_download(
        args.model, args.weights_dir, accepted=args.accept_license, force=args.force
    )


if __name__ == "__main__":
    raise SystemExit(main())
