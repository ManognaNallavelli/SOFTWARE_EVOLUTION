"""User persistence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongo import serialize_id


async def upsert_google_user(
    db: AsyncIOMotorDatabase,
    *,
    google_sub: str,
    email: str,
    name: str,
    picture: str | None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"google_sub": google_sub},
        {
            "$set": {
                "email": email,
                "name": name,
                "picture": picture,
                "updated_at": now,
            },
            "$setOnInsert": {
                "google_sub": google_sub,
                "created_at": now,
            },
        },
        upsert=True,
    )
    user = await db.users.find_one({"google_sub": google_sub})
    serialized = serialize_id(user)
    assert serialized is not None
    return serialized


async def get_user_by_id(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(user_id):
        return None
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    return serialize_id(user)
