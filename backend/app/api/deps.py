"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.db.mongo import get_db
from app.services.auth_service import get_user_by_id
from app.services.ownership import get_owned_project
from app.services.session_service import get_session


async def get_current_user(request: Request) -> dict[str, Any]:
    settings = get_settings()
    db = get_db()
    session_id = request.cookies.get(settings.session_cookie_name)
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "Authentication required."},
        )

    user = await get_user_by_id(db, session["user_id"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "Authentication required."},
        )
    return user


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    settings = get_settings()
    db = get_db()
    session_id = request.cookies.get(settings.session_cookie_name)
    session = await get_session(db, session_id)
    if session is None:
        return None
    return await get_user_by_id(db, session["user_id"])


async def get_owned_project_dep(
    project_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    db = get_db()
    return await get_owned_project(db, project_id=project_id, user_id=user["id"])


def require_settings() -> Settings:
    return get_settings()
