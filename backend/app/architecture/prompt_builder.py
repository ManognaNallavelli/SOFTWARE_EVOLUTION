"""Build a compact architecture brief from existing RepositoryAnalysis (no full dump)."""

from __future__ import annotations

import json
from typing import Any

from app.architecture.evidence import (
    build_internal_import_links,
    build_package_summaries,
    dominant_application_kind,
    production_route_entries,
)
from app.schemas.analysis import RepositoryAnalysisPayload
from app.schemas.architecture import ArchitectureGraph

MAX_BRIEF_CHARS = 16_000
MAX_FILES = 36
MAX_SYMBOLS = 45
MAX_IMPORTS = 35
MAX_ROUTES = 28
MAX_MODULES = 18


def build_architecture_brief(analysis: RepositoryAnalysisPayload) -> dict[str, Any]:
    """Evidence-only compact JSON for Gemini. Prefer production signals."""

    production_routes = production_route_entries(analysis, limit=MAX_ROUTES)
    test_or_example_route_count = sum(
        1
        for r in analysis.detections.api_routes
        if (r.code_role or "") in {"test", "example"}
    )

    production_files = [
        f
        for f in analysis.files
        if f.code_role == "production"
        and f.category
        in {
            "source",
            "api",
            "service",
            "data_access",
            "frontend_component",
        }
    ]
    production_files_sorted = sorted(production_files, key=lambda f: (f.size, f.path))[:MAX_FILES]

    symbols = [
        {
            "name": s.name,
            "type": s.type,
            "file_path": s.file_path,
            "parent": s.parent,
        }
        for s in analysis.symbols[:MAX_SYMBOLS]
        if not any(
            part in s.file_path.lower()
            for part in ("/test", "/tests/", "/example", "/examples/", "/spec/")
        )
    ]

    imports = [
        {
            "source_file": i.source_file,
            "imported_module": i.imported_module,
            "names": i.names[:8],
        }
        for i in analysis.imports[:MAX_IMPORTS]
    ]

    packages = build_package_summaries(analysis, limit=12)
    import_links = build_internal_import_links(analysis, limit=24)

    brief: dict[str, Any] = {
        "repository": {
            "name": analysis.repository.name,
            "full_name": analysis.repository.full_name,
            "url": analysis.repository.url,
            "branch": analysis.repository.branch,
        },
        "summary": {
            "total_files": analysis.summary.total_files,
            "languages": [
                {"language": lang.language, "file_count": lang.file_count}
                for lang in analysis.summary.languages[:12]
            ],
            "important_files": analysis.summary.important_files[:20],
            "dependency_manifests": analysis.summary.dependency_manifests[:15],
            "has_readme": analysis.summary.has_readme,
            "deep_analysis_languages": analysis.summary.deep_analysis_languages,
            "symbol_count": analysis.summary.symbol_count,
            "import_count": analysis.summary.import_count,
            "production_route_count": analysis.summary.production_route_count,
            "test_or_example_route_count": analysis.summary.test_or_example_route_count
            or test_or_example_route_count,
            "truncated": analysis.summary.truncated,
            "suggested_application_kind": dominant_application_kind(analysis),
        },
        "detections": {
            "frontend_components": analysis.detections.frontend_components[:MAX_MODULES],
            "backend_services": analysis.detections.backend_services[:MAX_MODULES],
            "data_access_modules": analysis.detections.data_access_modules[:MAX_MODULES],
            "configuration_files": analysis.detections.configuration_files[:15],
            "tests_sample": analysis.detections.tests[:12],
            "integrations": analysis.detections.integrations[:15],
            "production_api_routes": production_routes,
        },
        "packages": packages,
        "internal_import_links": import_links,
        "sample_production_files": [
            {
                "path": f.path,
                "language": f.language,
                "category": f.category,
                "code_role": f.code_role,
            }
            for f in production_files_sorted
        ],
        "symbols_sample": symbols,
        "imports_sample": imports,
        "guidance": {
            "prefer_nodes": [
                "application/backend or frontend layer (from languages + detections)",
                "API routes/controllers (production routes only)",
                "services/business logic packages",
                "data/database access modules",
                "configuration",
                "external integrations",
                "tests (if present)",
                "important packages/modules with import relationships",
            ],
            "prefer_edge_types": [
                "imports",
                "calls",
                "exposes",
                "uses",
                "stores",
                "depends_on",
            ],
            "avoid": [
                "generic contains edges when an imports/uses/calls edge is supported",
                "invented databases, frameworks, or services not listed in evidence",
                "treating test/example routes as production API",
            ],
        },
    }

    raw = json.dumps(brief, ensure_ascii=False)
    if len(raw) > MAX_BRIEF_CHARS:
        brief["symbols_sample"] = brief["symbols_sample"][:20]
        brief["imports_sample"] = brief["imports_sample"][:15]
        brief["sample_production_files"] = brief["sample_production_files"][:20]
        brief["packages"] = brief["packages"][:8]
        brief["internal_import_links"] = brief["internal_import_links"][:12]
        brief["_truncated_brief"] = True

    return brief


def build_gemini_prompt(brief: dict[str, Any]) -> str:
    schema_hint = ArchitectureGraph.model_json_schema()
    return f"""You are an expert software architect. Given ONLY the structural analysis brief below,
produce a concise ArchitectureGraph JSON for interactive visualization.

Hard rules:
1. Use ONLY facts present in the brief. Do NOT invent technologies, services, databases, APIs, modules, or relationships.
2. Do NOT infer unsupported dependencies as facts. If evidence is weak, omit the node/edge and optionally add a warning.
3. Every important node and edge MUST include evidence (file paths, import lines, route signatures, detection names, or package samples from the brief).
4. Prefer meaningful architectural relationships over generic "contains" edges. Prefer: imports, calls, exposes, uses, stores, depends_on.
5. Prefer meaningful nodes when evidence exists: frontend/application, backend/application, API routes/controllers, services/business logic, data/database layer, configuration, external integrations, tests, important packages/modules.
6. Do NOT force categories onto repositories that lack evidence for them.
7. Prefer production code. Do not promote test/example routes as production API nodes (test_or_example_route_count is informational only).
8. Use packages[] and internal_import_links[] heavily when detections are sparse — these are evidence-backed.
9. Keep the graph readable: typically 8–20 nodes, focused edges, clear labels.
10. Node kinds must be one of: frontend, backend, service, module, api, database, external, config, test, other.
11. Edge types must be one of: calls, imports, uses, contains, exposes, stores, depends_on.
12. Respond with JSON only matching nodes, edges, summary, warnings.

JSON Schema (informational):
{json.dumps(schema_hint, ensure_ascii=False)[:3500]}

Structural analysis brief:
{json.dumps(brief, ensure_ascii=False)}
"""
