"""Phase 2 verification: clone, analyze, authz, re-analyze."""

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

    user_a = await seed_user("phase2-user-a", "phase2a@example.com", "Phase2 A")
    user_b = await seed_user("phase2-user-b", "phase2b@example.com", "Phase2 B")
    session_a = await create_session(db, user_a, settings)
    session_b = await create_session(db, user_b, settings)

    # Clean prior test projects for Hello-World
    await db.projects.delete_many(
        {
            "owner_user_id": {"$in": [user_a, user_b]},
            "github_full_name": "octocat/Hello-World",
        }
    )

    base = "http://127.0.0.1:8000"
    async with httpx.AsyncClient(base_url=base, timeout=180.0) as client:
        print("== Unauthenticated analyze ==")
        r = await client.post("/api/projects/000000000000000000000000/analyze")
        assert r.status_code == 401, r.text
        print("OK 401")

        print("== Create project A ==")
        r = await client.post(
            "/api/projects",
            json={
                "name": "Hello World Analysis",
                "github_url": "https://github.com/octocat/Hello-World",
                "technologies": ["Git"],
                "description": "Phase 2 test",
            },
            cookies={cookie: session_a},
        )
        assert r.status_code == 201, r.text
        project_a = r.json()
        assert project_a["status"] == "created"
        print("OK", project_a["id"])

        print("== Analyze project A ==")
        r = await client.post(
            f"/api/projects/{project_a['id']}/analyze",
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed", body
        assert body["analysis"] is not None
        analysis = body["analysis"]
        assert analysis["summary"]["total_files"] >= 1
        assert any(f["path"] for f in analysis["files"])
        # .git should not appear as analyzed file paths
        assert all(not f["path"].startswith(".git/") for f in analysis["files"])
        print(
            "OK files",
            analysis["summary"]["total_files"],
            "langs",
            [l["language"] for l in analysis["summary"]["languages"]],
        )

        print("== GET analysis ==")
        r = await client.get(
            f"/api/projects/{project_a['id']}/analysis",
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        stored = r.json()
        assert stored["status"] == "completed"
        assert stored["analysis"]["summary"]["total_files"] == analysis["summary"]["total_files"]
        print("OK stored")

        print("== Re-analyze updates same document ==")
        before = await db.repository_analyses.count_documents({"project_id": project_a["id"]})
        r = await client.post(
            f"/api/projects/{project_a['id']}/analyze",
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        after = await db.repository_analyses.count_documents({"project_id": project_a["id"]})
        assert before == after == 1
        print("OK single analysis doc")

        print("== Create project B same repo ==")
        r = await client.post(
            "/api/projects",
            json={
                "name": "Hello World B",
                "github_url": "https://github.com/octocat/Hello-World.git",
                "technologies": [],
            },
            cookies={cookie: session_b},
        )
        assert r.status_code == 201, r.text
        project_b = r.json()

        print("== Authz: B cannot read A analysis ==")
        r = await client.get(
            f"/api/projects/{project_a['id']}/analysis",
            cookies={cookie: session_b},
        )
        assert r.status_code == 403, r.text
        print("OK 403")

        print("== Authz: B cannot analyze A ==")
        r = await client.post(
            f"/api/projects/{project_a['id']}/analyze",
            cookies={cookie: session_b},
        )
        assert r.status_code == 403, r.text
        print("OK 403")

        print("== Invalid/nonexistent repo fails cleanly ==")
        r = await client.post(
            "/api/projects",
            json={
                "name": "Missing Repo",
                "github_url": "https://github.com/this-org-should-not-exist-xyz/no-repo-abc-999",
                "technologies": [],
            },
            cookies={cookie: session_a},
        )
        # create itself validates and should 404 before insert
        assert r.status_code == 404, r.text
        print("OK create rejected missing repo")

        # cleanup
        for pid, sess in ((project_a["id"], session_a), (project_b["id"], session_b)):
            r = await client.delete(f"/api/projects/{pid}", cookies={cookie: sess})
            assert r.status_code == 204, r.text

        print("== Analyze small Python public repo ==")
        await db.projects.delete_many(
            {
                "owner_user_id": user_a,
                "github_full_name": "pypa/sampleproject",
            }
        )
        r = await client.post(
            "/api/projects",
            json={
                "name": "Sampleproject Analysis",
                "github_url": "https://github.com/pypa/sampleproject",
                "technologies": ["Python"],
            },
            cookies={cookie: session_a},
        )
        assert r.status_code == 201, r.text
        py_project = r.json()
        r = await client.post(
            f"/api/projects/{py_project['id']}/analyze",
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        py_body = r.json()
        assert py_body["status"] == "completed", py_body
        py_analysis = py_body["analysis"]
        assert any(lang["language"] == "python" for lang in py_analysis["summary"]["languages"])
        assert py_analysis["summary"]["symbol_count"] >= 1
        assert py_analysis["summary"]["import_count"] >= 1
        print(
            "OK python repo symbols",
            py_analysis["summary"]["symbol_count"],
            "imports",
            py_analysis["summary"]["import_count"],
        )
        r = await client.delete(
            f"/api/projects/{py_project['id']}",
            cookies={cookie: session_a},
        )
        assert r.status_code == 204

    print("== Local Python AST smoke ==")
    from app.analyzers.python_ast import analyze_python_source

    sample = analyze_python_source(
        "app/demo.py",
        "import os\n\nclass Demo:\n    def run(self):\n        return 1\n\ndef helper():\n    return 2\n",
    )
    assert any(s.name == "Demo" and s.type == "class" for s in sample.symbols)
    assert any(s.name == "helper" and s.type == "function" for s in sample.symbols)
    assert any(i.imported_module == "os" for i in sample.imports)
    print("OK python symbols/imports")

    print("\nAll Phase 2 automated checks passed.")
    await close_mongo()


if __name__ == "__main__":
    asyncio.run(run())
