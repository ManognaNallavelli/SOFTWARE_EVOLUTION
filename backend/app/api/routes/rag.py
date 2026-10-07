"""RAG indexing and project chat routes (Phase 4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_owned_project_dep
from app.config import get_settings
from app.db.mongo import get_db
from app.schemas.rag import ChatRequest, ChatResponse, RagIndexResponse, RagStatusResponse
from app.services.rag_service import chat_with_project, get_rag_status, index_project_repository

router = APIRouter(prefix="/projects", tags=["rag"])


@router.post("/{project_id}/rag/index", response_model=RagIndexResponse)
async def index_repository(
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> RagIndexResponse:
    db = get_db()
    settings = get_settings()
    return await index_project_repository(db, project=project, settings=settings)


@router.get("/{project_id}/rag/status", response_model=RagStatusResponse)
async def rag_status(
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> RagStatusResponse:
    db = get_db()
    return await get_rag_status(db, project["id"])


@router.post("/{project_id}/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> ChatResponse:
    db = get_db()
    settings = get_settings()
    return await chat_with_project(
        db,
        project=project,
        message=body.message,
        context=body.context,
        settings=settings,
    )
