"""Architecture generation routes (Phase 3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_owned_project_dep
from app.config import get_settings
from app.db.mongo import get_db
from app.schemas.architecture import ArchitectureDocumentResponse, ArchitectureGenerateResponse
from app.services.architecture_service import generate_project_architecture, get_architecture_document

router = APIRouter(prefix="/projects", tags=["architecture"])


@router.post("/{project_id}/architecture/generate", response_model=ArchitectureGenerateResponse)
async def generate_architecture(
    project: dict[str, Any] = Depends(get_owned_project_dep),
    deterministic: bool = Query(
        False,
        description="Force evidence-only layout (skip Gemini). Useful for offline demos.",
    ),
) -> ArchitectureGenerateResponse:
    db = get_db()
    settings = get_settings()
    return await generate_project_architecture(
        db,
        project=project,
        settings=settings,
        prefer_deterministic=deterministic,
    )


@router.get("/{project_id}/architecture", response_model=ArchitectureDocumentResponse)
async def get_architecture(
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> ArchitectureDocumentResponse:
    db = get_db()
    return await get_architecture_document(db, project["id"])
