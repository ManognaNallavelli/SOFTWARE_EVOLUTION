"""Benchmark optimized Phase 4 RAG performance + auto-index."""

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
from app.rag.chroma_store import query_project_chunks
from app.rag.embedder import embed_texts
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


async def wait_ready(client: httpx.AsyncClient, cookie: str, session: str, pid: str, timeout: float = 600.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        r = await client.get(f"/api/projects/{pid}/rag/status", cookies={cookie: session})
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] == "ready":
            return body
        if body["status"] == "failed":
            raise AssertionError(f"auto-index failed: {body}")
        await asyncio.sleep(2.0)
    raise TimeoutError("RAG indexing did not become ready in time")


async def run() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    cookie = settings.session_cookie_name
    user = await seed_user("rag-opt-user", "rag-opt@example.com", "RAG Opt")
    session = await create_session(db, user, settings)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=900.0) as client:
        print("== Create FastAPI template project ==")
        await db.projects.delete_many(
            {"owner_user_id": user, "github_full_name": "fastapi/full-stack-fastapi-template"}
        )
        r = await client.post(
            "/api/projects",
            json={
                "name": "FastAPI RAG Perf",
                "github_url": "https://github.com/fastapi/full-stack-fastapi-template",
                "technologies": ["Python", "TypeScript"],
            },
            cookies={cookie: session},
        )
        assert r.status_code == 201, r.text
        pid = r.json()["id"]

        print("== Analyze (should auto-start RAG index) ==")
        t_analyze = time.perf_counter()
        r = await client.post(f"/api/projects/{pid}/analyze", cookies={cookie: session})
        analyze_s = time.perf_counter() - t_analyze
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"
        assert "RAG indexing" in (r.json().get("message") or "")
        print(f"analyze_s={analyze_s:.2f}")

        print("== Wait for auto-index ready ==")
        t_auto = time.perf_counter()
        status = await wait_ready(client, cookie, session, pid)
        auto_wait_s = time.perf_counter() - t_auto
        print(
            f"auto_index_wait_s={auto_wait_s:.2f} files={status['file_count']} "
            f"chunks={status['chunk_count']} message={status.get('message')}"
        )
        doc = await db.rag_index_status.find_one({"project_id": pid})
        timings = (doc or {}).get("timings") or {}
        print("index_phase_timings", {k: round(float(v), 3) for k, v in timings.items()})

        print("== Manual re-index timing ==")
        t_re = time.perf_counter()
        r = await client.post(f"/api/projects/{pid}/rag/index", cookies={cookie: session})
        reindex_s = time.perf_counter() - t_re
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ready"
        print(
            f"reindex_s={reindex_s:.2f} files={body['file_count']} chunks={body['chunk_count']}"
        )
        doc = await db.rag_index_status.find_one({"project_id": pid})
        timings = (doc or {}).get("timings") or {}
        print("reindex_phase_timings", {k: round(float(v), 3) for k, v in timings.items()})

        print("== Retrieval timing ==")
        t_ret = time.perf_counter()
        vectors = embed_texts(["What backend framework is used?"], model_name=settings.embedding_model_name)
        rows = query_project_chunks(settings, project_id=pid, query_embedding=vectors[0], top_k=4)
        retrieve_s = time.perf_counter() - t_ret
        assert rows
        assert all(row["metadata"]["project_id"] == pid for row in rows)
        print(f"retrieve_s={retrieve_s:.2f} hits={len(rows)}")

        print("== Chat timing ==")
        t_chat = time.perf_counter()
        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "What backend framework does this project use?"},
            cookies={cookie: session},
        )
        chat_total_s = time.perf_counter() - t_chat
        assert r.status_code == 200, r.text
        chat = r.json()
        assert chat["answer"]
        print(f"chat_total_s={chat_total_s:.2f} sources={len(chat['sources'])}")
        print("answer_preview:", chat["answer"][:160].replace("\n", " "))

        # Warm second chat (model keep_alive)
        t_chat2 = time.perf_counter()
        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "Where is the FastAPI app created?"},
            cookies={cookie: session},
        )
        chat2_s = time.perf_counter() - t_chat2
        assert r.status_code == 200, r.text
        print(f"chat2_warm_s={chat2_s:.2f} sources={len(r.json().get('sources') or [])}")

        await client.delete(f"/api/projects/{pid}", cookies={cookie: session})
        print("Phase 4 optimization benchmark passed.")

    await close_mongo()


if __name__ == "__main__":
    asyncio.run(run())
