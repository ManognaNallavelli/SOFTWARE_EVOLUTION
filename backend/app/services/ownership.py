"""Ownership helpers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.project_service import get_project_document


async def get_owned_project(
    db: AsyncIOMotorDatabase,
    *,
    project_id: str,
    user_id: str,
) -> dict[str, Any]:
    project = await get_project_document(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "project_not_found", "message": "Project not found."},
        )
    if project.get("owner_user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "forbidden",
                "message": "You do not have access to this project.",
            },
        )
    return project
