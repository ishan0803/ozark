"""Network router — isomorphism search and graph retrieval."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.models import AnalysisResult, User
from app.schemas.schemas import IsomorphismRequest, IsomorphismResultResponse
from app.tasks.analysis_tasks import run_isomorphism_search

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/network", tags=["Network"])


@router.post(
    "/isomorphism",
    response_model=IsomorphismResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Run VF2 isomorphism search (synchronous, returns result directly)",
)
async def start_isomorphism(
    body: IsomorphismRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run the VF2 isomorphism search in a thread pool and return the result
    immediately. No polling needed — this replaces the old Celery-based flow.
    """
    result = await db.execute(
        select(AnalysisResult)
        .join(User, AnalysisResult.user_id == User.id)
        .where(
            AnalysisResult.id == body.analysis_id,
            AnalysisResult.status == "completed",
            User.clerk_id == user_id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed analysis not found or access denied.",
        )

    logger.info(
        "isomorphism_dispatched",
        analysis_id=str(analysis.id),
        target_node=body.target_node,
        hops=body.hops,
    )

    # Run the CPU-bound search in the thread pool (non-blocking)
    iso_result = await run_in_threadpool(
        run_isomorphism_search,
        str(analysis.id),
        str(analysis.dataset_id),
        body.target_node,
        body.hops,
    )

    return IsomorphismResultResponse(**iso_result)


@router.get(
    "/graph/{analysis_id}",
    summary="Get the full graph payload for visualization",
)
async def get_graph(
    analysis_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full D3-ready graph + risk data for a completed analysis."""
    result = await db.execute(
        select(AnalysisResult)
        .join(User, AnalysisResult.user_id == User.id)
        .where(AnalysisResult.id == analysis_id, User.clerk_id == user_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or access denied.",
        )

    if analysis.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis is not complete yet. Current status: {analysis.status}",
        )

    return {
        "graph": json.loads(analysis.graph_json) if analysis.graph_json else None,
        "risk": json.loads(analysis.risk_json) if analysis.risk_json else None,
        "stats": json.loads(analysis.stats_json) if analysis.stats_json else None,
    }
