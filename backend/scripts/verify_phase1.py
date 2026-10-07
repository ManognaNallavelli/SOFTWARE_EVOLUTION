"""Phase 1 verification helpers (no Google browser flow)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import HTTPException
from pymongo import ReturnDocument

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, get_db
from app.services.github_service import normalize_github_url, validate_public_github_repository
from app.services.session_service import create_session


async def seed_user(google_sub: str, email: str, name: str) -> str:
    db = get_db()
    now = datetime.now(timezone.utc)
    result = await db.users.find_one_and_update(
        {"google_sub": google_sub},
        {
            "$set": {
                "email": email,
                "name": name,
                "picture": None,
                "updated_at": now,
            },
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

    print("== URL normalization ==")
    urls = [
        "https://github.com/octocat/Hello-World",
        "https://github.com/octocat/Hello-World/",
        "https://github.com/octocat/Hello-World.git",
    ]
    norms = [normalize_github_url(u).normalized_url for u in urls]
    assert len(set(norms)) == 1, norms
    print("OK", norms[0])

    print("== Public repo validation ==")
    validated = await validate_public_github_repository("https://github.com/octocat/Hello-World.git")
    print("OK", validated.github_repo_id, validated.full_name)

    print("== Invalid URL ==")
    try:
        normalize_github_url("https://gitlab.com/foo/bar")
        raise AssertionError("expected failure")
    except HTTPException as exc:
        print("OK rejected", exc.detail)

    print("== Seed users & sessions ==")
    user_a = await seed_user("phase1-test-user-a", "a@example.com", "User A")
    user_b = await seed_user("phase1-test-user-b", "b@example.com", "User B")
    session_a = await create_session(db, user_a, settings)
    session_b = await create_session(db, user_b, settings)
    print("OK users", user_a, user_b)

    # Clean prior test projects for these users + flask repo
    await db.projects.delete_many(
        {
            "owner_user_id": {"$in": [user_a, user_b]},
            "github_repo_id": validated.github_repo_id,
        }
    )

    base = "http://127.0.0.1:8000"
    cookie_name = settings.session_cookie_name

    async with httpx.AsyncClient(base_url=base, timeout=90.0) as client:
        print("== Unauthenticated /api/projects ==")
        r = await client.get("/api/projects")
        assert r.status_code == 401, r.text
        print("OK 401")

        print("== /api/auth/me anonymous ==")
        r = await client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["authenticated"] is False
        print("OK")

        print("== Create project as User A ==")
        r = await client.post(
            "/api/projects",
            json={
                "name": "Hello World Study",
                "github_url": "https://github.com/octocat/Hello-World",
                "technologies": ["Git"],
                "description": "Phase 1 test",
            },
            cookies={cookie_name: session_a},
        )
        assert r.status_code == 201, r.text
        project_a = r.json()
        print("OK", project_a["id"], project_a["github_repo_id"])

        print("== Duplicate equivalents for User A ==")
        for url in [
            "https://github.com/octocat/Hello-World/",
            "https://github.com/octocat/Hello-World.git",
            "https://github.com/octocat/Hello-World",
        ]:
            r = await client.post(
                "/api/projects",
                json={"name": "Dup", "github_url": url, "technologies": []},
                cookies={cookie_name: session_a},
            )
            assert r.status_code == 409, (url, r.text)
            body = r.json()["detail"]
            assert body["code"] == "duplicate_repository"
            assert body["existing_project_id"] == project_a["id"]
        print("OK duplicates rejected")

        print("== User B can connect same repo ==")
        r = await client.post(
            "/api/projects",
            json={
                "name": "Hello World Study B",
                "github_url": "https://github.com/octocat/Hello-World.git",
                "technologies": ["Git"],
            },
            cookies={cookie_name: session_b},
        )
        assert r.status_code == 201, r.text
        project_b = r.json()
        print("OK", project_b["id"])

        print("== Authorization: A cannot read B ==")
        r = await client.get(
            f"/api/projects/{project_b['id']}",
            cookies={cookie_name: session_a},
        )
        assert r.status_code == 403, r.text
        print("OK 403 get")

        print("== Authorization: A cannot delete B ==")
        r = await client.delete(
            f"/api/projects/{project_b['id']}",
            cookies={cookie_name: session_a},
        )
        assert r.status_code == 403, r.text
        print("OK 403 delete")

        print("== List projects scoped to owner ==")
        r = await client.get("/api/projects", cookies={cookie_name: session_a})
        assert r.status_code == 200
        ids = {p["id"] for p in r.json()["projects"]}
        assert project_a["id"] in ids
        assert project_b["id"] not in ids
        print("OK list isolation")

        print("== Logout ==")
        r = await client.post("/api/auth/logout", cookies={cookie_name: session_a})
        assert r.status_code == 200
        r = await client.get("/api/projects", cookies={cookie_name: session_a})
        assert r.status_code == 401
        print("OK logout invalidates session")

        # cleanup B project with still-valid session
        r = await client.delete(
            f"/api/projects/{project_b['id']}",
            cookies={cookie_name: session_b},
        )
        assert r.status_code == 204, r.text
        # recreate session for A cleanup if needed
        session_a2 = await create_session(db, user_a, settings)
        r = await client.delete(
            f"/api/projects/{project_a['id']}",
            cookies={cookie_name: session_a2},
        )
        assert r.status_code == 204, r.text
        print("OK cleanup")

    print("== Non-existent repo ==")
    try:
        await validate_public_github_repository(
            "https://github.com/this-org-should-not-exist-xyz/no-repo-abc-999"
        )
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404
        print("OK", exc.detail)

    print("\nAll Phase 1 automated checks passed.")
    await close_mongo()


if __name__ == "__main__":
    asyncio.run(run())
