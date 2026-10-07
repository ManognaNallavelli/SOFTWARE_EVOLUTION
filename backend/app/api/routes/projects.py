"""Project management routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_current_user, get_owned_project_dep
from app.db.mongo import get_db
from app.schemas.project import ProjectCreateRequest, ProjectListResponse, ProjectPublic
from app.services.ownership import get_owned_project
from app.services.project_service import (
    create_project,
    delete_project,
    list_projects_for_user,
    project_to_public,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(user: dict[str, Any] = Depends(get_current_user)) -> ProjectListResponse:
    db = get_db()
    projects = await list_projects_for_user(db, user["id"])
    return ProjectListResponse(projects=[ProjectPublic(**p) for p in projects])


@router.post("", response_model=ProjectPublic, status_code=status.HTTP_201_CREATED)
async def create_project_route(
    payload: ProjectCreateRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ProjectPublic:
    db = get_db()
    project = await create_project(db, owner_user_id=user["id"], payload=payload)
    return ProjectPublic(**project)


@router.get("/{project_id}", response_model=ProjectPublic)
async def get_project(
    project: dict[str, Any] = Depends(get_owned_project_dep),
) -> ProjectPublic:
    return ProjectPublic(**project_to_public(project))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_route(
    project_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    db = get_db()
    await get_owned_project(db, project_id=project_id, user_id=user["id"])
    await delete_project(db, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
