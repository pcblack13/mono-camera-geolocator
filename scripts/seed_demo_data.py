#!/usr/bin/env python3
"""Seed the offline demo project. CONTRACT.md §2.9, §9.13.

**The offline path needs a front door that is not a test flag.** The brief's hard
requirement is that the system works end to end on a machine with **no network
guarantee**. Esri — the keyless default — needs network; when it is unreachable
`get_tile` raises and the job fails. Both offline providers were previously
unreachable by default: `fixture` was labelled TEST-ONLY and wired to `LE_TESTING`,
and `local_orthophoto` self-skips because `./data/orthophotos` ships empty. The
capability existed and had no door a human could open. This script is that door.

It seeds a demo project whose ``default_provider`` is ``fixture``, backed by the
committed fixture tiles, so::

    make seed && make up

demonstrates **upload → mark → place GCPs → export with the NIC unplugged**.

★ **What this seeds, and what it deliberately does not.**
``CONTRACT.md`` §2.9 describes the demo as "upload → mark → **match** → export".
**In this build there is no match** — the automatic engine is DEFERRED
(``docs/architecture/SCOPE.md``). ``POST /images/{id}/match`` returns **501**, and
seeding a fake match result would be exactly the fabricated confidence SCOPE.md
§4.2 forbids. So this script seeds the project, the image and the annotations —
and **stops there, on purpose**. Placing the GCPs is the demo: the surveyor marks
a landmark in the photo, clicks the same spot on the map, and the coordinate is
recorded as a direct observation. That interaction is the product, and a seeder
cannot perform it for you.

★ **Why this drives the HTTP API rather than the ORM.** Two reasons, both practical:
sqlalchemy is not installed on this machine (§0.1), and inserting rows directly
would bypass every validation, sniff, checksum and EXIF path that ingest exists to
run — proving nothing about whether the demo actually works. Driving §7's public
endpoints exercises the real thing. **stdlib only** (``urllib``): no httpx, no
requests, nothing to install.

Usage::

    make seed                                     # the supported path
    python3 scripts/seed_demo_data.py             # against http://localhost:8000
    python3 scripts/seed_demo_data.py --api-url http://api:8000/api/v1
"""

from __future__ import annotations

import argparse
import json
import mimetypes

import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
# ★ A constant + a --api-url flag, NOT an env var. §13.4 rule 7 requires every env
#   var to appear in §9 and in .env.example, and CI asserts the two match; §9 has
#   no seeder variable. `make seed` passes the flag.
DEFAULT_API_URL = "http://localhost:8000/api/v1"
DEMO_SCENE = REPO_ROOT / "data" / "fixtures" / "demo_scene.jpg"

DEMO_PROJECT_NAME = "Demo — offline field survey"

# The landmarks the demo pre-marks in the photo. Pixel coordinates are in
# ORIGINAL IMAGE PIXEL SPACE (y-down, origin top-left, post-EXIF-orientation) —
# never viewer space. That conversion is normative and correctness-critical
# (SCOPE.md §5); a seeder that wrote viewer coordinates would bake in the exact
# bug the two-stage transform exists to prevent.
#
# demo_scene.jpg is 1280x720 with a horizon at y=240. Every landmark below sits
# well below the horizon, on the ground plane, where a surveyor could actually
# identify it.
DEMO_ANNOTATIONS: tuple[dict[str, Any], ...] = (
    {
        "kind": "field_corner",
        "label": "NW field corner",
        "description": "Corner of the near parcel, left of the track.",
        "pixel": (196.0, 604.0),
        "confidence": 0.9,
    },
    {
        "kind": "road_intersection",
        "label": "Track / canal crossing",
        "description": "Where the farm track crosses the irrigation canal.",
        "pixel": (642.0, 470.0),
        "confidence": 0.85,
    },
    {
        "kind": "field_corner",
        "label": "NE field corner",
        "description": "Corner of the far parcel, right of the track.",
        "pixel": (1042.0, 528.0),
        "confidence": 0.8,
    },
    {
        "kind": "generic",
        "label": "Isolated tree",
        "description": "Solitary tree on the field boundary — a good GCP target.",
        "pixel": (888.0, 640.0),
        "confidence": 0.75,
    },
)


class SeedError(RuntimeError):
    """A seeding step failed in a way the operator must see."""


def _request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, bytes]:
    """Issue one HTTP request with stdlib urllib.

    Returns:
        ``(status, body_bytes)``. HTTP error responses are RETURNED, not raised —
        the caller decides what a 4xx means, because for some steps (a demo that
        already exists) a 4xx is the expected, benign answer.
    """
    request = urllib.request.Request(url, data=body, method=method)  # noqa: S310 — http(s) only, below
    if not url.startswith(("http://", "https://")):
        msg = f"refusing a non-HTTP url: {url}"
        raise SeedError(msg)
    if content_type:
        request.add_header("Content-Type", content_type)
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return (response.status, response.read())
    except urllib.error.HTTPError as exc:
        return (exc.code, exc.read())
    except urllib.error.URLError as exc:
        msg = (
            f"cannot reach the API at {url}: {exc.reason}\n"
            "  Is the stack up?  make up   (or:  docker compose --project-directory . "
            "-f infra/compose/docker-compose.yml up -d)"
        )
        raise SeedError(msg) from exc


def _post_json(api: str, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
    """POST a JSON body, returning ``(status, decoded_body_or_bytes)``."""
    status, raw = _request(
        "POST", f"{api}{path}", body=json.dumps(payload).encode(), content_type="application/json"
    )
    try:
        return (status, json.loads(raw))
    except json.JSONDecodeError:
        return (status, raw)


def _encode_multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    """Encode a multipart/form-data body by hand.

    Hand-rolled because the alternative is a dependency, and this script's whole
    value is that it runs anywhere with nothing installed. The boundary is random
    per call, so it cannot collide with file content.

    Args:
        fields: Plain text form fields.
        file_field: The form field name carrying the upload.
        file_path: The file to send.

    Returns:
        ``(body, content_type_header)``.
    """
    boundary = f"----LandExplorerSeed{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return (b"".join(parts), f"multipart/form-data; boundary={boundary}")


def wait_for_api(api: str, *, attempts: int = 30, delay: float = 1.0) -> None:
    """Block until ``GET /health`` answers 200, or give up with a legible message.

    ``/health`` is the right probe here: it touches no dependency, so it answers as
    soon as the process is up rather than waiting on Postgres (§7.1).
    """
    health = f"{api}/health"
    for attempt in range(1, attempts + 1):
        try:
            status, _ = _request("GET", health, timeout=3.0)
            if status == 200:
                print(f"  api is up ({health})")
                return
        except SeedError:
            pass
        if attempt == attempts:
            msg = (
                f"the API never became healthy at {health} after {attempts} attempts.\n"
                "  Check:  make logs"
            )
            raise SeedError(msg)
        time.sleep(delay)


def find_demo_project(api: str) -> dict[str, Any] | None:
    """Return the existing demo project, or ``None``.

    Makes the seeder **idempotent**: `make seed` twice must not produce two demos.
    """
    status, body = _request("GET", f"{api}/projects?limit=100")
    if status != 200:
        return None
    try:
        page = json.loads(body)
    except json.JSONDecodeError:
        return None
    for item in page.get("items", []):
        if item.get("name") == DEMO_PROJECT_NAME:
            return item
    return None


def create_project(api: str) -> dict[str, Any]:
    """Create the demo project pinned to the offline ``fixture`` provider."""
    payload = {
        "name": DEMO_PROJECT_NAME,
        "description": (
            "Offline demo. Imagery comes from the committed fixture tiles, so this "
            "project works with the network cable unplugged. Automatic matching is "
            "DEFERRED in this build (see docs/architecture/SCOPE.md) — place GCPs "
            "manually: mark a landmark in the photo, then click the same spot on the map."
        ),
        # ★ THE POINT OF THE WHOLE SCRIPT. 'fixture' is deterministic and needs no
        #   network. Its label changed from "TEST-ONLY" to "TEST + OFFLINE DEMO"
        #   precisely so this is a legitimate value for a real project (§9.13).
        "default_provider": "fixture",
        "default_search_zoom": 18,
        "default_search_radius_m": 1000.0,
        "tags": ["demo", "offline"],
        "metadata": {"seeded_by": "scripts/seed_demo_data.py", "offline": True},
    }
    status, body = _post_json(api, "/projects", payload)
    if status != 201:
        msg = f"POST /projects returned {status}: {body!r}"
        raise SeedError(msg)
    return body


def upload_image(api: str, project_id: str, path: Path) -> dict[str, Any]:
    """Upload the demo photograph through the real ingest path (endpoint 9)."""
    if not path.exists():
        msg = (
            f"the demo photo is missing: {path}\n"
            "  Generate it first:  python3 scripts/make_fixtures.py   (or: make fixtures)"
        )
        raise SeedError(msg)
    body, content_type = _encode_multipart({"project_id": project_id}, "file", path)
    status, raw = _request(
        "POST", f"{api}/images", body=body, content_type=content_type, timeout=120.0
    )
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = raw
    # 201 = ingested synchronously. 202 = accepted, ingest went async (the file is
    # over LE_ASYNC_INGEST_THRESHOLD_BYTES). Both are success.
    if status not in (201, 202):
        msg = f"POST /images returned {status}: {decoded!r}"
        raise SeedError(msg)
    if status == 202:
        print("    (202 — ingest queued; annotations may need the worker to finish first)")
    return decoded if isinstance(decoded, dict) else {}


def create_annotations(api: str, image_id: str) -> int:
    """Create the demo landmark points. Returns the number created."""
    created = 0
    for index, spec in enumerate(DEMO_ANNOTATIONS):
        x, y = spec["pixel"]
        payload = {
            "kind": spec["kind"],
            "geom_type": "point",
            # ★ GeoJSON-SHAPED but IMAGE PIXELS: [x, y], y-DOWN, SRID 0. This is not
            #   a coordinate on the Earth and must never be treated as one (§5.2 I1).
            "geometry": {"type": "Point", "coordinates": [x, y]},
            "label": spec["label"],
            "description": spec["description"],
            # ★ 0-1, THE SURVEYOR'S certainty — a declared judgement, never computed.
            "confidence": spec["confidence"],
            "ordering": index,
        }
        status, body = _post_json(api, f"/images/{image_id}/annotations", payload)
        if status != 201:
            print(f"    ! annotation {spec['label']!r} -> {status}: {body!r}", file=sys.stderr)
            continue
        created += 1
        print(f"    ✔ {spec['label']}  @ ({x:.0f}, {y:.0f}) px")
    return created


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="seed_demo_data.py",
        description="Seed the offline demo project (CONTRACT.md §2.9, §9.13).",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help=f"default: {DEFAULT_API_URL}")
    parser.add_argument("--scene", type=Path, default=DEMO_SCENE, help="the demo photograph")
    parser.add_argument(
        "--wait",
        type=int,
        default=30,
        help="seconds to wait for the API to become healthy (default: 30)",
    )
    args = parser.parse_args(argv)
    api = args.api_url.rstrip("/")

    try:
        print(f"Seeding the offline demo against {api}")
        wait_for_api(api, attempts=max(1, args.wait))

        existing = find_demo_project(api)
        if existing is not None:
            print(f"\n  Demo project already exists (id={existing.get('id')}). Nothing to do.")
            print("  Delete it in the UI and re-run to reseed.")
            return 0

        print("\n  Creating the demo project (default_provider=fixture)...")
        project = create_project(api)
        project_id = project["id"]
        print(f"    ✔ project {project_id}")

        print(f"\n  Uploading {args.scene.name} through the real ingest path...")
        image = upload_image(api, project_id, args.scene)
        image_id = image.get("id")
        if not image_id:
            msg = f"upload succeeded but returned no image id: {image!r}"
            raise SeedError(msg)
        print(f"    ✔ image {image_id}")

        print("\n  Marking landmarks in the photo...")
        created = create_annotations(api, image_id)

        print(f"\n✔ Demo seeded: 1 project · 1 image · {created} annotation(s).")
        print("\nWhat to do next — this IS the product:")
        print("  1. Open the workspace and select the demo image.")
        print("  2. Pick a marked landmark in the photo.")
        print("  3. Click the SAME physical spot on the satellite map.")
        print("     -> a GCP is recorded, linking (pixel_x, pixel_y) to (lat, lon).")
        print("  4. Export: CSV · GeoJSON · KML · Shapefile · PDF.")
        print("\nAll of it works offline: the imagery is the committed fixture tiles.")
        print("Automatic matching is DEFERRED in this build — docs/architecture/SCOPE.md.")
        print("Every GCP you place records source='manual' and a confidence YOU declare.")
        return 0
    except SeedError as exc:
        print(f"\n✘ seed failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
