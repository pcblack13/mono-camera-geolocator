"""Camera pose and the confidence heatmap — endpoints 48, 49 (§6.2 puts both here).

★★ SCOPE.md §4: camera-pose estimation and the confidence heatmap are ABCs only, and SCOPE.md
§4 rule 3 lists ``/camera-pose`` and ``/heatmap`` among the deferred endpoints. Both GETs — and
the ``PATCH`` pose override — are **registered and documented** and return ``501`` + ``feature:
"deferred"``.

★ Flagged cross-unit note: ``PoseService`` / ``HeatmapService`` also expose *real read* methods
(``get_selected_or_raise`` → 404) intended for when the feature is live. In this build the SCOPE
ruling and the IU-17 schema docstrings both say these endpoints return 501, so that is what they
do; the 404 read path is dormant until the feature is enabled.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api import deps
from app.core.exceptions import FeatureDeferredError
from app.schemas.pose import CameraPoseRead, CameraPoseUpdate, HeatmapRead

router = APIRouter()

_POSE_MESSAGE = (
    "Automatic camera-pose estimation is not enabled in this build (SCOPE.md §4). Place GCPs "
    "manually; a human asserting where they stood needs no CV."
)
_HEATMAP_MESSAGE = (
    "The confidence heatmap is part of the deferred automatic matching engine and is not enabled "
    "in this build (SCOPE.md §4). Place GCPs manually."
)


@router.get("/images/{image_id}/camera-pose", response_model=CameraPoseRead, summary="Camera pose (DEFERRED)")
async def get_camera_pose(image=Depends(deps.get_image)) -> CameraPoseRead:
    raise FeatureDeferredError(_POSE_MESSAGE, component="ai_engine.geometry.pose")


@router.patch("/images/{image_id}/camera-pose", response_model=CameraPoseRead, summary="Override camera pose (DEFERRED)")
async def update_camera_pose(
    body: CameraPoseUpdate,
    image=Depends(deps.get_image),
    _: None = Depends(deps.require_writable),
) -> CameraPoseRead:
    raise FeatureDeferredError(_POSE_MESSAGE, component="ai_engine.geometry.pose")


@router.get("/images/{image_id}/heatmap", response_model=HeatmapRead, summary="Confidence heatmap (DEFERRED)")
async def get_heatmap(image=Depends(deps.get_image)) -> HeatmapRead:
    raise FeatureDeferredError(_HEATMAP_MESSAGE, component="ai_engine.heatmap.posterior")
