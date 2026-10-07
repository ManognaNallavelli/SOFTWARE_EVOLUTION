"""Orchestrate clone + structural analysis and persist results."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncio
from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.analyzers.filesystem import read_text_file, walk_repository
from app.analyzers.javascript_basic import analyze_js_ts_source
from app.analyzers.python_ast import analyze_python_source
from app.config import Settings, get_settings
from app.schemas.analysis import (
    AnalysisDetections,
    AnalysisDocumentResponse,
    AnalysisExport,
    AnalysisFile,
    AnalysisImport,
    AnalysisRepositoryInfo,
    AnalysisRoute,
    AnalysisSummary,
    AnalysisSymbol,
    LanguageCount,
    RepositoryAnalysisPayload,
)
from app.services.clone_service import cleanup_clone_path, clone_public_repository
from app.services.github_service import validate_public_github_repository
from app.services.health_engine import annotate_route_roles, build_health_report
from app.services.stack_detection import derive_detected_stack
from app.schemas.health_report import HealthReport

logger = logging.getLogger(__name__)

# GitHub "size" is approximate KB. Above this, warn/fail early for local demo machines.
LARGE_REPO_SIZE_KB = 400_000

INTEGRATION_HINTS = {
    "mongodb": ("pymongo", "motor", "mongoose", "mongodb"),
    "postgres": ("psycopg", "sqlalchemy", "prisma", "pg", "postgres"),
    "redis": ("redis", "ioredis"),
    "aws": ("boto3", "@aws-sdk", "aws-sdk"),
    "stripe": ("stripe",),
    "firebase": ("firebase",),
    "openai": ("openai",),
    "google": ("google.generativeai", "@google/generative-ai", "google-auth"),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def update_project_status(
    db: AsyncIOMotorDatabase,
    project_id: str,
    status_value: str,
    *,
    error: str | None = None,
    error_code: str | None = None,
) -> None:
    update: dict[str, Any] = {
        "status": status_value,
        "updated_at": _utcnow(),
    }
    if error is not None:
        update["last_error"] = error
    if error_code is not None:
        update["last_error_code"] = error_code
    if status_value == "completed":
        update["last_error"] = None
        update["last_error_code"] = None
    await db.projects.update_one({"_id": ObjectId(project_id)}, {"$set": update})


async def get_analysis_document(
    db: AsyncIOMotorDatabase,
    project_id: str,
) -> AnalysisDocumentResponse:
    doc = await db.repository_analyses.find_one({"project_id": project_id})
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    project_status = (project or {}).get("status", "created")

    if doc is None:
        return AnalysisDocumentResponse(
            project_id=project_id,
            status=project_status if project_status in {"validating", "cloning", "analyzing", "failed"} else "not_analyzed",
            analysis=None,
            health_report=None,
            health_error=None,
            error=(project or {}).get("last_error"),
            error_code=(project or {}).get("last_error_code"),
            analyzed_at=None,
            updated_at=(project or {}).get("updated_at"),
        )

    analysis_payload = None
    if doc.get("analysis"):
        analysis_payload = RepositoryAnalysisPayload.model_validate(doc["analysis"])

    health_report = None
    if doc.get("health_report"):
        try:
            health_report = HealthReport.model_validate(doc["health_report"])
        except Exception:  # noqa: BLE001
            logger.exception("Stored health_report failed validation for %s", project_id)

    return AnalysisDocumentResponse(
        project_id=project_id,
        status=doc.get("status") or project_status,
        analysis=analysis_payload,
        health_report=health_report,
        health_error=doc.get("health_error"),
        error=doc.get("error"),
        error_code=doc.get("error_code"),
        analyzed_at=doc.get("analyzed_at"),
        updated_at=doc.get("updated_at"),
    )


async def run_project_analysis(
    db: AsyncIOMotorDatabase,
    *,
    project: dict[str, Any],
    settings: Settings | None = None,
) -> AnalysisDocumentResponse:
    settings = settings or get_settings()
    project_id = project["id"]
    clone_path: Path | None = None

    claimed = await db.projects.find_one_and_update(
        {
            "_id": ObjectId(project_id),
            "status": {"$nin": ["validating", "cloning", "analyzing"]},
        },
        {
            "$set": {
                "status": "validating",
                "updated_at": _utcnow(),
                "last_error": None,
                "last_error_code": None,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        current = await db.projects.find_one({"_id": ObjectId(project_id)})
        if current and current.get("status") in {"validating", "cloning", "analyzing"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "analysis_in_progress",
                    "message": "Analysis is already in progress for this project.",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "project_not_found", "message": "Project not found."},
        )

    await db.repository_analyses.update_one(
        {"project_id": project_id},
        {
            "$set": {
                "project_id": project_id,
                "owner_user_id": project["owner_user_id"],
                "status": "validating",
                "error": None,
                "error_code": None,
                "updated_at": _utcnow(),
            },
            "$setOnInsert": {"created_at": _utcnow()},
        },
        upsert=True,
    )

    try:
        validated = await validate_public_github_repository(project["normalized_github_url"])

        if validated.size_kb >= LARGE_REPO_SIZE_KB:
            size_mb = validated.size_kb / 1024
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "repository_too_large",
                    "message": (
                        f"Repository '{validated.full_name}' is too large for local analysis "
                        f"(~{size_mb:.0f} MB on GitHub). Use a smaller public repo for demos "
                        "(for example axios/axios or a small personal project)."
                    ),
                },
            )

        await update_project_status(db, project_id, "cloning")
        await db.repository_analyses.update_one(
            {"project_id": project_id},
            {"$set": {"status": "cloning", "updated_at": _utcnow()}},
        )

        branch = project.get("github_default_branch") or validated.default_branch
        clone = await asyncio.to_thread(
            clone_public_repository,
            settings=settings,
            project_id=project_id,
            github_url=validated.normalized_url,
            branch=branch,
        )
        clone_path = clone.local_path

        await update_project_status(db, project_id, "analyzing")
        await db.repository_analyses.update_one(
            {"project_id": project_id},
            {"$set": {"status": "analyzing", "updated_at": _utcnow()}},
        )

        payload = await asyncio.to_thread(
            analyze_repository_tree,
            project_id=project_id,
            repo_root=clone.local_path,
            repository_url=validated.normalized_url,
            repository_name=validated.repo,
            full_name=validated.full_name,
            branch=clone.branch,
        )

        health_report = None
        health_error = None
        try:
            health_report = build_health_report(payload)
        except Exception as health_exc:  # noqa: BLE001
            logger.exception("Health report generation failed for %s", project_id)
            health_error = f"Health report could not be generated: {health_exc}"

        now = _utcnow()
        await db.repository_analyses.update_one(
            {"project_id": project_id},
            {
                "$set": {
                    "status": "completed",
                    "analysis": payload.model_dump(mode="json"),
                    "health_report": health_report.model_dump(mode="json") if health_report else None,
                    "health_error": health_error,
                    "error": None,
                    "error_code": None,
                    "analyzed_at": now,
                    "updated_at": now,
                    "repository_name": validated.full_name,
                    "branch": clone.branch,
                }
            },
            upsert=True,
        )
        await update_project_status(db, project_id, "completed")

        detected_stack = derive_detected_stack(payload)
        await db.projects.update_one(
            {"_id": ObjectId(project_id)},
            {
                "$set": {
                    "technologies": detected_stack,
                    "updated_at": _utcnow(),
                }
            },
        )

        return await get_analysis_document(db, project_id)

    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail)
            code = str(detail.get("code") or "analysis_failed")
        else:
            message = str(detail)
            code = "analysis_failed"
        await _mark_failed(db, project_id, message, code)
        raise
    except Exception as exc:  # noqa: BLE001 - persist unexpected failures
        logger.exception("Unexpected analysis failure for %s", project_id)
        await _mark_failed(db, project_id, "Unexpected analysis failure.", "internal_error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "internal_error", "message": "Unexpected analysis failure."},
        ) from exc
    finally:
        cleanup_clone_path(clone_path)


async def _mark_failed(
    db: AsyncIOMotorDatabase,
    project_id: str,
    message: str,
    code: str,
) -> None:
    now = _utcnow()
    await update_project_status(db, project_id, "failed", error=message, error_code=code)
    await db.repository_analyses.update_one(
        {"project_id": project_id},
        {
            "$set": {
                "status": "failed",
                "error": message,
                "error_code": code,
                "updated_at": now,
            },
            "$setOnInsert": {
                "project_id": project_id,
                "created_at": now,
                "analysis": None,
            },
        },
        upsert=True,
    )


def analyze_repository_tree(
    *,
    project_id: str,
    repo_root: Path,
    repository_url: str,
    repository_name: str,
    full_name: str,
    branch: str,
) -> RepositoryAnalysisPayload:
    walk = walk_repository(repo_root)

    language_files: Counter[str] = Counter()
    language_bytes: Counter[str] = Counter()
    files: list[AnalysisFile] = []
    symbols: list[AnalysisSymbol] = []
    imports: list[AnalysisImport] = []
    exports: list[AnalysisExport] = []
    routes: list[AnalysisRoute] = []

    frontend_components: list[str] = []
    backend_services: list[str] = []
    data_access: list[str] = []
    configuration_files: list[str] = []
    tests: list[str] = []
    dependency_manifests: list[str] = []
    integration_hits: set[str] = set()

    deep_langs = {"python", "javascript", "typescript"}

    for record in walk.files:
        files.append(
            AnalysisFile(
                path=record.path,
                language=record.language,
                size=record.size,
                extension=record.extension,
                category=record.category,
                code_role=record.code_role,
            )
        )
        if record.language:
            language_files[record.language] += 1
            language_bytes[record.language] += record.size

        if record.code_role == "production":
            if record.category == "frontend_component":
                frontend_components.append(record.path)
            elif record.category == "service":
                backend_services.append(record.path)
            elif record.category == "data_access":
                data_access.append(record.path)
        if record.category in {"config", "dependency_manifest"}:
            configuration_files.append(record.path)
        if record.code_role == "test" or record.category == "test":
            tests.append(record.path)
        if record.category == "dependency_manifest":
            dependency_manifests.append(record.path)

        if record.is_binary or not record.language:
            continue
        if record.language not in deep_langs:
            continue

        absolute = repo_root / record.path
        source = read_text_file(absolute)
        if source is None:
            continue

        if record.language == "python":
            extracted = analyze_python_source(record.path, source)
            symbols.extend(
                AnalysisSymbol(
                    name=s.name,
                    type=s.type,
                    file_path=s.file_path,
                    start_line=s.start_line,
                    end_line=s.end_line,
                    parent=s.parent,
                )
                for s in extracted.symbols
            )
            imports.extend(
                AnalysisImport(
                    source_file=i.source_file,
                    imported_module=i.imported_module,
                    names=i.names,
                    line=i.line,
                )
                for i in extracted.imports
            )
            exports.extend(
                AnalysisExport(
                    source_file=e.source_file,
                    name=e.name,
                    export_type=e.export_type,
                    line=e.line,
                )
                for e in extracted.exports
            )
            for route in extracted.routes:
                route_dict = dict(route)
                route_dict["code_role"] = record.code_role
                routes.append(AnalysisRoute.model_validate(route_dict))
            integration_hits.update(_detect_integrations_from_imports(extracted.imports))

        elif record.language in {"javascript", "typescript"}:
            extracted = analyze_js_ts_source(record.path, source)
            symbols.extend(
                AnalysisSymbol(
                    name=s.name,
                    type=s.type,
                    file_path=s.file_path,
                    start_line=s.start_line,
                    end_line=s.end_line,
                    parent=s.parent,
                )
                for s in extracted.symbols
            )
            imports.extend(
                AnalysisImport(
                    source_file=i.source_file,
                    imported_module=i.imported_module,
                    names=i.names,
                    line=i.line,
                )
                for i in extracted.imports
            )
            exports.extend(
                AnalysisExport(
                    source_file=e.source_file,
                    name=e.name,
                    export_type=e.export_type,
                    line=e.line,
                )
                for e in extracted.exports
            )
            for route in extracted.routes:
                route_dict = dict(route)
                route_dict["code_role"] = record.code_role
                routes.append(AnalysisRoute.model_validate(route_dict))
            integration_hits.update(_detect_integrations_from_imports(extracted.imports))

    routes = annotate_route_roles(routes, files)
    production_route_count = sum(1 for r in routes if r.code_role == "production")
    test_example_route_count = sum(1 for r in routes if r.code_role in {"test", "example"})

    languages = [
        LanguageCount(
            language=lang,
            file_count=language_files[lang],
            total_bytes=language_bytes[lang],
        )
        for lang in sorted(language_files.keys())
    ]

    summary = AnalysisSummary(
        total_files=len(files),
        total_directories=len(walk.directories),
        languages=languages,
        important_files=walk.important_files,
        has_readme=walk.has_readme,
        dependency_manifests=sorted(set(dependency_manifests)),
        deep_analysis_languages=sorted(deep_langs),
        truncated=walk.truncated,
        symbol_count=len(symbols),
        import_count=len(imports),
        export_count=len(exports),
        route_count=len(routes),
        production_route_count=production_route_count,
        test_or_example_route_count=test_example_route_count,
    )

    detections = AnalysisDetections(
        frontend_components=sorted(set(frontend_components))[:200],
        backend_services=sorted(set(backend_services))[:200],
        api_routes=routes[:300],
        data_access_modules=sorted(set(data_access))[:200],
        configuration_files=sorted(set(configuration_files))[:200],
        tests=sorted(set(tests))[:200],
        integrations=sorted(integration_hits),
    )

    return RepositoryAnalysisPayload(
        project_id=project_id,
        repository=AnalysisRepositoryInfo(
            name=repository_name,
            url=repository_url,
            branch=branch,
            full_name=full_name,
        ),
        summary=summary,
        files=files,
        symbols=symbols[:5000],
        imports=imports[:5000],
        exports=exports[:3000],
        detections=detections,
        limits={
            "max_walk_files": 8000,
            "symbols_stored_cap": 5000,
            "imports_stored_cap": 5000,
            "deep_analysis_languages": sorted(deep_langs),
            "notes": [
                "Python uses the standard ast module.",
                "JavaScript/TypeScript use best-effort regex extraction.",
                "Other languages include file/language metadata only.",
            ],
        },
    )


def _detect_integrations_from_imports(imports: list[Any]) -> set[str]:
    found: set[str] = set()
    modules = []
    for item in imports:
        modules.append(getattr(item, "imported_module", "") or "")
    blob = " ".join(modules).lower()
    for name, hints in INTEGRATION_HINTS.items():
        if any(hint.lower() in blob for hint in hints):
            found.add(name)
    return found
