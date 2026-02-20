"""
Task status router — kept for API compatibility.
Celery has been removed; this endpoint now maps task_id → analysis DB status.

The frontend should prefer GET /api/v1/analysis/{id}/status directly.
This endpoint accepts the analysis_id as the "task_id" for backward compat.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.models import AnalysisResult, User
from app.schemas.schemas import TaskStatusResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="Poll analysis status by analysis ID (Celery removed — uses DB status)",
)
async def get_task_status(
    task_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check the status of an analysis by its analysis_id.
    Maps DB statuses to the previous Celery vocabulary:
      pending  → PENDING
      running  → STARTED
      completed → SUCCESS
      failed   → FAILURE
    """
    try:
        analysis_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_id must be a valid UUID (the analysis_id).",
        )

    result = await db.execute(
        select(AnalysisResult)
        .join(User, AnalysisResult.user_id == User.id)
        .where(AnalysisResult.id == analysis_uuid, User.clerk_id == user_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or access denied.",
        )

    status_map = {
        "pending": "PENDING",
        "running": "STARTED",
        "completed": "SUCCESS",
        "failed": "FAILURE",
    }

    return TaskStatusResponse(
        task_id=task_id,
        status=status_map.get(analysis.status, "PENDING"),
        error=analysis.error_message if analysis.status == "failed" else None,
    )
