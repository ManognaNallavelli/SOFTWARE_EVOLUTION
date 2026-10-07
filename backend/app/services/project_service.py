"""Project CRUD with ownership and duplicate prevention."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.db.mongo import serialize_id
from app.schemas.project import ProjectCreateRequest
from app.services.github_service import normalize_github_url, validate_public_github_repository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def project_to_public(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["id"],
        "owner_user_id": document["owner_user_id"],
        "name": document["name"],
        "github_url": document["github_url"],
        "normalized_github_url": document["normalized_github_url"],
        "github_repo_id": document["github_repo_id"],
        "github_full_name": document.get("github_full_name", ""),
        "technologies": document.get("technologies", []),
        "description": document.get("description"),
        "status": document["status"],
        "last_error": document.get("last_error"),
        "last_error_code": document.get("last_error_code"),
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
    }


async def list_projects_for_user(db: AsyncIOMotorDatabase, user_id: str) -> list[dict[str, Any]]:
    cursor = db.projects.find({"owner_user_id": user_id}).sort("created_at", -1)
    projects: list[dict[str, Any]] = []
    async for doc in cursor:
        serialized = serialize_id(doc)
        if serialized:
            projects.append(project_to_public(serialized))
    return projects


async def get_project_document(db: AsyncIOMotorDatabase, project_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(project_id):
        return None
    doc = await db.projects.find_one({"_id": ObjectId(project_id)})
    return serialize_id(doc)


async def create_project(
    db: AsyncIOMotorDatabase,
    *,
    owner_user_id: str,
    payload: ProjectCreateRequest,
) -> dict[str, Any]:
    parsed = normalize_github_url(payload.github_url)

    existing_by_url = await db.projects.find_one(
        {
            "owner_user_id": owner_user_id,
            "normalized_github_url": parsed.normalized_url,
        }
    )
    if existing_by_url is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_repository",
                "message": "You already connected this GitHub repository.",
                "existing_project_id": str(existing_by_url["_id"]),
            },
        )

    validated = await validate_public_github_repository(payload.github_url)

    existing = await db.projects.find_one(
        {
            "owner_user_id": owner_user_id,
            "github_repo_id": validated.github_repo_id,
        }
    )
    if existing is not None:
        existing_id = str(existing["_id"])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_repository",
                "message": "You already connected this GitHub repository.",
                "existing_project_id": existing_id,
            },
        )

    now = _utcnow()
    project_name = payload.name.strip() or validated.repo
    document = {
        "owner_user_id": owner_user_id,
        "name": project_name,
        "github_url": payload.github_url.strip(),
        "normalized_github_url": validated.normalized_url,
        "github_repo_id": validated.github_repo_id,
        "github_full_name": validated.full_name,
        "github_default_branch": validated.default_branch,
        # Technologies come from repository analysis after Analyze — not user entry.
        "technologies": [],
        "description": payload.description,
        "status": "created",
        "last_error": None,
        "last_error_code": None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        result = await db.projects.insert_one(document)
    except DuplicateKeyError as exc:
        race = await db.projects.find_one(
            {
                "owner_user_id": owner_user_id,
                "github_repo_id": validated.github_repo_id,
            }
        )
        existing_id = str(race["_id"]) if race else ""
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_repository",
                "message": "You already connected this GitHub repository.",
                "existing_project_id": existing_id,
            },
        ) from exc

    created = await get_project_document(db, str(result.inserted_id))
    assert created is not None
    return project_to_public(created)


async def delete_project(db: AsyncIOMotorDatabase, project_id: str) -> None:
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await db.projects.delete_one({"_id": ObjectId(project_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    await db.repository_analyses.delete_one({"project_id": project_id})
    await db.architectures.delete_one({"project_id": project_id})
    from app.config import get_settings
    from app.services.clone_service import cleanup_project_clone
    from app.services.rag_service import delete_project_rag

    settings = get_settings()
    cleanup_project_clone(settings, project_id)
    await delete_project_rag(settings, db, project_id)
