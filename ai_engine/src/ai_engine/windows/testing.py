"""`SyntheticWindowSource` — ★ REAL. Procedural farmland with a KNOWN ground-truth answer.

★ THIS IS NOT DEFERRED, AND KEEPING IT IS A DELIBERATE RULING (SCOPE §6): *"The synthetic
known-homography fixtures are still created — they are the future engine's acceptance
harness, and they cost nothing now."* Every line here is procedural numpy. There is no CV,
no network, no weight file and no fixture on disk.

★ WHAT IT IS FOR. It makes the entire engine testable against a **known answer**. A
`WindowSource` that generates its own imagery from a seed, and can also state exactly which
homography relates a given camera to a given window, is the only way to measure end-to-end
pixel error without ground truth someone had to survey by hand. `test_pipeline_e2e` asserts
< 2 px against it, and `tests/e2e/` uses it too — which is why it ships in the package
rather than under `tests/`.

★ IT SHIPS TODAY, UNUSED, ON PURPOSE. The pipeline that would consume it is deferred. But
this is the harness that will decide whether the automatic engine is good enough to enable
— and SCOPE §2 makes the same point from the other side: the manual correspondences this
product collects are the ground-truth dataset an automatic engine must be measured against.
Building the measuring instrument before the thing it measures is the right order.

★ ON THE OPAQUE FIELDS. `CandidateWindow.geotransform` and `.crs` are an opaque payload
that `ai_engine` carries and never interprets (L3). This module **constructs** them — a
source has to — but nothing here reads them back, and the values are internally consistent
with the plane frame below, so a `gis`-side test can use this source meaningfully too.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterator

import numpy as np

from ai_engine.types import CandidateWindow, WindowRef

__all__ = [
    "SyntheticCameraPose",
    "SyntheticWindowSource",
    "ground_truth_homography",
]

#: An opaque payload string. ★ Deliberately not an authority code: `ai_engine` must not
#: know what one is, and naming a real one inside the very type that exists to be
#: agnostic would invite exactly the parsing L3 forbids.
SYNTHETIC_FRAME_TAG = "synthetic:plane-frame"

#: Attribution is a REQUIRED field on `CandidateWindow` for a licensing reason — pixels
#: must not travel without it. Synthetic pixels have no licensor, and saying so plainly is
#: better than an empty string that would look like a dropped obligation.
SYNTHETIC_ATTRIBUTION = "Synthetic procedural imagery (LandExplorer test harness)"
SYNTHETIC_TERMS_URL = "https://example.invalid/landexplorer/synthetic-imagery"


@dataclass(frozen=True, slots=True)
class SyntheticCameraPose:
    """A camera viewing the synthetic ground plane.

    ★ THIS TYPE IS THIS UNIT'S CHOICE. §13.2 mandates
    ``ground_truth_homography(window_ref, camera_pose)`` but specifies no pose type, and
    `types.geometry.PoseResult` is the wrong one to demand here — it carries `R`, `t`,
    `intrinsics`, `reproj_error_px` and `inlier_count`, i.e. the *output* of a solve. A test
    fixture needs to state a viewpoint in terms a human can reason about, so this is the
    input form. Flagged as an open decision in the unit report.

    Angle conventions match `PoseResult`'s exactly, and that is the point of stating them:

    Attributes:
        yaw_deg: The view bearing. ★ `0` is **-y of the window frame** — UP the raster —
            increasing clockwise. Identical to `PoseResult.yaw_deg`, so a solver's output
            can be compared against a fixture's input with no conversion. (Taking `0 = +y`
            instead is a silent 180° error, because a north-up raster's `+y` points the
            opposite way.)
        tilt_deg: The angle from straight down. `0` is nadir; `90` is horizontal. The
            regimes this product cares about are the oblique ones — which is why a
            nadir-only fixture proves almost nothing.
        roll_deg: Rotation about the optical axis, positive clockwise.
        height_m: The camera's height above the plane, in metres.
        position_m: The camera's horizontal `(east, north)` position in the plane frame, in
            metres. `(0,0)` is the window centre.
        focal_px: The focal length in pixels.
        image_size: `(width, height)` of the camera image.
    """

    yaw_deg: float = 0.0
    tilt_deg: float = 0.0
    roll_deg: float = 0.0
    height_m: float = 120.0
    position_m: tuple[float, float] = (0.0, 0.0)
    focal_px: float = 900.0
    image_size: tuple[int, int] = (1024, 768)

    def rotation(self) -> np.ndarray:
        """The world→camera rotation `R`, such that ``p_cam = R @ p_world + t``.

        World is local ENU (X east, Y north, Z up); camera is OpenCV (x right, y down,
        z forward). At nadir with `yaw=0` this returns ``diag(1, -1, -1)``: east is image
        `+x`, north is image `-y` (up the image), and the ground is `+z` (in front).

        Returns:
            `(3,3)` float64, orthonormal, `det == +1`.
        """
        psi = np.deg2rad(self.yaw_deg)
        tau = np.deg2rad(self.tilt_deg)
        phi = np.deg2rad(self.roll_deg)

        # Horizontal component of the view direction: yaw 0 => +north, clockwise positive.
        d_h = np.array([np.sin(psi), np.cos(psi), 0.0])
        # Straight down at tilt 0; swings toward d_h as tilt increases.
        forward = np.sin(tau) * d_h + np.cos(tau) * np.array([0.0, 0.0, -1.0])
        # To the right of the view direction, in the horizontal plane. Well-defined at
        # nadir, where cross(forward, up) is degenerate and would silently produce NaN.
        right = np.array([np.cos(psi), -np.sin(psi), 0.0])
        down = np.cross(forward, right)

        if phi:
            c, s = np.cos(phi), np.sin(phi)
            right, down = c * right + s * down, -s * right + c * down

        R = np.stack([right, down, forward], axis=0)
        return R.astype(np.float64)

    def camera_position_enu(self) -> np.ndarray:
        """The camera's position `C` in the plane frame, metres. `(3,)` float64."""
        east, north = self.position_m
        return np.array([east, north, self.height_m], dtype=np.float64)

    def translation(self) -> np.ndarray:
        """`t` in ``p_cam = R @ p_world + t``, i.e. ``-R @ C``. `(3,)` float64.

        ★ NOT the camera position. `t` is the world origin expressed in camera
        coordinates; the position is `C = -R.T @ t`. The two coincide only at nadir, which
        is why taking `camera_height_m = t[2]` is exactly right at `tilt=0` and wrong by 2×
        at 60° and ~5.8× at 80° — and why this class exposes both, named for what they are.
        """
        return -self.rotation() @ self.camera_position_enu()

    def intrinsic_matrix(self) -> np.ndarray:
        """`K`, with the principal point at the image centre. `(3,3)` float64."""
        width, height = self.image_size
        return np.array(
            [
                [self.focal_px, 0.0, (width - 1) / 2.0],
                [0.0, self.focal_px, (height - 1) / 2.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )


def _plane_to_window(gsd_m: float, window_size: tuple[int, int]) -> np.ndarray:
    """`S`, mapping plane metres `(X, Y, 1)` onto window pixels `(u, v, 1)`.

    The window is a nadir, north-up raster of the plane, centred on the plane origin. `v`
    increases **downward**, i.e. southward — which is why `S[1,1]` is negative, and why
    `yaw_deg = 0` means `-y` of this frame.
    """
    width, height = window_size
    return np.array(
        [
            [1.0 / gsd_m, 0.0, (width - 1) / 2.0],
            [0.0, -1.0 / gsd_m, (height - 1) / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def ground_truth_homography(
    window_ref: WindowRef,
    camera_pose: SyntheticCameraPose,
    *,
    gsd_m: float = 0.5,
    window_size: tuple[int, int] = (1024, 1024),
) -> np.ndarray:
    """★ THE ANSWER: the homography mapping CAMERA pixels onto WINDOW pixels.

    Direction matches the engine's convention throughout: **a-frame → b-frame**, where `a`
    is the query photograph and `b` is the window. It is what `HomographyResult.H` must
    equal, so a test can compare a solve against it directly.

    The derivation, which is exact rather than approximate because the scene is exactly
    planar::

        p_img ~ K · (R · [X, Y, 0]ᵀ + t)  =  K · [r₁ | r₂ | t] · [X, Y, 1]ᵀ
        [X, Y, 1]ᵀ = S⁻¹ · p_win
        ⇒  H_win→img = K · [r₁ | r₂ | t] · S⁻¹
        ⇒  H_img→win = (H_win→img)⁻¹

    Args:
        window_ref: The window whose frame is the target. Its `key` is accepted for
            symmetry with the source and is **not parsed** — the frame is defined by
            `gsd_m` and `window_size`, which are passed explicitly precisely so that
            nothing here has to reach into an opaque handle.
        camera_pose: The viewpoint.
        gsd_m: Ground metres per window pixel. Must match the source's.
        window_size: `(width, height)` of the window. Must match the source's.

    Returns:
        `(3,3)` float64, normalised so that `H[2,2] == 1` — the `h33 = 1` gauge §4.24 uses
        for covariance, applied here so a fixture and a solve are comparable without
        anyone having to guess a scale.

    Raises:
        ValueError: The pose looks along the plane (`tilt_deg` at or past 90°) or otherwise
            produces a singular map. ★ It raises rather than returning a
            pseudo-inverse: a camera that cannot see the plane has no homography to the
            plane, and a matrix of plausible numbers here would become a "ground truth" that
            every test silently measured itself against.
    """
    del window_ref  # Opaque. Named in the signature per §13.2; never parsed. See Args.

    K = camera_pose.intrinsic_matrix()
    R = camera_pose.rotation()
    t = camera_pose.translation()
    S = _plane_to_window(gsd_m, window_size)

    M = np.column_stack([R[:, 0], R[:, 1], t])  # plane (X,Y,1) -> camera ray
    plane_to_img = K @ M

    if abs(np.linalg.det(plane_to_img)) < 1e-12:
        raise ValueError(
            f"the pose (tilt={camera_pose.tilt_deg}°, height={camera_pose.height_m} m) "
            f"produces a singular plane-to-image map: the camera cannot see the ground "
            f"plane, so no homography to it exists. Refusing to return a pseudo-inverse "
            f"that would be adopted as ground truth."
        )

    win_to_img = plane_to_img @ np.linalg.inv(S)
    img_to_win = np.linalg.inv(win_to_img)

    if abs(img_to_win[2, 2]) < 1e-12:
        raise ValueError(
            "the resulting homography has h33 ~ 0 and cannot be normalised into the h33=1 "
            "gauge; the camera centre lies on the plane."
        )
    return img_to_win / img_to_win[2, 2]


class SyntheticWindowSource:
    """A `WindowSource` that generates procedural farmland from a `(key, seed)` hash.

    Structurally satisfies `ai_engine.types.WindowSource` — `name`, `__len__`, `__iter__` —
    without inheriting from it, exactly as `gis.candidates.source.TileWindowSource` does.
    That is the seam working: the engine cannot tell this apart from a live tile source, and
    that is what makes the engine testable with no network at all.

    Every window is deterministic in its key: the same key yields byte-identical pixels
    forever, on any machine, with no fixture on disk.
    """

    def __init__(
        self,
        *,
        keys: tuple[str, ...] = ("w0", "w1", "w2", "w3"),
        seed: int = 42,
        window_size: tuple[int, int] = (1024, 1024),
        gsd_m: float = 0.5,
        name: str = "synthetic",
        provider: str = "synthetic",
    ) -> None:
        """Configure the generator.

        Args:
            keys: The window keys to yield, in order. Opaque strings; their only meaning is
                as a generator seed and a cache key.
            seed: The global seed, mixed with each key.
            window_size: `(width, height)` of every window, in pixels.
            gsd_m: True ground metres per pixel. ★ Passed in, never derived — deriving it
                needs the window's position on the planet, which this package may not know.
            name: The source's name, for provenance.
            provider: The provider string stamped onto each `WindowRef`.

        Raises:
            ValueError: `keys` is empty, or the size or `gsd_m` is non-positive.
        """
        if not keys:
            raise ValueError("SyntheticWindowSource needs at least one key")
        width, height = window_size
        if width <= 0 or height <= 0:
            raise ValueError(f"window_size must be positive; got {window_size!r}")
        if gsd_m <= 0:
            raise ValueError(f"gsd_m must be positive; got {gsd_m}")

        self.name = name
        self.keys = tuple(keys)
        self.seed = seed
        self.window_size = (int(width), int(height))
        self.gsd_m = float(gsd_m)
        self.provider = provider

    def __len__(self) -> int:
        """The window count, known up front — which is what makes progress honest."""
        return len(self.keys)

    def __iter__(self) -> Iterator[CandidateWindow]:
        """Yield every window lazily, in key order."""
        for key in self.keys:
            yield self.window_for(key)

    def rng_for(self, key: str) -> np.random.Generator:
        """The deterministic generator for `key`.

        Seeded from a sha256 of `(seed, key)` rather than from `hash(key)`: Python's `hash`
        is salted per process, so a `hash`-seeded fixture would generate different imagery
        on every run and every worker — the sort of non-determinism that makes a flaky test
        look like a real regression.
        """
        digest = hashlib.sha256(f"{self.seed}:{key}".encode()).digest()
        return np.random.default_rng(int.from_bytes(digest[:8], "big"))

    def geotransform_for(self) -> tuple[float, float, float, float, float, float]:
        """The opaque payload transform for a window, in the conventional six-float order.

        Consistent with `_plane_to_window`'s inverse, so the synthetic frame is coherent for
        anything downstream that *is* allowed to interpret it. Constructed here and never
        read back — see the module docstring.
        """
        width, height = self.window_size
        origin_x = -((width - 1) / 2.0) * self.gsd_m
        origin_y = ((height - 1) / 2.0) * self.gsd_m
        return (origin_x, self.gsd_m, 0.0, origin_y, 0.0, -self.gsd_m)

    def window_for(self, key: str) -> CandidateWindow:
        """Generate the window named `key`.

        Args:
            key: An opaque window key.

        Returns:
            A `CandidateWindow` with C-contiguous `(H,W,3)` uint8 RGB pixels.
        """
        rgb = self.render(key)
        return CandidateWindow(
            ref=WindowRef(key=key, provider=self.provider),
            rgb=rgb,
            geotransform=self.geotransform_for(),
            crs=SYNTHETIC_FRAME_TAG,
            gsd_m=self.gsd_m,
            georef_ce90_m=0.0,  # Synthetic imagery is exact by construction.
            attribution=SYNTHETIC_ATTRIBUTION,
            terms_url=SYNTHETIC_TERMS_URL,
            captured_at=None,
            is_authoritative=False,
            placeholder_fraction=0.0,
            bands=("R", "G", "B"),
            supports_multispectral=False,
            extra_bands=None,
            meta={"synthetic": True, "zoom_clamped": False},
        )

    def render(self, key: str) -> np.ndarray:
        """Render one window's pixels: soil, fields, crop rows, a canal, an orchard.

        Deliberately built from the structures the engine's semantics layer is designed to
        find — rows at a seeded orientation and spacing, field borders, a canal ribbon, a
        tree lattice — so that a test exercises the same features a real scene would offer,
        and so that a matcher has genuinely repeated texture to be confused by.

        Args:
            key: The window key. The same key always renders identical pixels.

        Returns:
            `(H,W,3)` uint8 RGB, C-contiguous.
        """
        rng = self.rng_for(key)
        width, height = self.window_size
        ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)

        # --- base soil, with a slow large-scale tint so the scene is not flat ----------
        soil = np.array([134.0, 108.0, 82.0])
        tint = 0.06 * np.sin(xs / (width / 3.0) + rng.uniform(0, 6.28)) + 0.06 * np.cos(
            ys / (height / 3.0) + rng.uniform(0, 6.28)
        )
        img = soil[None, None, :] * (1.0 + tint)[:, :, None]

        # --- fields: a few rectangles, each with its own crop colour ------------------
        n_fields = int(rng.integers(3, 6))
        field_id = np.zeros((height, width), dtype=np.int32)
        for idx in range(1, n_fields + 1):
            x0 = rng.integers(0, width)
            y0 = rng.integers(0, height)
            w = rng.integers(width // 5, width // 2)
            h = rng.integers(height // 5, height // 2)
            x1 = min(width, int(x0 + w))
            y1 = min(height, int(y0 + h))
            field_id[int(y0) : y1, int(x0) : x1] = idx

        for idx in range(1, n_fields + 1):
            mask = field_id == idx
            if not mask.any():
                continue
            crop = np.array(
                [rng.uniform(60, 110), rng.uniform(110, 165), rng.uniform(45, 90)]
            )
            img[mask] = crop

            # --- crop rows: a sinusoid along a seeded orientation ----------------------
            theta = rng.uniform(0.0, np.pi)  # undirected: rows fold to [0, pi)
            spacing = rng.uniform(9.0, 22.0)
            phase = (xs * np.cos(theta) + ys * np.sin(theta)) * (2.0 * np.pi / spacing)
            rows = 0.5 + 0.5 * np.sin(phase)
            img[mask] *= (0.78 + 0.22 * rows)[mask][:, None]

        # --- canal: a straight ribbon of water ----------------------------------------
        cx, cy = rng.uniform(0, width), rng.uniform(0, height)
        angle = rng.uniform(0.0, np.pi)
        nx, ny = np.sin(angle), -np.cos(angle)
        dist = np.abs((xs - cx) * nx + (ys - cy) * ny)
        canal_w = rng.uniform(3.0, 7.0)
        canal = dist < canal_w
        img[canal] = np.array([48.0, 78.0, 116.0])
        banks = (dist >= canal_w) & (dist < canal_w + 2.0)
        img[banks] = np.array([150.0, 138.0, 110.0])

        # --- orchard: a two-axis tree lattice -----------------------------------------
        pitch = rng.uniform(26.0, 44.0)
        lat_theta = rng.uniform(0.0, np.pi / 2.0)
        ox, oy = rng.uniform(0, pitch), rng.uniform(0, pitch)
        ct, st = np.cos(lat_theta), np.sin(lat_theta)
        u = (xs - ox) * ct + (ys - oy) * st
        v = -(xs - ox) * st + (ys - oy) * ct
        du = u - np.round(u / pitch) * pitch
        dv = v - np.round(v / pitch) * pitch
        trees = (du * du + dv * dv) < (pitch * 0.16) ** 2
        img[trees] = np.array([38.0, 74.0, 40.0])

        # --- sensor noise: enough texture for a detector to bite on -------------------
        img += rng.normal(0.0, 3.0, size=img.shape)

        return np.ascontiguousarray(np.clip(img, 0, 255).astype(np.uint8))

    def __repr__(self) -> str:
        return (
            f"SyntheticWindowSource(name={self.name!r}, windows={len(self.keys)}, "
            f"size={self.window_size}, gsd_m={self.gsd_m})"
        )
