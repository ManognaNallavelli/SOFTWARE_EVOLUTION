"""Verify auto-analyze flow + unique Chroma chunk IDs for Axios and a second repo."""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pymongo import ReturnDocument

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, get_db
from app.rag.chroma_store import count_project_chunks
from app.services.session_service import create_session

REPOS = [
    ("axios/axios", "https://github.com/axios/axios", "Axios Verify"),
    ("sindresorhus/is", "https://github.com/sindresorhus/is", "Is Type Verify"),
]


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


async def wait_ready(
    client: httpx.AsyncClient,
    cookie: str,
    session: str,
    pid: str,
    timeout: float = 900.0,
) -> dict:
    deadline = time.perf_counter() + timeout
    last = None
    while time.perf_counter() < deadline:
        r = await client.get(f"/api/projects/{pid}/rag/status", cookies={cookie: session})
        assert r.status_code == 200, r.text
        last = r.json()
        status = last.get("status")
        print(f"  rag status={status} message={last.get('message')!r}")
        if status == "ready":
            return last
        if status == "failed":
            raise AssertionError(f"RAG indexing failed: {last}")
        await asyncio.sleep(3.0)
    raise TimeoutError(f"RAG not ready in time: {last}")


async def exercise_repo(
    client: httpx.AsyncClient,
    db,
    *,
    cookie: str,
    session: str,
    user_id: str,
    full_name: str,
    github_url: str,
    name: str,
) -> str:
    print(f"\n== {full_name}: create ==")
    await db.projects.delete_many({"owner_user_id": user_id, "github_full_name": full_name})
    r = await client.post(
        "/api/projects",
        json={"name": name, "github_url": github_url, "technologies": []},
        cookies={cookie: session},
    )
    assert r.status_code == 201, r.text
    project = r.json()
    pid = project["id"]
    assert project["status"] in {"created", "pending", "not_analyzed"}, project
    print(f"  created id={pid} status={project['status']}")

    print(f"== {full_name}: analyze (same pipeline workspace auto-starts) ==")
    r = await client.post(f"/api/projects/{pid}/analyze", cookies={cookie: session})
    assert r.status_code == 200, r.text
    analysis = r.json()
    assert analysis["status"] == "completed", analysis
    assert analysis.get("analysis"), "missing analysis payload"
    print(f"  analysis completed; auto RAG message={analysis.get('message')!r}")

    print(f"== {full_name}: wait for auto RAG index ==")
    status = await wait_ready(client, cookie, session, pid)
    assert status["chunk_count"] > 0, status
    chroma = count_project_chunks(get_settings(), pid)
    assert chroma == status["chunk_count"], (chroma, status["chunk_count"])
    print(f"  READY chunks={status['chunk_count']} files={status.get('file_count')}")

    print(f"== {full_name}: assistant chat ==")
    r = await client.post(
        f"/api/projects/{pid}/chat",
        json={"message": "What is the main purpose of this repository?"},
        cookies={cookie: session},
    )
    assert r.status_code == 200, r.text
    chat = r.json()
    assert chat.get("answer"), chat
    print(f"  chat ok ({len(chat['answer'])} chars)")
    return pid


async def run() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    cookie = settings.session_cookie_name
    user = await seed_user("auto-analyze-verify", "auto-analyze@example.com", "Auto Analyze")
    session = await create_session(db, user, settings)

    pids: list[str] = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=1200.0) as client:
        for full_name, url, name in REPOS:
            pid = await exercise_repo(
                client,
                db,
                cookie=cookie,
                session=session,
                user_id=user,
                full_name=full_name,
                github_url=url,
                name=name,
            )
            pids.append(pid)

        print("\n== Cleanup test projects ==")
        for pid in pids:
            r = await client.delete(f"/api/projects/{pid}", cookies={cookie: session})
            assert r.status_code == 204, r.text
            print(f"  deleted {pid}")

    await close_mongo()
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(run())
