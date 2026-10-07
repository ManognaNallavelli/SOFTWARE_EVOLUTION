"""Question-driven selection of stored analysis findings (no network, no Chroma)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.rag.analysis_context import (
    AnalysisSnapshot,
    build_analysis_context,
    classify_analysis_topics,
    load_analysis_snapshot,
    module_matches,
    render_analysis_block,
    technology_presence_facts,
)
from app.rag.retriever import select_supporting_chunks
from tests.conftest import ANALYZED_AT, FakeDB, chunk_row, seed_project


def _snapshot(db: FakeDB, project: dict) -> AnalysisSnapshot:
    status = asyncio.run(db.rag_index_status.find_one({"project_id": project["id"]}))
    return asyncio.run(load_analysis_snapshot(db, project, rag_status_doc=status))


def _titles(ctx) -> list[str]:
    return [f.title for f in ctx.facts]


def test_topic_classification_covers_phase1_questions() -> None:
    assert "health" in classify_analysis_topics("Why is the health score low?")
    assert "issues" in classify_analysis_topics("What issues were detected?")
    assert "recommendations" in classify_analysis_topics("What recommendations did the analysis generate?")
    assert "architecture" in classify_analysis_topics("Explain this architecture component.")
    assert "dependencies" in classify_analysis_topics("What depends on this module?")
    assert "routes" in classify_analysis_topics("Which APIs and routes were detected?")
    assert "issues" in classify_analysis_topics("What are the biggest problems in this repository?")
    # Plain implementation questions stay on the existing code-retrieval path.
    assert classify_analysis_topics("Where is authentication implemented?") == set()


def test_health_score_question_uses_stored_report(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    snap = _snapshot(fake_db, project)
    ctx = build_analysis_context(snap, "Why is the health score low?")

    assert snap.health is not None
    overall = ctx.facts[0]
    assert overall.title == "Overall health score"
    assert f"{snap.health.overall_score}/100" in overall.detail
    categories = [f for f in ctx.facts if f.kind == "health_category"]
    assert len(categories) == len(snap.health.categories)
    scores = [snap.health.categories[f.title.split(": ", 1)[1].replace(" ", "_")].score for f in categories]
    scored = [s for s in scores if s is not None]
    assert scored == sorted(scored), "lowest-scoring categories should come first"
    testing = next(f for f in categories if f.title.endswith("testing"))
    assert "No test files detected." in testing.detail
    assert any(f.kind == "health_method" for f in ctx.facts)
    assert ctx.wants_explanation


def test_issue_question_lists_detected_issues_by_severity(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    snap = _snapshot(fake_db, project)
    ctx = build_analysis_context(snap, "What issues were detected?")

    issues = [f for f in ctx.facts if f.kind == "health_issue"]
    assert issues, _titles(ctx)
    assert len(issues) == min(len(snap.health.issues), 10)
    assert issues[0].title.startswith("Issue (critical, security)")
    # The sensitive-file finding names `.env`, which exists in the stored inventory.
    assert [r.file_path for r in issues[0].file_refs] == [".env"]
    assert all(r.line is None for f in issues for r in f.file_refs), "health issues store no line numbers"


def test_category_filter_for_issue_question(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "What testing problems were found?")
    issues = [f for f in ctx.facts if f.kind == "health_issue"]
    assert issues and all("testing" in f.title for f in issues)


def test_recommendations_question(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    snap = _snapshot(fake_db, project)
    ctx = build_analysis_context(snap, "What recommendations did the analysis generate?")
    recs = [f for f in ctx.facts if f.kind == "recommendation"]
    assert [r.title.split(": ", 1)[1] for r in recs] == [r.title for r in snap.health.recommendations]


def test_architecture_component_question_matches_node_and_edges(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "Explain the data access component of the architecture.")

    nodes = [f for f in ctx.facts if f.kind == "architecture_node"]
    assert nodes and nodes[0].title.startswith("Architecture component: Data access")
    assert any(r.file_path == "backend/app/db/mongo.py" for r in nodes[0].file_refs)
    edges = [f for f in ctx.facts if f.kind == "architecture_edge"]
    assert any("Data access" in e.title for e in edges)
    assert ctx.facts[0].kind == "architecture_summary"


def test_unnamed_component_is_reported_not_guessed(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "What depends on this module?")
    assert any("this module" in note for note in ctx.notes)
    assert any(f.kind == "architecture_components" for f in ctx.facts)
    assert not any(f.kind == "import" for f in ctx.facts)


def test_dependents_of_named_module_use_stored_import_lines(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "What depends on the rag service?")

    imports = [f for f in ctx.facts if f.kind == "import"]
    assert imports, _titles(ctx)
    refs = {(r.file_path, r.line) for f in imports for r in f.file_refs}
    assert ("backend/app/api/routes/rag.py", 13) in refs
    # ragService.ts (frontend) is imported by ChatPanel via a relative path.
    assert ("frontend/src/components/ChatPanel.tsx", 5) in refs
    assert all("Imports declared in" not in f.title for f in imports), "incoming question only"


def test_outgoing_dependencies_question(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "What does `rag_service` import?")
    imports = [f for f in ctx.facts if f.kind == "import"]
    assert imports and imports[0].title.startswith("Imports declared in `rag_service`")
    assert imports[0].file_refs[0].line == 14


def test_routes_question_lists_production_routes_with_lines(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "Which APIs and routes were detected?")

    summary = next(f for f in ctx.facts if f.kind == "route_summary")
    assert "2 production route(s)" in summary.detail
    routes = [f for f in ctx.facts if f.kind == "route"]
    assert {f.title for f in routes} == {
        "Route POST /{project_id}/chat (production)",
        "Route GET /{project_id}/rag/status (production)",
    }
    assert {(r.file_refs[0].file_path, r.file_refs[0].line) for r in routes} == {
        ("backend/app/api/routes/rag.py", 35),
        ("backend/app/api/routes/rag.py", 27),
    }


def test_technology_question_uses_detected_stack(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "Which technologies and frameworks does it use?")
    titles = _titles(ctx)
    assert "Detected stack labels" in titles
    assert "Dependency manifests" in titles
    integration = next(f for f in ctx.facts if f.kind == "integration")
    assert integration.file_refs[0].file_path == "backend/app/db/mongo.py"
    assert integration.file_refs[0].line == 8


def test_technology_presence_from_imports(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    snap = _snapshot(fake_db, project)
    assert technology_presence_facts(snap, "MongoDB")
    assert technology_presence_facts(snap, "motor")
    assert technology_presence_facts(snap, "Redis") == []


def test_symbol_lookup_cites_stored_definition_lines(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "How does chat_with_project work?")
    assert "symbols" in ctx.topics
    symbol = next(f for f in ctx.facts if f.kind == "symbol")
    ref = symbol.file_refs[0]
    assert (ref.file_path, ref.line, ref.end_line) == ("backend/app/services/rag_service.py", 356, 420)


def test_statistics_question(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "How many files are in the repository and which are the largest files?")
    assert ctx.facts[0].title == "Repository statistics"
    assert "11 files in 9 directories" in ctx.facts[0].detail
    largest = next(f for f in ctx.facts if f.title == "Largest files")
    assert largest.file_refs[0].file_path == "backend/app/services/rag_service.py"


def test_architecture_node_refs_never_invent_lines(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    snap = _snapshot(fake_db, project)
    ctx = build_analysis_context(snap, "Explain the API controllers component")
    stored_lines = {(r.file_path, r.line) for r in snap.analysis.detections.api_routes}
    stored_lines |= {(i.source_file, i.line) for i in snap.analysis.imports}
    stored_lines |= {(s.file_path, s.start_line) for s in snap.analysis.symbols}
    for fact in ctx.facts:
        for ref in fact.file_refs:
            if ref.line is not None:
                assert (ref.file_path, ref.line) in stored_lines, (fact.title, ref)


def test_missing_analysis_produces_note_and_no_facts(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1", with_analysis=False)
    ctx = build_analysis_context(_snapshot(fake_db, project), "What issues were detected?")
    assert ctx.facts == []
    assert ctx.notes == ["No repository analysis has been run for this project yet."]


def test_missing_health_report_is_explicit(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1", with_health=False)
    ctx = build_analysis_context(_snapshot(fake_db, project), "Why is the health score low?")
    assert not any(f.kind.startswith("health") for f in ctx.facts)
    assert any("No health report is available" in n for n in ctx.notes)


def test_missing_architecture_is_explicit(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1", with_architecture=False)
    ctx = build_analysis_context(_snapshot(fake_db, project), "Explain the architecture.")
    assert any("has not been generated" in n for n in ctx.notes)
    assert not any(f.kind.startswith("architecture") for f in ctx.facts)


def test_outdated_architecture_is_flagged(fake_db: FakeDB) -> None:
    project = seed_project(
        fake_db, owner_user_id="u1", architecture_analyzed_at=ANALYZED_AT - timedelta(days=3)
    )
    ctx = build_analysis_context(_snapshot(fake_db, project), "Explain the architecture.")
    assert any("older analysis" in n for n in ctx.notes)


def test_failed_reanalysis_keeps_previous_results_with_note(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1", analysis_status="failed")
    ctx = build_analysis_context(_snapshot(fake_db, project), "What issues were detected?")
    assert ctx.facts
    assert any("most recent analysis attempt failed" in n for n in ctx.notes)


def test_non_analysis_question_has_no_context(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "Where is authentication implemented?")
    assert ctx.topics == set() and ctx.facts == [] and ctx.notes == []


def test_render_block_contains_ids_and_refs(fake_db: FakeDB) -> None:
    project = seed_project(fake_db, owner_user_id="u1")
    ctx = build_analysis_context(_snapshot(fake_db, project), "Which routes were detected?")
    block = render_analysis_block(ctx)
    assert "[A1] Detected API routes" in block
    assert "backend/app/api/routes/rag.py:35" in block


def test_module_matching() -> None:
    assert module_matches("app.services.rag_service", "rag_service")
    assert module_matches("backend/app/services/rag_service.py", "app.services.rag_service")
    assert module_matches("../services/ragService", "ragService.ts")
    assert not module_matches("app.services.rag_service_v2", "rag_service")


def test_supporting_chunk_selection_covers_stored_line() -> None:
    pid = "p1"
    rows = [
        chunk_row(pid, "backend/app/api/routes/rag.py", 1, 48, "imports ..."),
        chunk_row(pid, "backend/app/api/routes/rag.py", 20, 40, "@router.post('/{project_id}/chat')\nasync def chat"),
        chunk_row(pid, "backend/app/db/mongo.py", 1, 30, "client = AsyncIOMotorClient()"),
    ]
    refs = [
        {"file_path": "backend/app/api/routes/rag.py", "line": 35, "finding_id": "A2"},
        {"file_path": "backend/app/db/mongo.py", "line": None, "finding_id": "A4"},
        {"file_path": "unknown.py", "line": 3, "finding_id": "A5"},
    ]
    picked = select_supporting_chunks(rows, refs, question="where is chat defined", max_chunks=3)
    assert [(r["metadata"]["file_path"], r["metadata"]["start_line"]) for r in picked] == [
        ("backend/app/api/routes/rag.py", 20),
        ("backend/app/db/mongo.py", 1),
    ]
    assert picked[0]["supports"] == ["A2"]
