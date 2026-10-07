"""Verify Gemini chat + architecture primary/fallback model behavior."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
from pymongo import ReturnDocument

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.architecture.deterministic import build_deterministic_architecture
from app.architecture.gemini_client import GeminiArchitectureError, generate_architecture_graph
from app.architecture.prompt_builder import build_architecture_brief, build_gemini_prompt
from app.architecture.validator import validate_architecture_graph
from app.config import Settings, get_settings
from app.db.mongo import close_mongo, connect_mongo, get_db
from app.rag.gemini_chat_client import GeminiChatError, generate_chat_answer
from app.rag.prompts import build_rag_prompt
from app.schemas.analysis import RepositoryAnalysisPayload
from app.services.session_service import create_session


def _settings_override(**kwargs: str) -> Settings:
    base = get_settings()
    data = base.model_dump()
    data.update(kwargs)
    return Settings(**data)


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


async def test_chat_models(settings: Settings) -> None:
    print("== Chatbot primary success ==")
    answer, model = await generate_chat_answer(
        settings=settings,
        prompt=build_rag_prompt(
            question="Reply with exactly: ok",
            contexts=[
                {
                    "document": "This is a tiny FastAPI health route example.",
                    "metadata": {"file_path": "app/main.py", "start_line": 1, "end_line": 5},
                }
            ],
        ),
    )
    assert answer.strip(), answer
    assert model == settings.gemini_chat_model, (model, settings.gemini_chat_model)
    print("OK chat primary", model, "len", len(answer))

    print("== Chatbot forced primary failure -> fallback success ==")
    bad_primary = _settings_override(
        gemini_chat_model="gemini-this-model-does-not-exist-xyz",
        gemini_chat_fallback_model=settings.gemini_chat_fallback_model,
    )
    answer2, model2 = await generate_chat_answer(
        settings=bad_primary,
        prompt=build_rag_prompt(
            question="Reply with exactly: ok",
            contexts=[
                {
                    "document": "This is a tiny FastAPI health route example.",
                    "metadata": {"file_path": "app/main.py", "start_line": 1, "end_line": 5},
                }
            ],
        ),
    )
    assert answer2.strip(), answer2
    assert model2 == settings.gemini_chat_fallback_model, (model2, settings.gemini_chat_fallback_model)
    print("OK chat fallback", model2, "len", len(answer2))


async def test_architecture_models(settings: Settings, analysis: RepositoryAnalysisPayload) -> None:
    brief = build_architecture_brief(analysis)
    prompt = build_gemini_prompt(brief)

    print("== Architecture primary success ==")
    graph, model = await generate_architecture_graph(prompt=prompt, settings=settings)
    assert graph.nodes, graph
    assert model == settings.gemini_model, (model, settings.gemini_model)
    validated = validate_architecture_graph(graph, analysis)
    assert validated.nodes
    print("OK architecture primary", model, "nodes", len(validated.nodes))

    print("== Architecture forced primary failure -> fallback success ==")
    bad_primary = _settings_override(
        gemini_model="gemini-this-model-does-not-exist-xyz",
        gemini_architecture_fallback_model=settings.gemini_architecture_fallback_model,
    )
    graph2, model2 = await generate_architecture_graph(prompt=prompt, settings=bad_primary)
    assert graph2.nodes, graph2
    assert model2 == settings.gemini_architecture_fallback_model, (
        model2,
        settings.gemini_architecture_fallback_model,
    )
    print("OK architecture fallback", model2, "nodes", len(graph2.nodes))

    print("== Deterministic fallback still works ==")
    det = build_deterministic_architecture(analysis)
    det_validated = validate_architecture_graph(det, analysis)
    assert det_validated.nodes
    print("OK deterministic", "nodes", len(det_validated.nodes))


async def ensure_analyzed_project(
    client: httpx.AsyncClient,
    cookie: str,
    session: str,
    user_id: str,
) -> str:
    db = get_db()
    await db.projects.delete_many(
        {"owner_user_id": user_id, "github_full_name": "pallets/flask"}
    )
    r = await client.post(
        "/api/projects",
        json={
            "name": "Gemini Fallback Flask",
            "github_url": "https://github.com/pallets/flask",
            "technologies": ["Python"],
        },
        cookies={cookie: session},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    r = await client.post(f"/api/projects/{pid}/analyze", cookies={cookie: session})
    assert r.status_code == 200, r.text
    return pid


async def ensure_chat_ready_project(
    client: httpx.AsyncClient,
    cookie: str,
    session: str,
    user_id: str,
) -> str:
    """Prefer an already-ready RAG project; otherwise index the FastAPI template."""
    db = get_db()
    existing = await db.projects.find_one(
        {"owner_user_id": user_id, "github_full_name": "fastapi/full-stack-fastapi-template"}
    )
    if existing is None:
        r = await client.post(
            "/api/projects",
            json={
                "name": "Gemini Fallback FastAPI",
                "github_url": "https://github.com/fastapi/full-stack-fastapi-template",
                "technologies": ["Python", "TypeScript"],
            },
            cookies={cookie: session},
        )
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
    else:
        pid = str(existing["_id"])

    status = await client.get(f"/api/projects/{pid}/rag/status", cookies={cookie: session})
    assert status.status_code == 200, status.text
    body = status.json()
    if body.get("status") == "ready" and int(body.get("chunk_count") or 0) > 0:
        return pid

    r = await client.post(f"/api/projects/{pid}/rag/index", cookies={cookie: session})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready", r.text
    return pid


async def run() -> None:
    settings = get_settings()
    assert settings.gemini_api_key.strip(), "GEMINI_API_KEY required for this verification"

    print("Config:")
    print("  architecture primary ", settings.gemini_model)
    print("  architecture fallback", settings.gemini_architecture_fallback_model)
    print("  chat primary         ", settings.gemini_chat_model)
    print("  chat fallback        ", settings.gemini_chat_fallback_model)

    await test_chat_models(settings)

    await connect_mongo()
    db = get_db()
    cookie = settings.session_cookie_name
    user = await seed_user("gemini-fallback-a", "gemini-fallback@example.com", "Gemini Fallback")
    session = await create_session(db, user, settings)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=300.0) as client:
        print("== Backend health / startup ==")
        r = await client.get("/api/health")
        assert r.status_code == 200, r.text
        health = r.json()
        assert "ollama" not in health, health
        assert health.get("gemini") == "configured", health
        print("OK health", health["status"], "gemini", health["gemini"])

        print("== Ensure analyzed project for architecture ==")
        arch_pid = await ensure_analyzed_project(client, cookie, session, user)

        analysis_doc = await db.repository_analyses.find_one({"project_id": arch_pid})
        assert analysis_doc and analysis_doc.get("analysis"), analysis_doc
        analysis = RepositoryAnalysisPayload.model_validate(analysis_doc["analysis"])

        await test_architecture_models(settings, analysis)

        print("== API architecture generate ==")
        r = await client.post(
            f"/api/projects/{arch_pid}/architecture/generate",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        arch = r.json()
        assert arch["status"] == "completed", arch
        assert arch["source"] in {"gemini", "deterministic"}, arch
        if arch["source"] == "gemini":
            assert arch.get("gemini_model") in {
                settings.gemini_model,
                settings.gemini_architecture_fallback_model,
            }, arch
        print("OK api architecture source", arch["source"], "model", arch.get("gemini_model"))

        print("== API deterministic still works ==")
        r = await client.post(
            f"/api/projects/{arch_pid}/architecture/generate?deterministic=true",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        det = r.json()
        assert det["source"] == "deterministic", det
        assert det.get("graph") and det["graph"].get("nodes"), det
        print("OK api deterministic nodes", len(det["graph"]["nodes"]))

        print("== API chat (Gemini path) ==")
        chat_pid = await ensure_chat_ready_project(client, cookie, session, user)
        r = await client.post(
            f"/api/projects/{chat_pid}/chat",
            json={"message": "What is this repository about in one short sentence?"},
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        chat = r.json()
        assert chat.get("answer"), chat
        assert chat.get("model") in {
            settings.gemini_chat_model,
            settings.gemini_chat_fallback_model,
        }, chat
        print("OK api chat model", chat["model"], "sources", len(chat.get("sources") or []))

    await close_mongo()
    print("ALL GEMINI FALLBACK CHECKS PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        print("FAILED:", exc)
        raise
