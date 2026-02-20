"""Analysis router — start analysis, check status, fetch results, list history, export, delete."""

from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.models import AnalysisResult, Dataset, User
from app.schemas.schemas import (
    AnalysisHistoryItem,
    AnalysisResultResponse,
    AnalysisStartRequest,
    AnalysisStartResponse,
    AnalysisStatusResponse,
)
from app.tasks.analysis_tasks import run_analysis_pipeline

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/analysis", tags=["Analysis"])

# Thread pool for CPU-bound graph analysis (keeps uvicorn event loop free)
_executor = ThreadPoolExecutor(max_workers=4)


@router.post(
    "/start",
    response_model=AnalysisStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the analysis pipeline for a dataset",
)
async def start_analysis(
    body: AnalysisStartRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kick off the graph analysis pipeline as a FastAPI background task."""
    result = await db.execute(
        select(Dataset)
        .join(User, Dataset.user_id == User.id)
        .where(Dataset.id == body.dataset_id, User.clerk_id == user_id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found or access denied.",
        )

    user_result = await db.execute(select(User).where(User.clerk_id == user_id))
    user = user_result.scalar_one()

    analysis = AnalysisResult(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=user.id,
        status="pending",
    )
    db.add(analysis)
    dataset.status = "analyzing"
    await db.flush()

    analysis_id = str(analysis.id)
    dataset_id = str(dataset.id)

    logger.info("analysis_started", analysis_id=analysis_id, dataset_id=dataset_id)

    # Run the heavy computation in a separate thread so the event loop stays free
    background_tasks.add_task(
        _run_in_thread, run_analysis_pipeline, analysis_id, dataset_id
    )

    return AnalysisStartResponse(analysis_id=analysis.id)


def _run_in_thread(fn, *args):
    """Run a synchronous function in the thread pool executor."""
    loop = asyncio.new_event_loop()
    try:
        fn(*args)
    finally:
        loop.close()


@router.get(
    "/{analysis_id}/status",
    response_model=AnalysisStatusResponse,
    summary="Check analysis status",
)
async def get_analysis_status(
    analysis_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    return AnalysisStatusResponse(
        analysis_id=analysis.id,
        status=analysis.status,
        error_message=analysis.error_message,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


@router.get(
    "/{analysis_id}/export",
    summary="Export full structured analysis result (suspicious_accounts + fraud_rings + summary)",
)
async def export_analysis(
    analysis_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the pre-computed structured output that was stored in stats_json
    during the analysis pipeline. This avoids re-running build_structured_output
    on an edge-less graph which would produce empty fraud_rings.

    Output format:
    {
        "suspicious_accounts": [...],
        "fraud_rings": [...],
        "summary": { "total_accounts_analyzed": N, ... }
    }
    """
    result = await db.execute(
        select(AnalysisResult)
        .join(User, AnalysisResult.user_id == User.id)
        .where(AnalysisResult.id == analysis_id, User.clerk_id == user_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found or access denied.")
    if analysis.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Analysis not complete. Status: {analysis.status}")
    if not analysis.stats_json:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Structured data not available.")

    stats_raw = json.loads(analysis.stats_json)

    # stats_json is written by run_analysis_pipeline as:
    #   { total_nodes, total_edges, ..., **build_structured_output(...) }
    # so suspicious_accounts, fraud_rings, and summary are already there,
    # computed against the FULL graph with all edges intact.
    structured = {
        "suspicious_accounts": stats_raw.get("suspicious_accounts", []),
        "fraud_rings": stats_raw.get("fraud_rings", []),
        "summary": stats_raw.get("summary", {
            "total_accounts_analyzed": stats_raw.get("total_nodes", 0),
            "suspicious_accounts_flagged": 0,
            "fraud_rings_detected": 0,
            "processing_time_seconds": 0.0,
        }),
    }

    return JSONResponse(content=structured)


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResultResponse,
    summary="Fetch analysis result",
)
async def get_analysis(
    analysis_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnalysisResult)
        .join(User, AnalysisResult.user_id == User.id)
        .where(AnalysisResult.id == analysis_id, User.clerk_id == user_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found or access denied.")
    return AnalysisResultResponse(
        analysis_id=analysis.id,
        dataset_id=analysis.dataset_id,
        status=analysis.status,
        graph_data=json.loads(analysis.graph_json) if analysis.graph_json else None,
        risk_data=json.loads(analysis.risk_json) if analysis.risk_json else None,
        flags=json.loads(analysis.flags_json) if analysis.flags_json else None,
        stats=json.loads(analysis.stats_json) if analysis.stats_json else None,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


@router.get(
    "",
    response_model=list[AnalysisHistoryItem],
    summary="List analysis history for the current user",
)
async def list_analyses(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnalysisResult, Dataset.filename, Dataset.row_count)
        .join(Dataset, AnalysisResult.dataset_id == Dataset.id)
        .join(User, AnalysisResult.user_id == User.id)
        .where(User.clerk_id == user_id)
        .order_by(AnalysisResult.created_at.desc())
    )
    rows = result.all()
    return [
        AnalysisHistoryItem(
            id=analysis.id,
            dataset_id=analysis.dataset_id,
            filename=filename,
            status=analysis.status,
            row_count=row_count,
            stats=json.loads(analysis.stats_json) if analysis.stats_json else None,
            created_at=analysis.created_at,
            completed_at=analysis.completed_at,
        )
        for analysis, filename, row_count in rows
    ]


@router.delete(
    "/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an analysis and its parent dataset",
)
async def delete_analysis(
    analysis_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnalysisResult)
        .join(User, AnalysisResult.user_id == User.id)
        .where(AnalysisResult.id == analysis_id, User.clerk_id == user_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found or access denied.")

    dataset_id = analysis.dataset_id
    await db.delete(analysis)

    ds_result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = ds_result.scalar_one_or_none()
    if dataset:
        await db.delete(dataset)

    logger.info("analysis_deleted", analysis_id=str(analysis_id))
    return None
