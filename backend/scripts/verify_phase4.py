"""Verify Phase 4 RAG indexing + chat with project isolation."""

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
from app.rag.chroma_store import count_project_chunks, query_project_chunks
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


async def run() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    cookie = settings.session_cookie_name

    user_a = await seed_user("rag-user-a", "rag-a@example.com", "RAG A")
    user_b = await seed_user("rag-user-b", "rag-b@example.com", "RAG B")
    session_a = await create_session(db, user_a, settings)
    session_b = await create_session(db, user_b, settings)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=900.0) as client:
        print("== Create FastAPI full-stack template project ==")
        await db.projects.delete_many(
            {"owner_user_id": user_a, "github_full_name": "fastapi/full-stack-fastapi-template"}
        )
        r = await client.post(
            "/api/projects",
            json={
                "name": "FastAPI Full Stack RAG",
                "github_url": "https://github.com/fastapi/full-stack-fastapi-template",
                "technologies": ["Python", "TypeScript"],
            },
            cookies={cookie: session_a},
        )
        assert r.status_code == 201, r.text
        project = r.json()
        pid = project["id"]

        print("== Chat before index => 409 ==")
        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "What framework is used?"},
            cookies={cookie: session_a},
        )
        assert r.status_code == 409, r.text

        print("== Index repository (may take several minutes) ==")
        r = await client.post(f"/api/projects/{pid}/rag/index", cookies={cookie: session_a})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ready", body
        assert body["chunk_count"] > 0, body
        assert body["file_count"] > 0, body
        first_count = body["chunk_count"]
        print("OK indexed files", body["file_count"], "chunks", first_count)

        print("== Status endpoint ==")
        r = await client.get(f"/api/projects/{pid}/rag/status", cookies={cookie: session_a})
        assert r.status_code == 200, r.text
        status_body = r.json()
        assert status_body["status"] == "ready"
        assert status_body["chunk_count"] == first_count

        print("== Re-index does not duplicate ==")
        r = await client.post(f"/api/projects/{pid}/rag/index", cookies={cookie: session_a})
        assert r.status_code == 200, r.text
        re_body = r.json()
        assert re_body["status"] == "ready"
        chroma_count = count_project_chunks(settings, pid)
        assert chroma_count == re_body["chunk_count"], (chroma_count, re_body["chunk_count"])
        # Allow small variance across re-clones but should be same ballpark / exact after delete+upsert
        print("OK re-index chunks", re_body["chunk_count"], "chroma", chroma_count)

        print("== Retrieval is project-filtered ==")
        vectors = embed_texts(["FastAPI backend routes"], model_name=settings.embedding_model_name)
        rows = query_project_chunks(settings, project_id=pid, query_embedding=vectors[0], top_k=5)
        assert rows, "expected retrieval hits"
        for row in rows:
            assert row["metadata"]["project_id"] == pid
        # foreign project id must return empty
        foreign = query_project_chunks(
            settings,
            project_id="000000000000000000000000",
            query_embedding=vectors[0],
            top_k=5,
        )
        assert foreign == []
        print("OK retrieval hits", len(rows))

        print("== Chat with sources ==")
        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "What backend framework does this project use? Cite a file if possible."},
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        chat = r.json()
        assert chat["answer"]
        assert isinstance(chat["sources"], list)
        print("OK answer preview:", chat["answer"][:180].replace("\n", " "))
        print("OK sources", len(chat["sources"]))
        if chat["sources"]:
            print(" first source", chat["sources"][0]["file_path"], chat["sources"][0].get("start_line"))

        def assert_impl_sources(label: str, sources: list) -> None:
            assert sources, f"{label}: expected retrieved sources"
            paths = [str(s.get("file_path") or "").lower() for s in sources]
            weak_markers = ("readme", "/.github/", "/workflows/", ".md", "contributing")
            strong = [
                path
                for path in paths
                if not any(marker in path for marker in weak_markers)
            ]
            assert strong, f"{label}: expected implementation sources, got {paths}"
            print(f"OK {label} sources", paths[:4])

        print("== Grounded implementation questions ==")
        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "Where is authentication implemented?"},
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        auth_chat = r.json()
        assert auth_chat["answer"]
        assert_impl_sources("authentication", auth_chat["sources"])
        assert "readme" not in (auth_chat["sources"][0]["file_path"] or "").lower()

        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "How does the frontend communicate with the backend API?"},
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        api_chat = r.json()
        assert api_chat["answer"]
        assert_impl_sources("frontend-backend", api_chat["sources"])

        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "Which files handle database access?"},
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        db_chat = r.json()
        assert db_chat["answer"]
        assert_impl_sources("database access", db_chat["sources"])

        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "Is Redis used in this project?"},
            cookies={cookie: session_a},
        )
        assert r.status_code == 200, r.text
        redis_chat = r.json()
        answer_l = (redis_chat["answer"] or "").lower()
        assert "no evidence of redis" in answer_l or (
            "redis" in answer_l and "not" in answer_l and "found" in answer_l
        ), redis_chat["answer"]
        assert redis_chat.get("context_insufficient") is False
        print("OK redis absence answer:", redis_chat["answer"][:180].replace("\n", " "))

        print("== Ownership isolation ==")
        r = await client.get(f"/api/projects/{pid}/rag/status", cookies={cookie: session_b})
        assert r.status_code in {403, 404}, r.text
        r = await client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "hello"},
            cookies={cookie: session_b},
        )
        assert r.status_code in {403, 404}, r.text

        print("== Unauthenticated rejected ==")
        r = await client.post(f"/api/projects/{pid}/rag/index")
        assert r.status_code == 401, r.text

        await client.delete(f"/api/projects/{pid}", cookies={cookie: session_a})
        remaining = count_project_chunks(settings, pid)
        assert remaining == 0, remaining
        print("Phase 4 RAG verification passed.")

    await close_mongo()


if __name__ == "__main__":
    asyncio.run(run())
