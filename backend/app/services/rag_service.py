"""Orchestrate RAG indexing and chat for a project."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.rag.analysis_context import (
    AnalysisFact,
    availability_notes,
    build_analysis_context,
    load_analysis_snapshot,
    render_analysis_block,
    technology_presence_facts,
)
from app.rag.page_context import resolve_page_context
from app.rag.chroma_store import (
    delete_project_chunks,
    upsert_chunks,
)
from app.rag.chunker import chunk_repository
from app.rag.embedder import embed_texts
from app.rag.gemini_chat_client import GeminiChatError, generate_chat_answer
from app.rag.prompts import build_rag_prompt
from app.rag.retriever import (
    classify_question,
    contexts_mention_technology,
    detect_presence_technology,
    retrieve_context,
    retrieve_supporting_chunks,
)
from app.schemas.rag import (
    AnalysisFileRef,
    AnalysisFinding,
    ChatContext,
    ChatResponse,
    ChatSource,
    RagIndexResponse,
    RagStatusResponse,
)
from app.services.clone_service import cleanup_clone_path, clone_public_repository

logger = logging.getLogger(__name__)

CHAT_TOP_K = 5
MAX_SUPPORTING_CHUNKS = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _build_stack_metadata(project: dict[str, Any], analysis_doc: dict[str, Any] | None) -> str | None:
    """Serialize detected stack + analysis language/manifest evidence for chat prompts."""
    lines: list[str] = []
    technologies = [str(t).strip() for t in (project.get("technologies") or []) if str(t).strip()]
    if technologies:
        lines.append("Detected stack labels: " + ", ".join(technologies))

    analysis = (analysis_doc or {}).get("analysis") or {}
    summary = analysis.get("summary") or {}
    languages = summary.get("languages") or []
    if isinstance(languages, list) and languages:
        ranked: list[str] = []
        for item in languages:
            if not isinstance(item, dict):
                continue
            name = str(item.get("language") or "").strip()
            if not name or name.lower() in {
                "markdown",
                "json",
                "yaml",
                "yml",
                "toml",
                "xml",
                "text",
                "plaintext",
            }:
                continue
            ranked.append(name)
        if ranked:
            lines.append("Languages from analysis: " + ", ".join(ranked[:12]))

    manifests = summary.get("dependency_manifests") or []
    if isinstance(manifests, list) and manifests:
        paths = [str(p) for p in manifests if str(p).strip()][:12]
        if paths:
            lines.append("Dependency manifests: " + ", ".join(paths))

    important = summary.get("important_files") or []
    if isinstance(important, list) and important:
        interesting = [
            str(p)
            for p in important
            if any(
                token in str(p).lower()
                for token in (
                    "package.json",
                    "pyproject.toml",
                    "requirements.txt",
                    "tsconfig",
                    "webpack",
                    "rollup",
                    "vite.config",
                    "go.mod",
                    "cargo.toml",
                    "dockerfile",
                )
            )
        ][:12]
        if interesting:
            lines.append("Relevant config/manifest files: " + ", ".join(interesting))

    detections = analysis.get("detections") or {}
    config_files = detections.get("configuration_files") or []
    if isinstance(config_files, list) and config_files:
        cfg = [str(p) for p in config_files if str(p).strip()][:12]
        if cfg:
            lines.append("Configuration files: " + ", ".join(cfg))

    if not lines:
        return None
    return "\n".join(lines)


def _has_stack_manifest_sources(rows: list[dict[str, Any]]) -> bool:
    markers = (
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "go.mod",
        "cargo.toml",
        "tsconfig",
        "webpack",
        "rollup",
        "vite.config",
        "package-lock",
        "yarn.lock",
        "pnpm-lock",
    )
    for row in rows:
        path = str((row.get("metadata") or {}).get("file_path") or "").lower()
        if any(marker in path for marker in markers):
            return True
    return False


async def get_rag_status(db: AsyncIOMotorDatabase, project_id: str) -> RagStatusResponse:
    doc = await db.rag_index_status.find_one({"project_id": project_id})
    if doc is None:
        return RagStatusResponse(project_id=project_id, status="not_indexed")
    return RagStatusResponse(
        project_id=project_id,
        status=doc.get("status") or "not_indexed",
        chunk_count=int(doc.get("chunk_count") or 0),
        file_count=int(doc.get("file_count") or 0),
        indexed_at=doc.get("indexed_at"),
        updated_at=doc.get("updated_at"),
        error=doc.get("error"),
        error_code=doc.get("error_code"),
        embedding_model=doc.get("embedding_model"),
        message=doc.get("message"),
    )


async def index_project_repository(
    db: AsyncIOMotorDatabase,
    *,
    project: dict[str, Any],
    settings: Settings | None = None,
) -> RagIndexResponse:
    settings = settings or get_settings()
    project_id = project["id"]
    now = _utcnow()
    timings: dict[str, float] = {}
    clone_path = None

    existing = await db.rag_index_status.find_one({"project_id": project_id})
    if existing and existing.get("status") == "indexing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "rag_indexing_in_progress",
                "message": "RAG indexing is already in progress for this project.",
            },
        )

    await db.rag_index_status.update_one(
        {"project_id": project_id},
        {
            "$set": {
                "project_id": project_id,
                "owner_user_id": project["owner_user_id"],
                "status": "indexing",
                "error": None,
                "error_code": None,
                "message": "Cloning repository and building embeddings…",
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    try:
        analysis_doc = await db.repository_analyses.find_one({"project_id": project_id})
        branch = None
        symbols: list[dict[str, Any]] = []
        if analysis_doc and analysis_doc.get("analysis"):
            analysis = analysis_doc["analysis"]
            branch = (analysis.get("repository") or {}).get("branch")
            symbols = list(analysis.get("symbols") or [])

        t0 = time.perf_counter()
        clone = await asyncio.to_thread(
            clone_public_repository,
            settings=settings,
            project_id=project_id,
            github_url=project["normalized_github_url"],
            branch=branch,
        )
        clone_path = clone.local_path
        timings["clone_s"] = time.perf_counter() - t0

        await db.rag_index_status.update_one(
            {"project_id": project_id},
            {"$set": {"message": "Chunking repository files…", "updated_at": _utcnow()}},
        )

        t1 = time.perf_counter()
        chunks, file_count = await asyncio.to_thread(
            chunk_repository,
            project_id=project_id,
            repo_root=clone.local_path,
            analysis_symbols=symbols,
        )
        timings["chunk_s"] = time.perf_counter() - t1

        await db.rag_index_status.update_one(
            {"project_id": project_id},
            {
                "$set": {
                    "message": f"Embedding {len(chunks)} chunks…",
                    "updated_at": _utcnow(),
                }
            },
        )

        t2 = time.perf_counter()
        await asyncio.to_thread(delete_project_chunks, settings, project_id)
        timings["chroma_delete_s"] = time.perf_counter() - t2

        t3 = time.perf_counter()
        embeddings = await asyncio.to_thread(
            embed_texts,
            [c.text for c in chunks],
            model_name=settings.embedding_model_name,
            batch_size=64,
        )
        timings["embed_s"] = time.perf_counter() - t3

        t4 = time.perf_counter()
        stored = await asyncio.to_thread(upsert_chunks, settings, chunks, embeddings)
        timings["chroma_upsert_s"] = time.perf_counter() - t4
        timings["total_s"] = sum(timings.values())

        logger.info(
            "RAG index timings project=%s files=%s chunks=%s timings=%s",
            project_id,
            file_count,
            stored,
            {k: round(v, 3) for k, v in timings.items()},
        )

        indexed_at = _utcnow()
        message = (
            f"Repository indexed for RAG chat "
            f"({file_count} files, {stored} chunks, {timings['total_s']:.1f}s)."
        )
        await db.rag_index_status.update_one(
            {"project_id": project_id},
            {
                "$set": {
                    "status": "ready",
                    "chunk_count": stored,
                    "file_count": file_count,
                    "indexed_at": indexed_at,
                    "updated_at": indexed_at,
                    "error": None,
                    "error_code": None,
                    "embedding_model": settings.embedding_model_name,
                    "message": message,
                    "timings": timings,
                    "owner_user_id": project["owner_user_id"],
                }
            },
            upsert=True,
        )

        return RagIndexResponse(
            project_id=project_id,
            status="ready",
            chunk_count=stored,
            file_count=file_count,
            indexed_at=indexed_at,
            updated_at=indexed_at,
            error=None,
            error_code=None,
            embedding_model=settings.embedding_model_name,
            message=message,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        error_message = str(detail.get("message") or exc.detail)
        await db.rag_index_status.update_one(
            {"project_id": project_id},
            {
                "$set": {
                    "status": "failed",
                    "error": error_message,
                    "error_code": str(detail.get("code") or "rag_index_failed"),
                    "message": "Indexing failed.",
                    "updated_at": _utcnow(),
                }
            },
            upsert=True,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("RAG indexing failed for %s", project_id)
        await db.rag_index_status.update_one(
            {"project_id": project_id},
            {
                "$set": {
                    "status": "failed",
                    "error": str(exc),
                    "error_code": "rag_index_failed",
                    "message": "Indexing failed.",
                    "updated_at": _utcnow(),
                }
            },
            upsert=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "rag_index_failed", "message": str(exc)},
        ) from exc
    finally:
        cleanup_clone_path(clone_path)


async def schedule_auto_index(
    *,
    project: dict[str, Any],
    settings: Settings | None = None,
) -> None:
    """Fire-and-forget indexing after analysis. Never raises to the caller."""
    settings = settings or get_settings()
    project_id = project["id"]
    try:
        db = get_db_safe()
        if db is None:
            return
        existing = await db.rag_index_status.find_one({"project_id": project_id})
        if existing and existing.get("status") == "indexing":
            logger.info("Skip auto-index for %s — already indexing", project_id)
            return
        logger.info("Auto-starting RAG index for project %s", project_id)
        await index_project_repository(db, project=project, settings=settings)
    except Exception:  # noqa: BLE001
        logger.exception("Auto RAG index failed for %s", project_id)


def get_db_safe() -> AsyncIOMotorDatabase | None:
    try:
        from app.db.mongo import get_db

        return get_db()
    except Exception:  # noqa: BLE001
        return None


async def chat_with_project(
    db: AsyncIOMotorDatabase,
    *,
    project: dict[str, Any],
    message: str,
    context: ChatContext | None = None,
    settings: Settings | None = None,
) -> ChatResponse:
    settings = settings or get_settings()
    project_id = project["id"]
    question = message.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_message", "message": "Message cannot be empty."},
        )

    status_doc = await db.rag_index_status.find_one({"project_id": project_id})
    index_error: dict[str, str] | None = None
    if status_doc is None or status_doc.get("status") != "ready":
        index_error = {
            "code": "rag_not_ready",
            "message": "Repository is still indexing or not indexed yet. Try again shortly.",
        }
    elif int(status_doc.get("chunk_count") or 0) <= 0:
        index_error = {
            "code": "rag_empty_index",
            "message": "No indexed chunks found for this project. Re-index the repository.",
        }
    index_ready = index_error is None

    snapshot = await load_analysis_snapshot(db, project, rag_status_doc=status_doc)
    page_ctx = resolve_page_context(snapshot, context, question)
    analysis_ctx = build_analysis_context(
        snapshot,
        question,
        extra_topics=page_ctx.page_topics,
        has_selection=page_ctx.use_selection,
    )
    selection = page_ctx.selection if page_ctx.use_selection else None
    if selection is not None:
        analysis_ctx.topics |= selection.topics
        for note in availability_notes(snapshot, selection.topics):
            if note not in analysis_ctx.notes:
                analysis_ctx.notes.append(note)
        analysis_ctx.prepend_facts(selection.facts)
    analysis_ctx.notes.extend(page_ctx.notes)
    retrieval_question = page_ctx.retrieval_question(question)

    # The question targets stored analysis results that do not exist: say so
    # instead of letting code retrieval or the model guess.
    if (
        analysis_ctx.topics
        and not analysis_ctx.facts
        and analysis_ctx.notes
        and not (index_ready and analysis_ctx.code_relevant)
    ):
        return _analysis_unavailable_response(project_id, analysis_ctx.notes)

    if not index_ready and not analysis_ctx.facts:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=index_error)
    if not index_ready:
        analysis_ctx.notes.append(
            "The code index is not ready, so no source snippets are available; "
            "answer from the analysis findings only."
        )

    intent = classify_question(question)
    run_semantic = index_ready and (
        not analysis_ctx.topics or analysis_ctx.code_relevant or not analysis_ctx.facts
    )

    t_retrieve = time.perf_counter()
    filtered: list[dict[str, Any]] = []
    if run_semantic:
        contexts = await asyncio.to_thread(
            retrieve_context,
            settings,
            project_id=project_id,
            question=retrieval_question,
            top_k=CHAT_TOP_K,
        )
        for row in contexts:
            score = row.get("score")
            if score is not None and score < 0.12:
                continue
            filtered.append(row)
        filtered = filtered[:CHAT_TOP_K]
    retrieve_s = time.perf_counter() - t_retrieve

    stack_metadata = (
        _build_stack_metadata(project, snapshot.analysis_doc) if intent == "stack" else None
    )

    if run_semantic and intent == "stack" and not _has_stack_manifest_sources(filtered):
        broader = await asyncio.to_thread(
            retrieve_context,
            settings,
            project_id=project_id,
            question=(
                "package.json dependencies devDependencies engines "
                "pyproject.toml requirements.txt tsconfig webpack rollup vite"
            ),
            top_k=8,
        )
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in [*broader, *filtered]:
            meta = row.get("metadata") or {}
            key = str(
                row.get("id")
                or f"{meta.get('file_path')}:{meta.get('start_line')}-{meta.get('end_line')}"
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
        filtered = merged[: max(CHAT_TOP_K, 6)]

    presence_tech = detect_presence_technology(question)
    tech_facts = technology_presence_facts(snapshot, presence_tech) if presence_tech else []
    analysis_ctx.add_facts(tech_facts)
    if presence_tech and filtered and not contexts_mention_technology(filtered, presence_tech):
        # Broader pass for dependency/config evidence before concluding absence.
        broader = await asyncio.to_thread(
            retrieve_context,
            settings,
            project_id=project_id,
            question=f"{presence_tech} dependency configuration import require",
            top_k=8,
        )
        if contexts_mention_technology(broader, presence_tech):
            filtered = broader[:CHAT_TOP_K]
        elif not tech_facts:
            return ChatResponse(
                project_id=project_id,
                answer=(
                    f"No evidence of {presence_tech} was found in the indexed repository."
                ),
                sources=[],
                context_insufficient=False,
                model=None,
            )

    if (
        index_ready
        and analysis_ctx.facts
        and (
            analysis_ctx.wants_code
            or analysis_ctx.wants_explanation
            or "symbols" in analysis_ctx.topics
            or (selection is not None and selection.wants_source)
        )
    ):
        refs = analysis_ctx.supporting_refs()
        if refs:
            support_rows = await asyncio.to_thread(
                retrieve_supporting_chunks,
                settings,
                project_id=project_id,
                refs=refs,
                question=retrieval_question,
                max_chunks=MAX_SUPPORTING_CHUNKS,
            )
            filtered = _merge_contexts(support_rows, filtered)[: CHAT_TOP_K + MAX_SUPPORTING_CHUNKS]

    has_analysis_evidence = bool(analysis_ctx.facts)
    analysis_block = (
        render_analysis_block(analysis_ctx)
        if analysis_ctx.facts or analysis_ctx.notes
        else None
    )
    context_insufficient = (
        len(filtered) == 0 and not bool(stack_metadata) and not has_analysis_evidence
    )
    workspace_context = page_ctx.prompt_section()
    prompt = build_rag_prompt(
        question=question,
        contexts=filtered,
        stack_metadata=stack_metadata,
        analysis_block=analysis_block,
        workspace_context=workspace_context,
    )

    t_llm = time.perf_counter()
    try:
        answer, used_model = await generate_chat_answer(settings=settings, prompt=prompt)
    except GeminiChatError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    llm_s = time.perf_counter() - t_llm
    logger.info(
        "RAG chat timings project=%s retrieve=%.2fs gemini=%.2fs total=%.2fs sources=%s model=%s",
        project_id,
        retrieve_s,
        llm_s,
        retrieve_s + llm_s,
        len(filtered),
        used_model,
    )

    answer_l = answer.lower()
    insufficient_markers = (
        "do not have enough information",
        "insufficient",
        "not enough information",
        "cannot find",
        "no relevant",
        "context may be insufficient",
    )
    no_evidence_of = "no evidence of"
    no_evidence_generic = "no evidence was found in the indexed repository"

    def _source_paths() -> list[str]:
        return [
            str((row.get("metadata") or {}).get("file_path") or "").lower()
            for row in filtered
        ]

    paths = _source_paths()
    has_overview_evidence = any(
        p.endswith("readme.md") or p.endswith("package.json") or p.endswith("pyproject.toml")
        for p in paths
    )
    has_impl_evidence = any(
        p.endswith((".js", ".ts", ".tsx", ".py", ".go", ".java"))
        and not p.endswith(".md")
        for p in paths
    )
    # Analysis findings count as structured evidence alongside detected-stack metadata.
    has_stack_evidence = (
        bool(stack_metadata) or _has_stack_manifest_sources(filtered) or has_analysis_evidence
    )

    def _insufficient(text: str) -> bool:
        # "insufficient data" is a health-category status, not a refusal.
        text = text.replace("insufficient data", "")
        return any(m in text for m in insufficient_markers)

    # One retry when the model over-refuses despite clear overview/impl/stack evidence.
    # Do not retry genuine technology-absence replies ("No evidence of Redis...").
    refused = no_evidence_generic in answer_l or _insufficient(answer_l)
    tech_absence = bool(presence_tech) and no_evidence_of in answer_l
    false_absence = (not presence_tech) and answer_l.startswith("no evidence")
    if (
        (filtered or stack_metadata or has_analysis_evidence)
        and (refused or false_absence)
        and (has_overview_evidence or has_impl_evidence or has_stack_evidence)
        and not tech_absence
    ):
        retry_prompt = (
            build_rag_prompt(
                question=question,
                contexts=filtered,
                stack_metadata=stack_metadata,
                analysis_block=analysis_block,
                workspace_context=workspace_context,
            )
            + "\nIMPORTANT: Relevant repository evidence is already in context"
            + (" (including detected stack metadata)." if stack_metadata else ".")
            + " Answer using that evidence and cite file paths when available. "
            "Do not say that no evidence was found.\nAnswer:"
        )
        try:
            answer, used_model = await generate_chat_answer(settings=settings, prompt=retry_prompt)
            answer_l = answer.lower()
        except GeminiChatError:
            pass

    if not filtered and not stack_metadata and not has_analysis_evidence:
        answer = "No evidence was found in the indexed repository."
        context_insufficient = True
    elif presence_tech and no_evidence_of in answer_l:
        context_insufficient = False
    elif no_evidence_generic in answer_l and not (
        has_overview_evidence or has_impl_evidence or has_stack_evidence
    ):
        context_insufficient = True
    elif (not presence_tech) and answer_l.startswith("no evidence") and (
        has_overview_evidence or has_impl_evidence or has_stack_evidence
    ):
        # Over-refusal still present after retry; keep sources visible to the user.
        context_insufficient = True
    elif _insufficient(answer_l) and no_evidence_of not in answer_l:
        if len(answer.strip()) < 200 and not (
            has_overview_evidence or has_impl_evidence or has_stack_evidence
        ):
            answer = "No evidence was found in the indexed repository."
        context_insufficient = True
    else:
        context_insufficient = False
        if no_evidence_generic in answer_l and (
            has_overview_evidence or has_impl_evidence or has_stack_evidence
        ):
            context_insufficient = True

    sources: list[ChatSource] = []
    for row in filtered:
        meta = row.get("metadata") or {}
        excerpt = (row.get("document") or "")[:360]
        sources.append(
            ChatSource(
                file_path=str(meta.get("file_path") or "unknown"),
                language=meta.get("language"),
                symbol=meta.get("symbol"),
                start_line=meta.get("start_line"),
                end_line=meta.get("end_line"),
                excerpt=excerpt,
                score=row.get("score"),
                supports=list(row.get("supports") or []),
            )
        )

    return ChatResponse(
        project_id=project_id,
        answer=answer,
        sources=sources,
        context_insufficient=context_insufficient,
        model=used_model,
        analysis_findings=_findings_for_response(analysis_ctx.facts, answer),
        analysis_notes=list(analysis_ctx.notes),
        context_applied=page_ctx.applied_label,
    )


def _merge_contexts(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Concatenate context rows, keeping the first occurrence of each chunk."""
    merged: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group:
            meta = row.get("metadata") or {}
            key = str(
                row.get("id")
                or f"{meta.get('file_path')}:{meta.get('start_line')}-{meta.get('end_line')}"
            )
            if key in index:
                existing = index[key]
                for finding_id in row.get("supports") or []:
                    existing.setdefault("supports", [])
                    if finding_id not in existing["supports"]:
                        existing["supports"].append(finding_id)
                continue
            index[key] = row
            merged.append(row)
    return merged


_CITATION_GROUP_RE = re.compile(r"\[([^\]]+)\]")
_FINDING_ID_RE = re.compile(r"\bA\d+\b")


def _findings_for_response(facts: list[AnalysisFact], answer: str) -> list[AnalysisFinding]:
    """Findings cited in the answer; all provided findings if the answer cites none."""
    cited: set[str] = set()
    for group in _CITATION_GROUP_RE.finditer(answer):
        cited.update(_FINDING_ID_RE.findall(group.group(1)))
    selected = [f for f in facts if f.id in cited] or facts
    return [
        AnalysisFinding(
            id=fact.id,
            kind=fact.kind,
            title=fact.title,
            detail=fact.detail,
            file_refs=[
                AnalysisFileRef(file_path=r.file_path, line=r.line, end_line=r.end_line)
                for r in fact.file_refs
            ],
        )
        for fact in selected
    ]


def _analysis_unavailable_response(project_id: str, notes: list[str]) -> ChatResponse:
    return ChatResponse(
        project_id=project_id,
        answer="I can't answer this from stored analysis results. " + " ".join(notes),
        sources=[],
        context_insufficient=True,
        model=None,
        analysis_findings=[],
        analysis_notes=list(notes),
    )


async def delete_project_rag(settings: Settings, db: AsyncIOMotorDatabase, project_id: str) -> None:
    await db.rag_index_status.delete_one({"project_id": project_id})
    await asyncio.to_thread(delete_project_chunks, settings, project_id)
