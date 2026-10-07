"""Regression tests: a failed clone must not leave the RAG index stuck in "indexing"."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.services import rag_service
from tests.conftest import SETTINGS, FakeCollection, FakeDB


class UpdatableCollection(FakeCollection):
    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update.get("$set") or {})
                return
        if upsert:
            doc = dict(query)
            doc.update(update.get("$setOnInsert") or {})
            doc.update(update.get("$set") or {})
            self.docs.append(doc)


PROJECT = {
    "id": "proj_clone_fail",
    "owner_user_id": "user_1",
    "normalized_github_url": "https://github.com/acme/chat-app",
}


@pytest.fixture
def db() -> FakeDB:
    fake = FakeDB()
    fake.rag_index_status = UpdatableCollection()
    return fake


def _failing_clone(**_: Any) -> Any:
    raise HTTPException(
        status_code=502,
        detail={"code": "clone_failed", "message": "Could not clone repository."},
    )


def _status(db: FakeDB) -> dict[str, Any]:
    doc = asyncio.run(db.rag_index_status.find_one({"project_id": PROJECT["id"]}))
    assert doc is not None
    return doc


def test_clone_failure_marks_index_failed(db: FakeDB, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag_service, "clone_public_repository", _failing_clone)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(rag_service.index_project_repository(db, project=PROJECT, settings=SETTINGS))

    assert caught.value.status_code == 502
    doc = _status(db)
    assert doc["status"] == "failed"
    assert doc["error_code"] == "clone_failed"
    assert doc["error"] == "Could not clone repository."


def test_retry_after_clone_failure_is_not_rejected(db: FakeDB, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag_service, "clone_public_repository", _failing_clone)
    with pytest.raises(HTTPException):
        asyncio.run(rag_service.index_project_repository(db, project=PROJECT, settings=SETTINGS))

    monkeypatch.setattr(
        rag_service, "clone_public_repository", lambda **_: SimpleNamespace(local_path="unused")
    )
    monkeypatch.setattr(
        rag_service,
        "chunk_repository",
        lambda **_: ([SimpleNamespace(text="def main(): pass")], 1),
    )
    monkeypatch.setattr(rag_service, "delete_project_chunks", lambda *_: None)
    monkeypatch.setattr(rag_service, "embed_texts", lambda texts, **_: [[0.0] for _ in texts])
    monkeypatch.setattr(rag_service, "upsert_chunks", lambda _settings, chunks, _emb: len(chunks))
    monkeypatch.setattr(rag_service, "cleanup_clone_path", lambda _path: None)

    result = asyncio.run(rag_service.index_project_repository(db, project=PROJECT, settings=SETTINGS))

    assert result.status == "ready"
    assert _status(db)["status"] == "ready"
