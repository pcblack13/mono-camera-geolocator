"""The canonical object-key layout — the single source of truth for paths (§2.4).

★ **Never build a key with an f-string at a call site.** Two units composing the same
path independently is how the API writes ``images/{id}/original.jpg`` and the worker
reads ``images/{id}/original`` forever. Every key in the system is minted by a
function here.

The layout::

    images/{project_id}/{image_id}/original{ext}
    images/{project_id}/{image_id}/thumbnails/{size}.jpg
    images/{project_id}/{image_id}/overviews/{level}.tif
    matches/{image_id}/{match_result_id}/satellite.png
    exports/{project_id}/{export_id}/{filename}

Project-first, because it makes "delete a project's bytes" a prefix delete rather
than a table scan followed by N deletes, and because it keeps one customer's data in
one place when someone eventually needs to move it.

``storage_path`` is **NEVER serialised to the wire** (§5.5, §5.098). It is a
server-controlled path; exposing it invites path-traversal probing and leaks the
storage layout. Clients get ``urls.file``.
"""

from __future__ import annotations

import posixpath
import re
from typing import Final
from uuid import UUID

__all__ = [
    "KEY_SEPARATOR",
    "export_key",
    "export_prefix",
    "image_original_key",
    "image_overview_key",
    "image_prefix",
    "image_thumbnail_key",
    "project_prefix",
    "safe_filename",
    "satellite_window_key",
    "validate_key",
    "video_original_key",
    "video_preview_key",
    "video_prefix",
]

#: Always "/", on every backend. S3 has no directories and this is a convention;
#: the local backend maps it onto os.sep itself. A key is never an OS path.
KEY_SEPARATOR: Final = "/"

_IMAGES_ROOT: Final = "images"
_VIDEOS_ROOT: Final = "videos"
_MATCHES_ROOT: Final = "matches"
_EXPORTS_ROOT: Final = "exports"
_DEM_ROOT: Final = "dem"

#: What may appear in a key segment. Deliberately narrow: alphanumerics, dot, dash,
#: underscore. Everything the system mints is a UUID, an enum value or a sanitised
#: filename, so nothing legitimate is excluded — and the characters excluded are
#: exactly the ones that make a key mean something different to S3 than to a
#: filesystem.
_SAFE_SEGMENT_RE: Final = re.compile(r"^[A-Za-z0-9._-]+$")
_UNSAFE_FILENAME_RE: Final = re.compile(r"[^A-Za-z0-9._-]+")

_MAX_KEY_LENGTH: Final = 900  # S3's limit is 1024 bytes; leave headroom for a suffix.


def validate_key(key: str) -> str:
    """Assert a key cannot escape its namespace, and return it.

    Called on the way *in* to every ``ObjectStorage`` method, not merely at the mint
    sites, because a key can also arrive from a database row written by an older
    version of this code, and ``../../etc/passwd`` reaching an ``open()`` is the same
    catastrophe whichever way it got there.

    Raises:
        ValueError: absolute, empty, over-long, or containing a traversal or an
            unsafe character.
    """
    if not key:
        raise ValueError("storage key is empty")
    if len(key) > _MAX_KEY_LENGTH:
        raise ValueError(f"storage key exceeds {_MAX_KEY_LENGTH} characters")
    if key.startswith("/") or key.startswith("\\"):
        raise ValueError(f"storage key must be relative: {key!r}")
    if "\\" in key:
        # A backslash is a path separator on one OS and a literal on another. Never
        # in a key.
        raise ValueError(f"storage key must not contain a backslash: {key!r}")
    if "\x00" in key:
        raise ValueError("storage key must not contain a null byte")

    for segment in key.split(KEY_SEPARATOR):
        if segment in ("", ".", ".."):
            raise ValueError(f"storage key contains a traversal or empty segment: {key!r}")
        if not _SAFE_SEGMENT_RE.match(segment):
            raise ValueError(f"storage key segment {segment!r} contains unsafe characters")

    # Belt and braces: even having checked each segment, confirm normalisation is a
    # no-op. This catches anything the segment loop's grammar failed to anticipate.
    if posixpath.normpath(key) != key:
        raise ValueError(f"storage key is not normalised: {key!r}")

    return key


def safe_filename(filename: str, *, default: str = "file") -> str:
    """Sanitise a user-supplied filename into a single safe key segment.

    Uploads carry whatever the surveyor's camera or filesystem produced — spaces,
    parentheses, Cyrillic, occasionally a newline. The original is preserved in
    ``images.filename`` for display; this is what may become part of a key.
    """
    stem = posixpath.basename(filename.strip().replace("\\", "/"))
    cleaned = _UNSAFE_FILENAME_RE.sub("_", stem).strip("._")
    if not cleaned or cleaned in (".", ".."):
        return default
    return cleaned[:200]


def _ext(filename: str) -> str:
    """The lowercased extension, dot included, or "" — sanitised as a key segment."""
    suffix = posixpath.splitext(filename)[1].lower()
    if not suffix or not _SAFE_SEGMENT_RE.match(suffix.lstrip(".") or "x"):
        return ""
    return suffix[:16]


def project_prefix(project_id: UUID) -> str:
    """Every key under one project. For a prefix delete on hard-delete."""
    return f"{_IMAGES_ROOT}/{project_id}/"


def image_prefix(project_id: UUID, image_id: UUID) -> str:
    """Every key belonging to one image — original, thumbnails and overviews."""
    return f"{_IMAGES_ROOT}/{project_id}/{image_id}/"


def image_original_key(project_id: UUID, image_id: UUID, filename: str) -> str:
    """The uploaded bytes, byte-for-byte as received.

    The extension is carried through from the upload so the file is recognisable when
    an operator goes looking, but the *name* is ``original``: the surveyor's filename
    is display metadata, and letting it into the key would make the key
    non-deterministic and re-derivable only by reading the row.
    """
    return validate_key(f"{image_prefix(project_id, image_id)}original{_ext(filename)}")


def image_thumbnail_key(project_id: UUID, image_id: UUID, size: str) -> str:
    """A generated thumbnail. Always JPEG — a thumbnail of a 500 MB GeoTIFF is a
    preview, not evidence, and PNG would cost bandwidth for nothing."""
    return validate_key(f"{image_prefix(project_id, image_id)}thumbnails/{size}.jpg")


def image_overview_key(project_id: UUID, image_id: UUID, level: int) -> str:
    """A downsampled pyramid level for large uploads (``ingest_image_task``)."""
    if level < 0:
        raise ValueError(f"overview level must be >= 0, got {level}")
    return validate_key(f"{image_prefix(project_id, image_id)}overviews/{level}.tif")


def video_prefix(project_id: UUID | None, video_id: UUID) -> str:
    """Every key belonging to one video."""
    # ★ A clip with no project (0018) files under an explicit segment — never under a
    #   literal "None", and never under some project it does not belong to.
    owner = project_id if project_id is not None else "unassigned"
    return f"{_VIDEOS_ROOT}/{owner}/{video_id}/"


def video_preview_key(project_id: UUID | None, video_id: UUID) -> str:
    """The browser-playable H.264 preview transcoded from the original.

    ★ A FIXED name, no filename echo: existence of this key IS the "preview ready"
    signal (`VideoRead.preview_available`), so it must be derivable from ids alone.
    """
    return f"{video_prefix(project_id, video_id)}preview.mp4"


def video_original_key(project_id: UUID | None, video_id: UUID, filename: str) -> str:
    """The uploaded video bytes, byte-for-byte as received.

    Mirrors :func:`image_original_key`: the extension carries through so an operator can
    recognise the container, but the *name* is ``original`` — the surveyor's filename is
    display metadata and letting it into the key would make the key non-deterministic.
    """
    return validate_key(f"{video_prefix(project_id, video_id)}original{_ext(filename)}")


def satellite_window_key(image_id: UUID, match_result_id: UUID) -> str:
    """The cached satellite mosaic backing a match result.

    ★ This is ``match_results.satellite_image_path``, which §5.6 records as having had
    **no producer** in v1.0: nothing in the pipeline wrote the mosaic anywhere.
    ``app.tasks.matching`` now persists ``best.window.rgb`` through ``ObjectStorage``
    at this key. The column is nullable and stays NULL in this build, since SCOPE.md
    defers the matching engine that would fill it.
    """
    return validate_key(f"{_MATCHES_ROOT}/{image_id}/{match_result_id}/satellite.png")


def export_prefix(project_id: UUID) -> str:
    """Every export belonging to one project. For the TTL sweep."""
    return f"{_EXPORTS_ROOT}/{project_id}/"


def export_key(project_id: UUID, export_id: UUID, filename: str) -> str:
    """A rendered export artefact.

    The filename is kept (sanitised) because it is what the surveyor downloads and
    what ``Content-Disposition`` announces — ``parcel-7-gcps.csv`` is worth preserving
    in a way that an upload's original name is not.
    """
    return validate_key(f"{export_prefix(project_id)}{export_id}/{safe_filename(filename)}")


def dem_prefix(run_id: UUID) -> str:
    """Every artefact of one DEM processing run. For the TTL sweep and for delete.

    ★ Keyed by RUN, not by project: a DEM run is a stateless file transformation that
    owns no database row and belongs to no project (``gis.dem``). The run id in the URL
    is the only handle to it, which is also what bounds its lifetime.
    """
    return f"{_DEM_ROOT}/{run_id}/"


def dem_source_key(run_id: UUID, filename: str) -> str:
    """The uploaded DEM, as received. Kept so a run can be re-processed with new
    parameters without asking the surveyor to re-upload 200 MB over a field uplink."""
    return validate_key(f"{dem_prefix(run_id)}source{_ext(filename)}")


def dem_output_key(run_id: UUID, filename: str) -> str:
    """The processed GeoTIFF the surveyor downloads."""
    return validate_key(f"{dem_prefix(run_id)}{safe_filename(filename)}")
