"""Route-level authorization for the chat endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import rag as rag_routes
from app.main import app
from app.services import rag_service
from tests.conftest import FakeDB, seed_project


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, fake_db: FakeDB):
    monkeypatch.setattr(deps, "get_db", lambda: fake_db)
    monkeypatch.setattr(rag_routes, "get_db", lambda: fake_db)
    current_user: dict[str, Any] = {"id": "owner"}
    app.dependency_overrides[deps.get_current_user] = lambda: current_user
    try:
        yield TestClient(app), current_user
    finally:
        app.dependency_overrides.clear()


def test_chat_on_another_users_project_is_forbidden(client, fake_db: FakeDB, monkeypatch) -> None:
    test_client, user = client
    project = seed_project(fake_db, owner_user_id="owner")
    called: list[Any] = []

    async def spy(*args: Any, **kwargs: Any) -> None:
        called.append(kwargs)

    monkeypatch.setattr(rag_routes, "chat_with_project", spy)
    user["id"] = "intruder"
    response = test_client.post(
        f"/api/projects/{project['id']}/chat", json={"message": "What issues were detected?"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
    assert called == [], "chat service must not run for a non-owner"


def test_non_owner_with_workspace_context_is_still_forbidden(client, fake_db: FakeDB, monkeypatch) -> None:
    test_client, user = client
    project = seed_project(fake_db, owner_user_id="owner")
    called: list[Any] = []

    async def spy(*args: Any, **kwargs: Any) -> None:
        called.append(kwargs)

    monkeypatch.setattr(rag_routes, "chat_with_project", spy)
    user["id"] = "intruder"
    response = test_client.post(
        f"/api/projects/{project['id']}/chat",
        json={
            "message": "Explain this component",
            "context": {"page": "architecture", "architecture_node_id": "data_layer"},
        },
    )
    assert response.status_code == 403
    assert called == []


def test_invalid_workspace_context_is_rejected(client, fake_db: FakeDB) -> None:
    test_client, _user = client
    project = seed_project(fake_db, owner_user_id="owner")
    response = test_client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "Explain this", "context": {"page": "settings"}},
    )
    assert response.status_code == 422


def test_owner_context_is_passed_and_applied(client, fake_db: FakeDB, monkeypatch) -> None:
    test_client, _user = client
    project = seed_project(fake_db, owner_user_id="owner")

    async def fake_generate(*, settings, prompt):
        return "It reads and writes MongoDB [A1].", "fake-model"

    monkeypatch.setattr(rag_service, "generate_chat_answer", fake_generate)
    monkeypatch.setattr(rag_service, "retrieve_context", lambda *a, **k: [])
    monkeypatch.setattr(rag_service, "retrieve_supporting_chunks", lambda *a, **k: [])
    response = test_client.post(
        f"/api/projects/{project['id']}/chat",
        json={
            "message": "Explain this component",
            "context": {"page": "architecture", "architecture_node_id": "data_layer"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["context_applied"] == "Architecture component: Data access"
    assert body["analysis_findings"][0]["title"].startswith("Selected architecture component: Data access")


def test_chat_on_unknown_project_is_not_found(client) -> None:
    test_client, _user = client
    response = test_client.post(
        f"/api/projects/{ObjectId()}/chat", json={"message": "What issues were detected?"}
    )
    assert response.status_code == 404


def test_owner_receives_analysis_findings(client, fake_db: FakeDB, monkeypatch) -> None:
    test_client, _user = client
    project = seed_project(fake_db, owner_user_id="owner")

    async def fake_generate(*, settings, prompt):
        return "Testing is the main issue [A2].", "fake-model"

    monkeypatch.setattr(rag_service, "generate_chat_answer", fake_generate)
    response = test_client.post(
        f"/api/projects/{project['id']}/chat", json={"message": "What issues were detected?"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == project["id"]
    assert [f["id"] for f in body["analysis_findings"]] == ["A2"]
    assert body["analysis_findings"][0]["kind"] == "health_issue"
