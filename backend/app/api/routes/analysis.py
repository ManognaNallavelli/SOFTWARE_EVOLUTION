"""Repository analysis routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import get_owned_project_dep
from app.config import get_settings
from app.db.mongo import get_db
from app.schemas.analysis import AnalysisDocumentResponse, AnalyzeAcceptedResponse
from app.services.analysis_service import get_analysis_document, run_project_analysis
from app.services.rag_service import schedule_auto_index

router = APIRouter(prefix="/projects", tags=["analysis"])


@router.post("/{project_id}/analyze", response_model=AnalyzeAcceptedResponse)
async def analyze_project(
    background_tasks: BackgroundTasks,
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> AnalyzeAcceptedResponse:
    db = get_db()
    settings = get_settings()
    result = await run_project_analysis(db, project=project, settings=settings)
    if result.status == "completed":
        background_tasks.add_task(schedule_auto_index, project=project, settings=settings)
        message = "Repository analysis completed. RAG indexing started in the background."
    else:
        message = result.error or "Analysis finished with errors."
    return AnalyzeAcceptedResponse(
        project_id=result.project_id,
        status=result.status,
        message=message,
        analysis=result.analysis,
        health_report=result.health_report,
        health_error=result.health_error,
        error=result.error,
        error_code=result.error_code,
        analyzed_at=result.analyzed_at,
        updated_at=result.updated_at,
    )


@router.get("/{project_id}/analysis", response_model=AnalysisDocumentResponse)
async def get_project_analysis(
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> AnalysisDocumentResponse:
    db = get_db()
    return await get_analysis_document(db, project["id"])


@router.get("/{project_id}/health", response_model=AnalysisDocumentResponse)
async def get_project_health(
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> AnalysisDocumentResponse:
    """Return analysis document emphasizing health_report (same ownership rules)."""
    db = get_db()
    return await get_analysis_document(db, project["id"])
