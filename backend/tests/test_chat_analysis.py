"""chat_with_project with stored analysis data (Gemini and Chroma replaced by fakes)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.rag.prompts import NO_EVIDENCE_REPLY
from app.services.rag_service import chat_with_project
from tests.conftest import SETTINGS, FakeDB, chunk_row, seed_project

ANALYSIS_SECTION = "Repository analysis findings"


def ask(db: FakeDB, project: dict, question: str):
    return asyncio.run(chat_with_project(db, project=project, message=question, settings=SETTINGS))


# --- health / issues -------------------------------------------------------


def test_health_score_question_answers_from_stored_report(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    env.answer = "The score is pulled down by testing [A2] and security [A3]."
    resp = ask(fake_db, project, "Why is the health score low?")

    prompt = env.prompts[0]
    assert ANALYSIS_SECTION in prompt
    assert "[A1] Overall health score" in prompt
    assert "No test files detected." in prompt
    assert env.retrieve_calls == [], "pure health questions should not trigger code retrieval"
    assert [f.id for f in resp.analysis_findings] == ["A2", "A3"]
    assert resp.context_insufficient is False
    assert resp.answer == env.answer


def test_biggest_problems_lists_detected_issues(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    env.answer = "The biggest problem is a committed secrets file."
    resp = ask(fake_db, project, "What are the biggest problems in this repository?")

    prompt = env.prompts[0]
    assert "Issue (critical, security)" in prompt
    assert "Files: .env" in prompt
    # Answer cited nothing explicitly, so every provided finding is returned for the UI.
    assert any(f.kind == "health_issue" for f in resp.analysis_findings)
    issue = next(f for f in resp.analysis_findings if f.kind == "health_issue")
    assert issue.file_refs[0].file_path == ".env" and issue.file_refs[0].line is None


def test_category_score_below_threshold_is_not_treated_as_refusal(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    env.answer = "Architecture has insufficient data [A4]; testing scored lowest [A2]."
    resp = ask(fake_db, project, "What is the health score?")
    assert len(env.prompts) == 1, "no over-refusal retry"
    assert resp.context_insufficient is False


# --- architecture / dependencies -------------------------------------------


def test_architecture_component_question_combines_finding_and_code(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    pid = project["id"]
    env.chunk_store = [chunk_row(pid, "backend/app/db/mongo.py", 1, 30, "client = AsyncIOMotorClient(uri)")]
    resp = ask(fake_db, project, "Explain the data access component of the architecture.")

    prompt = env.prompts[0]
    assert "Architecture component: Data access" in prompt
    assert "backend/app/db/mongo.py:1-30" in prompt
    assert "supports A" in prompt
    assert env.retrieve_calls, "architecture questions keep semantic code retrieval"
    mongo_source = next(s for s in resp.sources if s.file_path == "backend/app/db/mongo.py")
    assert mongo_source.supports and mongo_source.start_line == 1 and mongo_source.end_line == 30


def test_dependents_question_cites_import_lines(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    resp = ask(fake_db, project, "What depends on the rag service?")
    prompt = env.prompts[0]
    assert "backend/app/api/routes/rag.py:13 imports 'app.services.rag_service'" in prompt
    refs = {(r.file_path, r.line) for f in resp.analysis_findings for r in f.file_refs}
    assert ("backend/app/api/routes/rag.py", 13) in refs


# --- routes / technologies -------------------------------------------------


def test_route_listing_uses_analysis_without_code_retrieval(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ask(fake_db, project, "Which APIs and routes were detected?")
    prompt = env.prompts[0]
    assert "Route POST /{project_id}/chat (production)" in prompt
    assert "backend/app/api/routes/rag.py:35" in prompt
    assert "/demo" not in prompt, "example routes are excluded unless asked for"
    assert env.retrieve_calls == [] and env.chunk_calls == []


def test_route_definition_question_fetches_covering_chunk(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    pid = project["id"]
    env.chunk_store = [
        chunk_row(pid, "backend/app/api/routes/rag.py", 1, 20, "from fastapi import APIRouter"),
        chunk_row(pid, "backend/app/api/routes/rag.py", 26, 47, '@router.post("/{project_id}/chat")\nasync def chat('),
    ]
    resp = ask(fake_db, project, "Where is the chat endpoint defined and how is it implemented?")

    supporting = [s for s in resp.sources if s.supports]
    assert supporting and (supporting[0].file_path, supporting[0].start_line) == ("backend/app/api/routes/rag.py", 26)
    assert '@router.post("/{project_id}/chat")' in env.prompts[0]


def test_technology_question_includes_stack_metadata_and_findings(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    pid = project["id"]
    env.retrieve_rows = [chunk_row(pid, "backend/requirements.txt", 1, 10, "fastapi\nmotor")]
    resp = ask(fake_db, project, "Which technologies and frameworks does this project use?")
    prompt = env.prompts[0]
    assert "Detected stack labels: Python, Node.js, TypeScript" in prompt  # existing stack metadata
    assert "Integration inferred from imports: mongodb" in prompt
    assert any(f.kind == "integration" for f in resp.analysis_findings)


# --- missing / outdated analysis -------------------------------------------


def test_missing_analysis_answers_explicitly_without_llm(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1", with_analysis=False)
    resp = ask(fake_db, project, "What issues were detected?")
    assert env.prompts == []
    assert resp.answer.startswith("I can't answer this from stored analysis results.")
    assert "No repository analysis has been run" in resp.answer
    assert resp.context_insufficient is True
    assert resp.analysis_findings == []


def test_missing_architecture_with_code_question_falls_back_to_code_with_note(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1", with_architecture=False)
    pid = project["id"]
    env.retrieve_rows = [chunk_row(pid, "backend/app/main.py", 1, 30, "app = FastAPI()")]
    ask(fake_db, project, "Explain the backend architecture.")
    prompt = env.prompts[0]
    assert "An architecture graph has not been generated for this project yet." in prompt
    assert "backend/app/main.py" in prompt


def test_analysis_questions_work_while_code_index_is_not_ready(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1", index_ready=False)
    resp = ask(fake_db, project, "What issues were detected?")
    assert env.prompts and "code index is not ready" in env.prompts[0]
    assert any(f.kind == "health_issue" for f in resp.analysis_findings)
    assert env.retrieve_calls == []


def test_code_questions_still_require_ready_index(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1", index_ready=False)
    with pytest.raises(HTTPException) as exc:
        ask(fake_db, project, "Where is authentication implemented?")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "rag_not_ready"


# --- isolation --------------------------------------------------------------


def test_chat_only_reads_the_requested_projects_data(fake_db: FakeDB, env) -> None:
    mine = seed_project(fake_db, owner_user_id="u1", repo_name="acme/chat-app")
    other = seed_project(fake_db, owner_user_id="u2", repo_name="rival/secret-service")
    env.retrieve_rows = [
        chunk_row(other["id"], "backend/app/main.py", 1, 10, "rival secret code"),
        chunk_row(mine["id"], "backend/app/main.py", 1, 10, "acme code"),
    ]
    env.chunk_store = [chunk_row(other["id"], "backend/app/db/mongo.py", 1, 30, "rival mongo")]
    ask(fake_db, mine, "Explain the data access component of the architecture.")

    prompt = env.prompts[0]
    assert "rival" not in prompt and "secret-service" not in prompt
    assert {pid for pid, _ in env.retrieve_calls} == {mine["id"]}
    assert {pid for pid, _ in env.chunk_calls} == {mine["id"]}
    for collection in (fake_db.repository_analyses, fake_db.architectures, fake_db.rag_index_status):
        assert all(q == {"project_id": mine["id"]} for q in collection.queries)


def test_analysis_document_owned_by_another_user_is_ignored(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    for collection in (fake_db.repository_analyses, fake_db.architectures):
        for doc in collection.docs:
            doc["owner_user_id"] = "attacker"
    resp = ask(fake_db, project, "What issues were detected?")
    assert env.prompts == []
    assert "No repository analysis has been run" in resp.answer


# --- existing behaviour (regressions) ---------------------------------------


def test_plain_code_question_keeps_original_prompt(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    pid = project["id"]
    env.retrieve_rows = [chunk_row(pid, "backend/app/auth.py", 1, 40, "def login(): ...")]
    env.answer = "Authentication lives in backend/app/auth.py."
    resp = ask(fake_db, project, "Where is authentication implemented?")
    assert ANALYSIS_SECTION not in env.prompts[0]
    assert env.chunk_calls == []
    assert resp.analysis_findings == [] and resp.analysis_notes == []
    assert [s.file_path for s in resp.sources] == ["backend/app/auth.py"]


def test_no_retrieved_context_still_returns_no_evidence(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    resp = ask(fake_db, project, "Where is authentication implemented?")
    assert resp.answer == NO_EVIDENCE_REPLY
    assert resp.context_insufficient is True


def test_absent_technology_still_short_circuits(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    env.retrieve_rows = [chunk_row(project["id"], "backend/app/main.py", 1, 10, "app = FastAPI()")]
    resp = ask(fake_db, project, "Does this project use Redis?")
    assert resp.answer == "No evidence of Redis was found in the indexed repository."
    assert env.prompts == []


def test_technology_found_in_analysis_is_not_reported_absent(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    env.retrieve_rows = [chunk_row(project["id"], "backend/app/main.py", 1, 10, "app = FastAPI()")]
    env.answer = "Yes, MongoDB is used via motor [A1]."
    resp = ask(fake_db, project, "Does this project use MongoDB?")
    assert env.prompts, "analysis evidence should reach the model"
    assert "Integration inferred from imports: mongodb" in env.prompts[0]
    assert resp.analysis_findings[0].file_refs[0].file_path == "backend/app/db/mongo.py"


def test_empty_message_rejected(fake_db: FakeDB, env) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    with pytest.raises(HTTPException) as exc:
        ask(fake_db, project, "   ")
    assert exc.value.status_code == 400
