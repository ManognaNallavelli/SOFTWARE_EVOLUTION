"""MongoDB connection and index setup."""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_mongo() -> AsyncIOMotorDatabase:
    global _client, _db
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    _db = _client[settings.mongodb_db]
    await _client.admin.command("ping")
    await ensure_indexes(_db)
    logger.info("Connected to MongoDB database '%s'", settings.mongodb_db)
    return _db


async def close_mongo() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
    logger.info("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("MongoDB is not connected")
    return _db


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.users.create_index("google_sub", unique=True)
    await db.sessions.create_index("session_id", unique=True)
    await db.sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.oauth_states.create_index("state", unique=True)
    await db.oauth_states.create_index("expires_at", expireAfterSeconds=0)
    await db.projects.create_index(
        [("owner_user_id", 1), ("github_repo_id", 1)],
        unique=True,
        name="owner_repo_unique",
    )
    await db.projects.create_index("owner_user_id")
    await db.repository_analyses.create_index("project_id", unique=True)
    await db.repository_analyses.create_index("owner_user_id")
    await db.architectures.create_index("project_id", unique=True)
    await db.architectures.create_index("owner_user_id")
    await db.rag_index_status.create_index("project_id", unique=True)
    await db.rag_index_status.create_index("owner_user_id")


def serialize_id(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    result = dict(document)
    if "_id" in result:
        result["id"] = str(result.pop("_id"))
    return result
