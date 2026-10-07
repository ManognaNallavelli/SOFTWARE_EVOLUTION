"""ChromaDB persistence for repository chunks (vectors only)."""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

from app.config import Settings
from app.rag.chunker import CodeChunk

logger = logging.getLogger(__name__)

COLLECTION_NAME = "ase_repo_chunks"
_client_lock = threading.Lock()
_client = None


def resolve_chroma_dir(settings: Settings) -> Path:
    configured = (settings.chroma_persist_dir or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = Path.cwd() / path
    else:
        path = Path(tempfile.gettempdir()) / "ase_chroma"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def get_chroma_client(settings: Settings):
    global _client
    with _client_lock:
        if _client is None:
            import chromadb

            persist = str(resolve_chroma_dir(settings))
            logger.info("Opening Chroma persistent client at %s", persist)
            _client = chromadb.PersistentClient(path=persist)
        return _client


def get_collection(settings: Settings):
    client = get_chroma_client(settings)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def delete_project_chunks(settings: Settings, project_id: str) -> None:
    collection = get_collection(settings)
    try:
        collection.delete(where={"project_id": project_id})
    except Exception:  # noqa: BLE001
        # Older empty collections may not support delete-where the same way
        logger.exception("Failed deleting Chroma chunks for project %s", project_id)


def upsert_chunks(
    settings: Settings,
    chunks: list[CodeChunk],
    embeddings: list[list[float]],
) -> int:
    if not chunks:
        return 0
    if len(chunks) != len(embeddings):
        raise ValueError("chunks/embeddings length mismatch")

    collection = get_collection(settings)
    all_ids = [c.chunk_id for c in chunks]
    if len(all_ids) != len(set(all_ids)):
        dupes = sorted({cid for cid in all_ids if all_ids.count(cid) > 1})
        raise ValueError(
            f"Duplicate chunk IDs before Chroma upsert ({len(dupes)} unique collisions). "
            f"Examples: {dupes[:5]}"
        )

    # Larger batches reduce Chroma round-trips for typical repo sizes.
    batch_size = 200
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        vectors = embeddings[i : i + batch_size]
        ids = [c.chunk_id for c in batch]
        documents = [c.text for c in batch]
        metadatas: list[dict[str, Any]] = []
        for c in batch:
            meta: dict[str, Any] = {
                "project_id": c.project_id,
                "file_path": c.file_path,
                "start_line": int(c.start_line),
                "end_line": int(c.end_line),
            }
            if c.language:
                meta["language"] = c.language
            if c.symbol:
                meta["symbol"] = c.symbol
            metadatas.append(meta)
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=vectors)
        total += len(batch)
    return total


def query_project_chunks(
    settings: Settings,
    *,
    project_id: str,
    query_embedding: list[float],
    top_k: int = 6,
) -> list[dict[str, Any]]:
    collection = get_collection(settings)
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"project_id": project_id},
        include=["documents", "metadatas", "distances"],
    )
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    ids = (result.get("ids") or [[]])[0]

    rows: list[dict[str, Any]] = []
    for idx, doc in enumerate(documents):
        meta = metadatas[idx] if idx < len(metadatas) else {}
        # Hard guard against cross-project leakage even if filter misbehaves
        if str(meta.get("project_id") or "") != project_id:
            continue
        distance = distances[idx] if idx < len(distances) else None
        score = None if distance is None else max(0.0, 1.0 - float(distance))
        rows.append(
            {
                "id": ids[idx] if idx < len(ids) else None,
                "document": doc,
                "metadata": meta,
                "score": score,
            }
        )
    return rows


def get_project_chunks_for_files(
    settings: Settings,
    *,
    project_id: str,
    file_paths: list[str],
    limit: int = 400,
) -> list[dict[str, Any]]:
    """Fetch stored chunks for specific files of one project (no embedding query)."""
    wanted = sorted({p for p in file_paths if p})
    if not wanted:
        return []
    collection = get_collection(settings)
    result = collection.get(
        where={"$and": [{"project_id": project_id}, {"file_path": {"$in": wanted}}]},
        include=["documents", "metadatas"],
        limit=limit,
    )
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    wanted_set = set(wanted)
    rows: list[dict[str, Any]] = []
    for idx, chunk_id in enumerate(ids):
        meta = (metadatas[idx] if idx < len(metadatas) else None) or {}
        if str(meta.get("project_id") or "") != project_id:
            continue
        if str(meta.get("file_path") or "") not in wanted_set:
            continue
        rows.append(
            {
                "id": chunk_id,
                "document": documents[idx] if idx < len(documents) else "",
                "metadata": meta,
                "score": None,
            }
        )
    return rows


def count_project_chunks(settings: Settings, project_id: str) -> int:
    collection = get_collection(settings)
    try:
        result = collection.get(where={"project_id": project_id}, include=[])
        return len(result.get("ids") or [])
    except Exception:  # noqa: BLE001
        logger.exception("count_project_chunks failed for %s", project_id)
        return 0
