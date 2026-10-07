"""Shared fixtures: an in-memory Mongo stand-in and realistic stored analysis documents."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bson import ObjectId

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.architecture.deterministic import build_deterministic_architecture  # noqa: E402
from app.architecture.validator import validate_architecture_graph  # noqa: E402
from app.config import Settings  # noqa: E402
from app.rag import retriever  # noqa: E402
from app.schemas.analysis import (  # noqa: E402
    AnalysisDetections,
    AnalysisFile,
    AnalysisImport,
    AnalysisRepositoryInfo,
    AnalysisRoute,
    AnalysisSummary,
    AnalysisSymbol,
    LanguageCount,
    RepositoryAnalysisPayload,
)
from app.services import rag_service  # noqa: E402
from app.services.health_engine import build_health_report  # noqa: E402

ANALYZED_AT = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        self.queries.append(dict(query))
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        self.docs.append(doc)
        return doc


class FakeDB:
    def __init__(self) -> None:
        self.projects = FakeCollection()
        self.repository_analyses = FakeCollection()
        self.architectures = FakeCollection()
        self.rag_index_status = FakeCollection()


def _file(path: str, language: str | None, size: int, category: str, role: str = "production") -> AnalysisFile:
    ext = Path(path).suffix
    return AnalysisFile(path=path, language=language, size=size, extension=ext, category=category, code_role=role)


def build_payload(project_id: str, *, repo_name: str = "acme/chat-app") -> RepositoryAnalysisPayload:
    files = [
        _file("backend/app/main.py", "python", 1800, "source"),
        _file("backend/app/api/routes/rag.py", "python", 1400, "api"),
        _file("backend/app/services/rag_service.py", "python", 22000, "service"),
        _file("backend/app/db/mongo.py", "python", 2100, "data_access"),
        _file("backend/requirements.txt", None, 300, "dependency_manifest", "config"),
        _file("frontend/package.json", "json", 900, "dependency_manifest", "config"),
        _file("frontend/src/services/ragService.ts", "typescript", 600, "service"),
        _file("frontend/src/components/ChatPanel.tsx", "typescript", 9000, "frontend_component"),
        _file("examples/demo.py", "python", 400, "example", "example"),
        _file("README.md", "markdown", 1500, "docs", "documentation"),
        _file(".env", None, 120, "config", "config"),
    ]
    symbols = [
        AnalysisSymbol(
            name="chat_with_project",
            type="function",
            file_path="backend/app/services/rag_service.py",
            start_line=356,
            end_line=420,
        ),
        AnalysisSymbol(name="chat", type="function", file_path="backend/app/api/routes/rag.py", start_line=35, end_line=47),
        AnalysisSymbol(name="ProjectChatPanel", type="function", file_path="frontend/src/components/ChatPanel.tsx", start_line=46),
    ]
    imports = [
        AnalysisImport(
            source_file="backend/app/api/routes/rag.py",
            imported_module="app.services.rag_service",
            names=["chat_with_project", "get_rag_status"],
            line=13,
        ),
        AnalysisImport(source_file="backend/app/main.py", imported_module="app.api.routes", names=["rag"], line=9),
        AnalysisImport(source_file="backend/app/services/rag_service.py", imported_module="app.config", names=["Settings"], line=14),
        AnalysisImport(
            source_file="backend/app/db/mongo.py",
            imported_module="motor.motor_asyncio",
            names=["AsyncIOMotorClient"],
            line=8,
        ),
        AnalysisImport(
            source_file="frontend/src/components/ChatPanel.tsx",
            imported_module="../services/ragService",
            names=["chatWithProject"],
            line=5,
        ),
    ]
    routes = [
        AnalysisRoute(
            file_path="backend/app/api/routes/rag.py",
            function="chat",
            method="POST",
            path="/{project_id}/chat",
            line=35,
            evidence="python_decorator",
            code_role="production",
        ),
        AnalysisRoute(
            file_path="backend/app/api/routes/rag.py",
            function="rag_status",
            method="GET",
            path="/{project_id}/rag/status",
            line=27,
            evidence="python_decorator",
            code_role="production",
        ),
        AnalysisRoute(
            file_path="examples/demo.py",
            function="demo",
            method="GET",
            path="/demo",
            line=4,
            evidence="python_decorator",
            code_role="example",
        ),
    ]
    summary = AnalysisSummary(
        total_files=len(files),
        total_directories=9,
        languages=[
            LanguageCount(language="python", file_count=5, total_bytes=27700),
            LanguageCount(language="typescript", file_count=2, total_bytes=9600),
            LanguageCount(language="markdown", file_count=1, total_bytes=1500),
        ],
        important_files=["README.md", "backend/requirements.txt", "frontend/package.json"],
        has_readme=True,
        dependency_manifests=["backend/requirements.txt", "frontend/package.json"],
        deep_analysis_languages=["javascript", "python", "typescript"],
        symbol_count=len(symbols),
        import_count=len(imports),
        export_count=0,
        route_count=len(routes),
        production_route_count=2,
        test_or_example_route_count=1,
    )
    detections = AnalysisDetections(
        frontend_components=["frontend/src/components/ChatPanel.tsx"],
        backend_services=["backend/app/services/rag_service.py", "frontend/src/services/ragService.ts"],
        api_routes=routes,
        data_access_modules=["backend/app/db/mongo.py"],
        configuration_files=[".env", "backend/requirements.txt", "frontend/package.json"],
        tests=[],
        integrations=["mongodb"],
    )
    return RepositoryAnalysisPayload(
        project_id=project_id,
        repository=AnalysisRepositoryInfo(
            name=repo_name.split("/")[-1],
            url=f"https://github.com/{repo_name}",
            branch="main",
            full_name=repo_name,
        ),
        summary=summary,
        files=files,
        symbols=symbols,
        imports=imports,
        exports=[],
        detections=detections,
    )


def seed_project(
    db: FakeDB,
    *,
    owner_user_id: str,
    with_analysis: bool = True,
    with_health: bool = True,
    with_architecture: bool = True,
    index_ready: bool = True,
    repo_name: str = "acme/chat-app",
    architecture_analyzed_at: datetime | None = None,
    analysis_status: str = "completed",
) -> dict[str, Any]:
    oid = ObjectId()
    project_id = str(oid)
    db.projects.insert(
        {
            "_id": oid,
            "owner_user_id": owner_user_id,
            "name": repo_name,
            "normalized_github_url": f"https://github.com/{repo_name}",
            "technologies": ["Python", "Node.js", "TypeScript"],
            "status": "completed",
        }
    )
    project = {
        "id": project_id,
        "owner_user_id": owner_user_id,
        "name": repo_name,
        "normalized_github_url": f"https://github.com/{repo_name}",
        "technologies": ["Python", "Node.js", "TypeScript"],
    }

    if with_analysis:
        payload = build_payload(project_id, repo_name=repo_name)
        health = build_health_report(payload) if with_health else None
        db.repository_analyses.insert(
            {
                "project_id": project_id,
                "owner_user_id": owner_user_id,
                "status": analysis_status,
                "analysis": payload.model_dump(mode="json"),
                "health_report": health.model_dump(mode="json") if health else None,
                "health_error": None if with_health else "Health report could not be generated: boom",
                "analyzed_at": ANALYZED_AT,
                "error": "clone failed" if analysis_status == "failed" else None,
            }
        )
        if with_architecture:
            graph = validate_architecture_graph(build_deterministic_architecture(payload), payload)
            db.architectures.insert(
                {
                    "project_id": project_id,
                    "owner_user_id": owner_user_id,
                    "status": "completed",
                    "graph": graph.model_dump(),
                    "source": "deterministic",
                    "analyzed_at": architecture_analyzed_at or ANALYZED_AT,
                    "generated_at": ANALYZED_AT + timedelta(minutes=2),
                }
            )

    db.rag_index_status.insert(
        {
            "project_id": project_id,
            "owner_user_id": owner_user_id,
            "status": "ready" if index_ready else "indexing",
            "chunk_count": 40 if index_ready else 0,
            "indexed_at": ANALYZED_AT + timedelta(minutes=3),
        }
    )
    return project


def chunk_row(project_id: str, file_path: str, start: int, end: int, text: str, *, score: float | None = 0.6) -> dict[str, Any]:
    return {
        "id": f"{project_id}_{file_path}_{start}",
        "document": text,
        "metadata": {
            "project_id": project_id,
            "file_path": file_path,
            "start_line": start,
            "end_line": end,
            "language": "python",
        },
        "score": score,
    }


@pytest.fixture
def fake_db() -> FakeDB:
    return FakeDB()


SETTINGS = Settings(_env_file=None, gemini_api_key="test-key")


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace Chroma retrieval, file-scoped chunk lookup and Gemini with recording fakes."""
    state = SimpleNamespace(
        retrieve_calls=[],
        chunk_calls=[],
        retrieve_rows=[],
        chunk_store=[],
        prompts=[],
        answer="Answer.",
    )

    def fake_retrieve(settings: Settings, *, project_id: str, question: str, top_k: int = 6) -> list[dict[str, Any]]:
        state.retrieve_calls.append((project_id, question))
        return [dict(r) for r in state.retrieve_rows if r["metadata"]["project_id"] == project_id]

    def fake_get_chunks(
        settings: Settings, *, project_id: str, file_paths: list[str], limit: int = 400
    ) -> list[dict[str, Any]]:
        state.chunk_calls.append((project_id, sorted(file_paths)))
        return [
            dict(r)
            for r in state.chunk_store
            if r["metadata"]["project_id"] == project_id and r["metadata"]["file_path"] in file_paths
        ]

    async def fake_generate(*, settings: Settings, prompt: str) -> tuple[str, str]:
        state.prompts.append(prompt)
        return state.answer, "fake-model"

    monkeypatch.setattr(rag_service, "retrieve_context", fake_retrieve)
    monkeypatch.setattr(retriever, "get_project_chunks_for_files", fake_get_chunks)
    monkeypatch.setattr(rag_service, "generate_chat_answer", fake_generate)
    return state
