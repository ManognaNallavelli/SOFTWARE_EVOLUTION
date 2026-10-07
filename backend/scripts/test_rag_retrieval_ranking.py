"""Unit checks for RAG retrieval ranking helpers (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.retriever import (
    classify_question,
    contexts_mention_technology,
    detect_presence_technology,
    extract_focus_symbols,
    path_relevance_bonus,
    rerank_contexts,
)


def test_path_priors_implementation() -> None:
    assert path_relevance_bonus("backend/app/api/routes/login.py") > path_relevance_bonus(
        "README.md"
    )
    assert path_relevance_bonus("frontend/src/client/api.ts") > path_relevance_bonus(
        ".github/workflows/test.yml"
    )


def test_path_priors_overview() -> None:
    assert path_relevance_bonus("README.md", intent="overview") > path_relevance_bonus(
        "lib/core/settle.js", intent="overview"
    )
    assert path_relevance_bonus("package.json", intent="overview") > path_relevance_bonus(
        "lib/adapters/http.js", intent="overview"
    )


def test_classify_question() -> None:
    assert classify_question("What is the purpose of this project?") == "overview"
    assert classify_question("Explain the backend architecture.") == "implementation"
    assert (
        classify_question(
            "What are AxiosHeaders, AxiosError, and InterceptorManager, and where are they used?"
        )
        == "usage"
    )
    assert classify_question("Where are the API/request adapters implemented?") == "implementation"
    assert classify_question("What technologies are used in this project?") == "stack"
    assert classify_question("What tech stack does this project use?") == "stack"
    assert classify_question("Which frameworks and libraries are used?") == "stack"
    assert classify_question("What languages are used?") == "stack"


def test_path_priors_stack() -> None:
    assert path_relevance_bonus("package.json", intent="stack") > path_relevance_bonus(
        "lib/core/settle.js", intent="stack"
    )
    assert path_relevance_bonus("rollup.config.js", intent="stack") > path_relevance_bonus(
        "README.md", intent="stack"
    )


def test_extract_symbols() -> None:
    symbols = extract_focus_symbols(
        "What are AxiosHeaders, AxiosError, and InterceptorManager, and where are they used?"
    )
    assert "AxiosHeaders" in symbols
    assert "AxiosError" in symbols
    assert "InterceptorManager" in symbols


def test_rerank_prefers_implementation() -> None:
    rows = [
        {
            "document": "Project overview and setup instructions.",
            "metadata": {"file_path": "README.md", "project_id": "p"},
            "score": 0.92,
        },
        {
            "document": "def authenticate_user(token): ...",
            "metadata": {"file_path": "backend/app/core/security.py", "project_id": "p"},
            "score": 0.80,
        },
        {
            "document": "run tests on pull request",
            "metadata": {"file_path": ".github/workflows/ci.yml", "project_id": "p"},
            "score": 0.88,
        },
    ]
    ranked = rerank_contexts("Where is authentication implemented?", rows, top_k=2)
    assert ranked
    assert "security.py" in ranked[0]["metadata"]["file_path"]


def test_rerank_prefers_readme_for_overview() -> None:
    rows = [
        {
            "document": "Promise based HTTP client for the browser and node.js",
            "metadata": {"file_path": "README.md", "project_id": "p"},
            "score": 0.72,
        },
        {
            "document": "function settle(resolve, reject, response) { ... }",
            "metadata": {"file_path": "lib/core/settle.js", "project_id": "p"},
            "score": 0.90,
        },
        {
            "document": '{"name":"axios","description":"Promise based HTTP client"}',
            "metadata": {"file_path": "package.json", "project_id": "p"},
            "score": 0.70,
        },
        {
            "document": '{"name":"docs","description":"Documentation for the Axios HTTP client"}',
            "metadata": {"file_path": "docs/package.json", "project_id": "p"},
            "score": 0.88,
        },
    ]
    ranked = rerank_contexts("What is the purpose of this project?", rows, top_k=2)
    paths = [r["metadata"]["file_path"] for r in ranked]
    assert paths[0] in {"README.md", "package.json"}
    assert "docs/package.json" not in paths
    assert "settle.js" not in paths[0]


def test_rerank_usage_keeps_definition_and_import() -> None:
    rows = [
        {
            "document": "class AxiosHeaders {\n  constructor() {}\n}",
            "metadata": {"file_path": "lib/core/AxiosHeaders.js", "project_id": "p"},
            "score": 0.70,
        },
        {
            "document": "import AxiosHeaders from './core/AxiosHeaders.js';\nexport default AxiosHeaders;",
            "metadata": {"file_path": "lib/axios.js", "project_id": "p"},
            "score": 0.66,
        },
        {
            "document": "# Contributing guide",
            "metadata": {"file_path": "CONTRIBUTING.md", "project_id": "p"},
            "score": 0.85,
        },
    ]
    ranked = rerank_contexts(
        "What is AxiosHeaders and where is it used?",
        rows,
        top_k=2,
    )
    paths = {r["metadata"]["file_path"] for r in ranked}
    assert "lib/core/AxiosHeaders.js" in paths
    assert "lib/axios.js" in paths


def test_presence_detection() -> None:
    assert detect_presence_technology("Is Redis used in this project?") == "Redis"
    assert detect_presence_technology("Does this repository use Kafka?") == "Kafka"
    contexts = [
        {
            "document": "import redis\ncache = redis.Redis()",
            "metadata": {"file_path": "app/cache.py"},
        }
    ]
    assert contexts_mention_technology(contexts, "Redis") is True
    assert contexts_mention_technology([{"document": "fastapi app", "metadata": {}}], "Redis") is False


if __name__ == "__main__":
    test_path_priors_implementation()
    test_path_priors_overview()
    test_path_priors_stack()
    test_classify_question()
    test_extract_symbols()
    test_rerank_prefers_implementation()
    test_rerank_prefers_readme_for_overview()
    test_rerank_usage_keeps_definition_and_import()
    test_presence_detection()
    print("RAG retriever unit checks passed.")
