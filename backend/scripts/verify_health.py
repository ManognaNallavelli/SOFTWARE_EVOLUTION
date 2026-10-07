"""Verify health report generation and route classification."""

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
    user = await seed_user("health-user-a", "health@example.com", "Health User")
    session = await create_session(db, user, settings)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=300.0) as client:
        print("== Small repo health ==")
        await db.projects.delete_many({"owner_user_id": user, "github_full_name": "pypa/sampleproject"})
        r = await client.post(
            "/api/projects",
            json={
                "name": "Sample Health",
                "github_url": "https://github.com/pypa/sampleproject",
                "technologies": ["Python"],
            },
            cookies={cookie: session},
        )
        assert r.status_code == 201, r.text
        small = r.json()
        r = await client.post(f"/api/projects/{small['id']}/analyze", cookies={cookie: session})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed"
        assert body["analysis"] is not None
        assert body.get("health_report") is not None, body
        health = body["health_report"]
        assert health["overall_score"] is not None
        assert "categories" in health
        assert "architecture_overview" in health
        print("OK small overall", health["overall_score"], health["status"])

        print("== Flask health + route roles ==")
        await db.projects.delete_many({"owner_user_id": user, "github_full_name": "pallets/flask"})
        r = await client.post(
            "/api/projects",
            json={
                "name": "Flask Health",
                "github_url": "https://github.com/pallets/flask",
                "technologies": ["Python"],
            },
            cookies={cookie: session},
        )
        assert r.status_code == 201, r.text
        flask_proj = r.json()
        r = await client.post(
            f"/api/projects/{flask_proj['id']}/analyze",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        flask_body = r.json()
        assert flask_body["status"] == "completed", flask_body
        assert flask_body.get("health_report") is not None
        fh = flask_body["health_report"]
        assert fh["overall_score"] is not None
        assert fh["strengths"] is not None
        assert fh["recommendations"] is not None
        print("OK flask overall", fh["overall_score"], fh["status"])

        routes = flask_body["analysis"]["detections"]["api_routes"]
        roles = {r.get("code_role") for r in routes}
        print("route roles seen:", sorted(roles))
        for route in routes:
            path = route["file_path"].replace("\\", "/").lower()
            role = route.get("code_role")
            if "/tests/" in f"/{path}" or path.startswith("tests/"):
                assert role == "test", route
            if "/examples/" in f"/{path}" or path.startswith("examples/"):
                assert role == "example", route
        prod = [r for r in routes if r.get("code_role") == "production"]
        non_prod = [r for r in routes if r.get("code_role") in {"test", "example"}]
        assert flask_body["analysis"]["summary"].get("production_route_count", len(prod)) == len(
            [r for r in routes if r.get("code_role") == "production"]
        )
        print("OK classified routes prod", len(prod), "test/example", len(non_prod))
        assert fh["architecture_overview"]["test_or_example_route_count"] == len(non_prod)

        print("== Re-analyze refreshes health ==")
        before = fh["overall_score"]
        r = await client.post(
            f"/api/projects/{flask_proj['id']}/analyze",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        again = r.json()
        assert again.get("health_report") is not None
        assert again["health_report"]["overall_score"] is not None
        count = await db.repository_analyses.count_documents({"project_id": flask_proj["id"]})
        assert count == 1
        print("OK re-analyze score", again["health_report"]["overall_score"], "(was", before, ")")

        print("== Health endpoint ==")
        r = await client.get(f"/api/projects/{flask_proj['id']}/health", cookies={cookie: session})
        assert r.status_code == 200
        assert r.json().get("health_report") is not None
        print("OK /health")

        for pid in (small["id"], flask_proj["id"]):
            r = await client.delete(f"/api/projects/{pid}", cookies={cookie: session})
            assert r.status_code == 204

    print("\nHealth report verification passed.")
    await close_mongo()


if __name__ == "__main__":
    asyncio.run(run())
