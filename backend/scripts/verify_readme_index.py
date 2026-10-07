"""Re-index Axios from a local clone and verify README retrieval."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, get_db
from app.rag.chroma_store import delete_project_chunks, get_collection, upsert_chunks
from app.rag.chunker import chunk_repository
from app.rag.embedder import embed_texts
from app.rag.retriever import classify_question, retrieve_context
from app.services.session_service import create_session

PID = "6a9e7da97e0e3a69aa5da609"
OWNER = "6a9d718f8ea8fc33df3af7aa"
REPO = Path(os.environ["TEMP"]) / "ase_readme_verify_axios"


async def main() -> None:
    print("repo", REPO, "exists", REPO.exists(), "readme", (REPO / "README.md").exists())
    assert REPO.exists() and (REPO / "README.md").exists()

    settings = get_settings()
    await connect_mongo()
    db = get_db()
    analysis_doc = await db.repository_analyses.find_one({"project_id": PID})
    symbols = []
    if analysis_doc and analysis_doc.get("analysis"):
        symbols = list((analysis_doc["analysis"] or {}).get("symbols") or [])

    print("chunking...")
    chunks, file_count = chunk_repository(
        project_id=PID,
        repo_root=REPO,
        analysis_symbols=symbols,
    )
    md_files = sorted(
        {
            c.file_path
            for c in chunks
            if c.file_path.lower().endswith((".md", ".markdown", ".rst"))
            or c.file_path.lower().startswith("readme")
        }
    )
    print("files", file_count, "chunks", len(chunks), "md files", md_files)
    assert any(p.replace("\\", "/").lower() == "readme.md" for p in md_files), md_files

    print("embedding/upsert...")
    delete_project_chunks(settings, PID)
    embeddings = embed_texts(
        [c.text for c in chunks],
        model_name=settings.embedding_model_name,
        batch_size=64,
    )
    stored = upsert_chunks(settings, chunks, embeddings)
    now = datetime.now(timezone.utc)
    await db.rag_index_status.update_one(
        {"project_id": PID},
        {
            "$set": {
                "project_id": PID,
                "status": "ready",
                "chunk_count": stored,
                "file_count": file_count,
                "indexed_at": now,
                "updated_at": now,
                "error": None,
                "error_code": None,
                "embedding_model": settings.embedding_model_name,
                "message": f"Repository indexed for RAG chat ({file_count} files, {stored} chunks).",
            }
        },
        upsert=True,
    )
    print("stored", stored)

    col = get_collection(settings)
    res = col.get(where={"project_id": PID}, include=["metadatas"], limit=800)
    paths = sorted({(m or {}).get("file_path", "") for m in (res.get("metadatas") or [])})
    print("chroma md", [p for p in paths if str(p).lower().endswith(".md")])
    assert any(str(p).replace("\\", "/").lower() == "readme.md" for p in paths)

    for q in (
        "What is the purpose of this project?",
        "What technologies are used in this project?",
    ):
        rows = retrieve_context(settings, project_id=PID, question=q, top_k=6)
        sp = [str((r.get("metadata") or {}).get("file_path")) for r in rows]
        print("retrieve", classify_question(q), sp)
        assert any("readme.md" in p.lower() or "package.json" in p.lower() for p in sp), sp

    session = await create_session(db, OWNER, settings)
    cookie = settings.session_cookie_name
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=180.0) as client:
        for q in (
            "What is the purpose of this project?",
            "What technologies are used in this project?",
        ):
            r = await client.post(
                f"/api/projects/{PID}/chat",
                json={"message": q},
                cookies={cookie: session},
            )
            assert r.status_code == 200, r.text
            data = r.json()
            sources = [s.get("file_path") for s in data.get("sources") or []]
            print("CHAT", q)
            print(" sources", sources)
            print(" answer", (data.get("answer") or "")[:260])
            assert "no evidence was found" not in (data.get("answer") or "").lower()
            if "purpose" in q.lower():
                assert any("readme.md" in (s or "").lower() for s in sources), sources

    await close_mongo()
    print("README INDEX + RETRIEVAL OK")


if __name__ == "__main__":
    asyncio.run(main())
