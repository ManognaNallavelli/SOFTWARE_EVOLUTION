"""Verify URL-only project create + auto Detected Stack after analyze."""

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
from app.schemas.analysis import RepositoryAnalysisPayload
from app.services.session_service import create_session
from app.services.stack_detection import derive_detected_stack


async def seed_user(google_sub: str, email: str, name: str) -> str:
    db = get_db()
    now = datetime.now(timezone.utc)
    result = await db.users.find_one_and_update(
        {"google_sub": google_sub},
        {
            "$set": {"email": email, "name": name, "picture": None, "updated_at": now},
            "$setOnInsert": {"google_sub": google_sub, "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    assert result is not None
    return str(result["_id"])


async def run() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    cookie = settings.session_cookie_name
    user_id = await seed_user("dash-stack-a", "dash-stack@example.com", "Dash Stack")
    session = await create_session(db, user_id, settings)

    await db.projects.delete_many(
        {"owner_user_id": user_id, "github_full_name": "pallets/flask"}
    )

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=300.0) as client:
        print("== Health ==")
        r = await client.get("/api/health")
        assert r.status_code == 200, r.text
        print("OK", r.json()["status"], "mongo", r.json()["mongodb"])

        print("== Create with empty name + empty technologies ==")
        r = await client.post(
            "/api/projects",
            json={
                "name": "",
                "github_url": "https://github.com/pallets/flask",
                "technologies": [],
            },
            cookies={cookie: session},
        )
        assert r.status_code == 201, r.text
        project = r.json()
        project_id = project["id"]
        assert project["name"] == "flask", project
        assert project["technologies"] == [], project
        print("OK created id=", project_id, "name=", project["name"], "tech=", project["technologies"])

        print("== Analyze ==")
        r = await client.post(
            f"/api/projects/{project_id}/analyze",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        analyze = r.json()
        assert analyze.get("status") == "completed", analyze
        print("OK analyze status=", analyze["status"])

        print("== GET project technologies populated from analysis ==")
        r = await client.get(f"/api/projects/{project_id}", cookies={cookie: session})
        assert r.status_code == 200, r.text
        refreshed = r.json()
        techs = refreshed["technologies"]
        assert isinstance(techs, list) and len(techs) > 0, refreshed
        assert "Python" in techs, techs
        assert "Flask" in techs, techs
        assert "Markdown" not in techs and "Json" not in techs and "Toml" not in techs, techs
        print("OK technologies=", techs)

        analysis_doc = await db.repository_analyses.find_one({"project_id": project_id})
        assert analysis_doc and analysis_doc.get("analysis"), analysis_doc
        payload = RepositoryAnalysisPayload.model_validate(analysis_doc["analysis"])
        derived = derive_detected_stack(payload)
        assert refreshed["technologies"] == derived, (refreshed["technologies"], derived)
        print("OK persisted stack matches derive_detected_stack()", derived)

        print("== LIST includes stack ==")
        r = await client.get("/api/projects", cookies={cookie: session})
        assert r.status_code == 200, r.text
        listed = r.json()
        projects = listed.get("projects", listed if isinstance(listed, list) else [])
        match = next((p for p in projects if p["id"] == project_id), None)
        assert match is not None, listed
        assert match["technologies"] == techs, match
        print("OK list count=", len(projects), "match tech=", match["technologies"])

        print("== DELETE ==")
        r = await client.delete(f"/api/projects/{project_id}", cookies={cookie: session})
        assert r.status_code in (200, 204), r.text
        r = await client.get("/api/projects", cookies={cookie: session})
        projects_after = r.json().get("projects", [])
        assert all(p["id"] != project_id for p in projects_after)
        print("OK deleted")

    await close_mongo()
    print("\nALL DASHBOARD STACK CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(run())
