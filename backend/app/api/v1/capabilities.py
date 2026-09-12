"""Capabilities — endpoint 3 (§11.1).

★ **READS the cached ``PreflightReport``** off ``app.state`` and NEVER re-resolves. Re-hashing a
2.4 GB SAM checkpoint per call is an outage, not a health check. Every ``ai_engine`` component
reports ``status="deferred"`` (SCOPE.md §4); providers and exports report honestly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api import deps
from app.schemas.capabilities import CapabilitiesResponse
from app.services.capability_service import CapabilityService

router = APIRouter()


@router.get("/capabilities", response_model=CapabilitiesResponse, summary="Server capabilities")
async def get_capabilities(
    service: CapabilityService = Depends(deps.get_capability_service),
) -> CapabilitiesResponse:
    return service.get_capabilities()
