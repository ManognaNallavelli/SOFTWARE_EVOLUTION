"""Verify workspace APIs return real analysis data for Overview."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pymongo import ReturnDocument

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, get_db
from app.services.session_service import create_session


async def seed_user() -> str:
    db = get_db()
    now = datetime.now(timezone.utc)
    user = await db.users.find_one_and_update(
        {"google_sub": "workspace-shell-a"},
        {
            "$set": {
                "email": "workspace-shell@example.com",
                "name": "Workspace Shell",
                "picture": None,
                "updated_at": now,
            },
            "$setOnInsert": {"google_sub": "workspace-shell-a", "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return str(user["_id"])


async def run() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    cookie = settings.session_cookie_name
    user_id = await seed_user()
    session = await create_session(db, user_id, settings)

    await db.projects.delete_many(
        {"owner_user_id": user_id, "github_full_name": "pypa/sampleproject"}
    )

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=300.0) as client:
        health = await client.get("/api/health")
        assert health.status_code == 200, health.text
        print("OK health", health.json()["status"])

        created = await client.post(
            "/api/projects",
            json={
                "name": "Workspace Sample",
                "github_url": "https://github.com/pypa/sampleproject",
                "technologies": [],
            },
            cookies={cookie: session},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        print("OK create", project_id)

        analyzed = await client.post(
            f"/api/projects/{project_id}/analyze",
            cookies={cookie: session},
        )
        assert analyzed.status_code == 200, analyzed.text
        assert analyzed.json()["status"] == "completed", analyzed.text
        print("OK analyze")

        project = await client.get(f"/api/projects/{project_id}", cookies={cookie: session})
        assert project.status_code == 200, project.text
        body = project.json()
        assert isinstance(body.get("technologies"), list)
        print("OK project technologies", body["technologies"])

        analysis = await client.get(
            f"/api/projects/{project_id}/analysis",
            cookies={cookie: session},
        )
        assert analysis.status_code == 200, analysis.text
        doc = analysis.json()
        assert doc.get("analysis"), doc
        summary = doc["analysis"]["summary"]
        assert summary.get("total_files") is not None
        assert summary.get("symbol_count") is not None
        assert doc.get("health_report") is not None
        print(
            "OK overview fields",
            "files=",
            summary["total_files"],
            "symbols=",
            summary["symbol_count"],
            "health=",
            doc["health_report"].get("overall_score"),
            "langs=",
            len(summary.get("languages") or []),
        )

        deleted = await client.delete(
            f"/api/projects/{project_id}",
            cookies={cookie: session},
        )
        assert deleted.status_code in (200, 204), deleted.text
        print("OK delete")

    await close_mongo()
    print("ALL WORKSPACE API CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(run())
