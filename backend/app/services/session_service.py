"""MongoDB-backed server-side sessions and OAuth state."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings
from app.db.mongo import serialize_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_oauth_state(db: AsyncIOMotorDatabase) -> str:
    state = secrets.token_urlsafe(32)
    await db.oauth_states.insert_one(
        {
            "state": state,
            "created_at": _utcnow(),
            "expires_at": _utcnow() + timedelta(minutes=10),
        }
    )
    return state


async def consume_oauth_state(db: AsyncIOMotorDatabase, state: str | None) -> bool:
    if not state:
        return False
    result = await db.oauth_states.find_one_and_delete({"state": state})
    if result is None:
        return False
    expires_at = result.get("expires_at")
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at >= _utcnow()


async def create_session(db: AsyncIOMotorDatabase, user_id: str, settings: Settings) -> str:
    session_id = secrets.token_urlsafe(48)
    now = _utcnow()
    await db.sessions.insert_one(
        {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + timedelta(minutes=settings.session_expire_minutes),
        }
    )
    return session_id


async def get_session(db: AsyncIOMotorDatabase, session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    session = await db.sessions.find_one({"session_id": session_id})
    if session is None:
        return None
    expires_at = session.get("expires_at")
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < _utcnow():
        await db.sessions.delete_one({"session_id": session_id})
        return None
    return serialize_id(session)


async def delete_session(db: AsyncIOMotorDatabase, session_id: str | None) -> None:
    if not session_id:
        return
    await db.sessions.delete_one({"session_id": session_id})


def set_session_cookie(response: Response, session_id: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_expire_minutes * 60,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
    )
