"""Live retrieval quality checks against the indexed Axios project."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, get_db
from app.rag.retriever import classify_question, retrieve_context
from app.services.session_service import create_session

PID = "6a9e7da97e0e3a69aa5da609"
OWNER = "6a9d718f8ea8fc33df3af7aa"

QUESTIONS = [
    "What is the purpose of this project?",
    "Explain the backend architecture.",
    "What are AxiosHeaders, AxiosError, and InterceptorManager, and where are they used?",
    "Where are the API/request adapters implemented?",
    "Does this project use Redis?",
]


def _paths(rows: list[dict]) -> list[str]:
    return [str((r.get("metadata") or {}).get("file_path") or "") for r in rows]


async def run() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    session = await create_session(db, OWNER, settings)
    cookie = settings.session_cookie_name

    print("== Offline retrieve_context checks ==")
    for q in QUESTIONS:
        intent = classify_question(q)
        rows = retrieve_context(settings, project_id=PID, question=q, top_k=5)
        paths = _paths(rows)
        print(f"\nQ: {q}\n  intent={intent}\n  paths={paths}")

        if intent == "overview":
            joined = " ".join(p.lower() for p in paths)
            assert "readme.md" in joined or "package.json" in joined, paths
            assert not paths[0].lower().startswith("docs/"), paths
        if "AxiosHeaders" in q:
            joined = " ".join(p.lower() for p in paths) + " " + " ".join(
                str(r.get("document") or "").lower() for r in rows
            )
            assert "axiosheaders" in joined or "axioserror" in joined, paths
            assert any(
                token in joined
                for token in ("import", "require", "from './", 'from "./', "axioserror", "interceptormanager")
            ), paths
        if "adapter" in q.lower():
            joined = " ".join(p.lower() for p in paths)
            assert "adapter" in joined, paths

    print("\n== Live chat checks ==")
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=180.0) as client:
        for q in QUESTIONS:
            r = await client.post(
                f"/api/projects/{PID}/chat",
                json={"message": q},
                cookies={cookie: session},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            answer = body.get("answer") or ""
            sources = [s.get("file_path") for s in body.get("sources") or []]
            print(f"\nQ: {q}\n  sources={sources}\n  answer={answer[:280]!r}")

            if "purpose" in q.lower():
                src = " ".join(s.lower() for s in sources if s)
                assert "readme.md" in src or src.strip().startswith("package.json") or " package.json" in f" {src}"
                assert sources[0].lower() in {"readme.md", "package.json"} or "readme" in sources[0].lower()
                assert not sources[0].lower().startswith("docs/"), sources
                assert any(m in answer.lower() for m in ("http client", "promise", "axios")), answer
            if "architecture" in q.lower():
                assert any(
                    "adapter" in (s or "").lower() or "core" in (s or "").lower() for s in sources
                ), sources
                assert not answer.lower().startswith("no evidence"), answer
                assert "adapter" in answer.lower() or "core" in answer.lower() or "axios" in answer.lower(), answer
            if "redis" in q.lower():
                assert "no evidence of redis" in answer.lower(), answer
            if "AxiosHeaders" in q:
                joined_src = " ".join((s or "").lower() for s in sources)
                assert any(
                    token in joined_src
                    for token in ("axiosheaders", "axioserror", "interceptor", "axios.js", "index.d.ts")
                ), (sources, answer)

    await close_mongo()
    print("\nLIVE RETRIEVAL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(run())
