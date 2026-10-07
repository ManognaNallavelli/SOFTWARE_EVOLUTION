"""Orchestrate architecture generation from stored analysis + Gemini."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.architecture.deterministic import build_deterministic_architecture
from app.architecture.gemini_client import GeminiArchitectureError, generate_architecture_graph
from app.architecture.prompt_builder import build_architecture_brief, build_gemini_prompt
from app.architecture.validator import validate_architecture_graph
from app.config import Settings, get_settings
from app.schemas.analysis import RepositoryAnalysisPayload
from app.schemas.architecture import ArchitectureDocumentResponse, ArchitectureGenerateResponse

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_architecture_document(
    db: AsyncIOMotorDatabase,
    project_id: str,
) -> ArchitectureDocumentResponse:
    doc = await db.architectures.find_one({"project_id": project_id})
    if doc is None:
        return ArchitectureDocumentResponse(
            project_id=project_id,
            status="not_generated",
            graph=None,
            source=None,
            gemini_model=None,
            analysis_project_id=None,
            analyzed_at=None,
            generated_at=None,
            updated_at=None,
            error=None,
            error_code=None,
            version=0,
        )

    graph = None
    if doc.get("graph"):
        from app.schemas.architecture import ArchitectureGraph

        try:
            graph = ArchitectureGraph.model_validate(doc["graph"])
        except Exception:  # noqa: BLE001
            logger.exception("Stored architecture graph failed validation for %s", project_id)

    return ArchitectureDocumentResponse(
        project_id=project_id,
        status=doc.get("status", "completed"),
        graph=graph,
        source=doc.get("source"),
        gemini_model=doc.get("gemini_model"),
        analysis_project_id=doc.get("analysis_project_id") or project_id,
        analyzed_at=doc.get("analyzed_at"),
        generated_at=doc.get("generated_at"),
        updated_at=doc.get("updated_at"),
        error=doc.get("error"),
        error_code=doc.get("error_code"),
        version=int(doc.get("version") or 1),
    )


async def generate_project_architecture(
    db: AsyncIOMotorDatabase,
    *,
    project: dict[str, Any],
    settings: Settings | None = None,
    prefer_deterministic: bool = False,
) -> ArchitectureGenerateResponse:
    settings = settings or get_settings()
    project_id = project["id"]

    analysis_doc = await db.repository_analyses.find_one({"project_id": project_id})
    if analysis_doc is None or not analysis_doc.get("analysis"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "analysis_required",
                "message": "Run repository analysis before generating architecture.",
            },
        )
    if analysis_doc.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "analysis_not_ready",
                "message": "Repository analysis is not completed yet.",
            },
        )

    analysis = RepositoryAnalysisPayload.model_validate(analysis_doc["analysis"])
    now = _utcnow()
    version = int((await db.architectures.find_one({"project_id": project_id}) or {}).get("version") or 0) + 1

    await db.architectures.update_one(
        {"project_id": project_id},
        {
            "$set": {
                "project_id": project_id,
                "owner_user_id": project["owner_user_id"],
                "status": "generating",
                "error": None,
                "error_code": None,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    source: Literal["gemini", "deterministic"] = "deterministic"
    gemini_model: str | None = None
    warnings_extra: list[str] = []

    try:
        use_gemini = bool(settings.gemini_api_key.strip()) and not prefer_deterministic
        if use_gemini:
            brief = build_architecture_brief(analysis)
            prompt = build_gemini_prompt(brief)
            raw_graph, gemini_model = await generate_architecture_graph(
                prompt=prompt,
                settings=settings,
            )
            source = "gemini"
        else:
            raw_graph = build_deterministic_architecture(analysis)
            source = "deterministic"
            if not settings.gemini_api_key.strip():
                warnings_extra.append(
                    "GEMINI_API_KEY missing — used evidence-only deterministic architecture."
                )

        graph = validate_architecture_graph(raw_graph, analysis)
        if warnings_extra:
            graph.warnings = [*warnings_extra, *graph.warnings]

        generated_at = _utcnow()
        await db.architectures.update_one(
            {"project_id": project_id},
            {
                "$set": {
                    "status": "completed",
                    "graph": graph.model_dump(),
                    "source": source,
                    "gemini_model": gemini_model,
                    "analysis_project_id": project_id,
                    "analyzed_at": analysis_doc.get("analyzed_at"),
                    "generated_at": generated_at,
                    "updated_at": generated_at,
                    "error": None,
                    "error_code": None,
                    "version": version,
                    "owner_user_id": project["owner_user_id"],
                }
            },
            upsert=True,
        )

        message = (
            "Architecture generated with Gemini."
            if source == "gemini"
            else "Architecture generated from structural analysis (deterministic)."
        )
        return ArchitectureGenerateResponse(
            project_id=project_id,
            status="completed",
            graph=graph,
            source=source,
            gemini_model=gemini_model,
            analysis_project_id=project_id,
            analyzed_at=analysis_doc.get("analyzed_at"),
            generated_at=generated_at,
            updated_at=generated_at,
            error=None,
            error_code=None,
            version=version,
            message=message,
        )
    except GeminiArchitectureError as exc:
        logger.warning("Gemini architecture failed for %s: %s", project_id, exc)
        # Fallback to deterministic so demos still work
        try:
            raw_graph = build_deterministic_architecture(analysis)
            graph = validate_architecture_graph(raw_graph, analysis)
            graph.warnings = [
                f"Gemini failed ({exc.code}): {exc}. Fell back to evidence-only layout.",
                *graph.warnings,
            ]
            generated_at = _utcnow()
            await db.architectures.update_one(
                {"project_id": project_id},
                {
                    "$set": {
                        "status": "completed",
                        "graph": graph.model_dump(),
                        "source": "deterministic",
                        "gemini_model": None,
                        "analysis_project_id": project_id,
                        "analyzed_at": analysis_doc.get("analyzed_at"),
                        "generated_at": generated_at,
                        "updated_at": generated_at,
                        "error": None,
                        "error_code": None,
                        "version": version,
                        "owner_user_id": project["owner_user_id"],
                    }
                },
                upsert=True,
            )
            return ArchitectureGenerateResponse(
                project_id=project_id,
                status="completed",
                graph=graph,
                source="deterministic",
                gemini_model=None,
                analysis_project_id=project_id,
                analyzed_at=analysis_doc.get("analyzed_at"),
                generated_at=generated_at,
                updated_at=generated_at,
                error=None,
                error_code=None,
                version=version,
                message="Gemini unavailable; used evidence-only architecture.",
            )
        except Exception as fallback_exc:  # noqa: BLE001
            logger.exception("Deterministic architecture fallback failed")
            await _mark_failed(db, project_id, str(fallback_exc), "architecture_failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "architecture_failed",
                    "message": str(fallback_exc),
                },
            ) from fallback_exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Architecture generation failed for %s", project_id)
        await _mark_failed(db, project_id, str(exc), "architecture_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "architecture_failed", "message": str(exc)},
        ) from exc


async def _mark_failed(
    db: AsyncIOMotorDatabase,
    project_id: str,
    error: str,
    error_code: str,
) -> None:
    await db.architectures.update_one(
        {"project_id": project_id},
        {
            "$set": {
                "status": "failed",
                "error": error,
                "error_code": error_code,
                "updated_at": _utcnow(),
            }
        },
        upsert=True,
    )
