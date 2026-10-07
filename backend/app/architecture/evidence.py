"""Shared evidence extraction for architecture brief + deterministic graphs."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from app.schemas.analysis import AnalysisFile, RepositoryAnalysisPayload

SKIP_TOP_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    "htmlcov",
    "coverage",
}


def package_key(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if not parts:
        return None
    if len(parts) == 1:
        return None
    top = parts[0]
    if top.lower() in SKIP_TOP_DIRS:
        return None
    return top


def classify_package_role(files: list[AnalysisFile]) -> str:
    """Map a package's files to a coarse architectural kind (evidence-only)."""
    cats = Counter(f.category for f in files)
    roles = Counter(f.code_role for f in files)
    if roles.get("test", 0) and roles.get("test", 0) >= max(1, len(files) // 2):
        return "test"
    if cats.get("frontend_component", 0) >= 2 or (
        cats.get("frontend_component", 0) and not cats.get("service", 0)
    ):
        return "frontend"
    if cats.get("data_access", 0) >= 1:
        return "database"
    if cats.get("api", 0) >= 1:
        return "api"
    if cats.get("service", 0) >= 1:
        return "service"
    if cats.get("config", 0) + cats.get("dependency_manifest", 0) >= max(1, len(files) // 2):
        return "config"
    # Heuristic names from path evidence already in file list
    name = (files[0].path.split("/")[0] if files else "").lower()
    if name in {"src", "lib", "app", "core", "pkg", "package"}:
        return "backend"
    if name in {"tests", "test", "testing", "specs", "spec"}:
        return "test"
    if name in {"docs", "doc", "documentation", "examples", "example", "samples"}:
        return "other"
    return "module"


def build_package_summaries(
    analysis: RepositoryAnalysisPayload,
    *,
    limit: int = 14,
) -> list[dict[str, Any]]:
    by_pkg: dict[str, list[AnalysisFile]] = defaultdict(list)
    for f in analysis.files:
        if f.code_role not in {"production", "test", "configuration"}:
            continue
        key = package_key(f.path)
        if not key:
            continue
        by_pkg[key].append(f)

    ranked = sorted(by_pkg.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:limit]
    summaries: list[dict[str, Any]] = []
    for name, files in ranked:
        sample = sorted(files, key=lambda f: f.path)[:8]
        symbols = [
            s.name
            for s in analysis.symbols
            if s.file_path.startswith(f"{name}/") and s.type in {"class", "function", "interface"}
        ][:8]
        summaries.append(
            {
                "name": name,
                "file_count": len(files),
                "suggested_kind": classify_package_role(files),
                "categories": dict(Counter(f.category for f in files).most_common(6)),
                "code_roles": dict(Counter(f.code_role for f in files).most_common(4)),
                "sample_files": [f.path for f in sample],
                "sample_symbols": symbols,
            }
        )
    return summaries


def build_internal_import_links(
    analysis: RepositoryAnalysisPayload,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Package→package import edges inferred only from recorded imports."""
    counts: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)

    package_names = {p["name"] for p in build_package_summaries(analysis, limit=40)}

    for imp in analysis.imports:
        src = package_key(imp.source_file)
        if not src:
            continue
        module = (imp.imported_module or "").replace("\\", "/")
        # Resolve first segment that matches a known package / relative import
        target: str | None = None
        if module.startswith("."):
            # relative — stay within same package unless dots escape; keep same pkg skip
            continue
        first = module.split(".")[0].split("/")[0]
        if first in package_names and first != src:
            target = first
        else:
            # imported path may be package.submodule
            for pkg in package_names:
                if module == pkg or module.startswith(f"{pkg}.") or module.startswith(f"{pkg}/"):
                    if pkg != src:
                        target = pkg
                        break
        if not target:
            continue
        key = (src, target)
        counts[key] += 1
        if len(examples[key]) < 3:
            examples[key].append(f"{imp.source_file} imports {imp.imported_module}")

    links: list[dict[str, Any]] = []
    for (src, tgt), count in counts.most_common(limit):
        links.append(
            {
                "from_package": src,
                "to_package": tgt,
                "import_count": count,
                "evidence": examples[(src, tgt)],
            }
        )
    return links


def production_route_entries(analysis: RepositoryAnalysisPayload, *, limit: int = 30) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in analysis.detections.api_routes:
        if (r.code_role or "production") != "production":
            continue
        rows.append(
            {
                "method": r.method,
                "path": r.path,
                "file_path": r.file_path,
                "function": r.function,
                "evidence": r.evidence,
                "package": package_key(r.file_path),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def dominant_application_kind(analysis: RepositoryAnalysisPayload) -> str:
    langs = {lang.language.lower() for lang in analysis.summary.languages}
    if analysis.detections.frontend_components and not analysis.detections.backend_services:
        if langs & {"javascript", "typescript", "tsx", "jsx"}:
            return "frontend"
    if langs & {"python", "go", "java", "ruby", "php", "csharp", "c#", "rust"}:
        return "backend"
    if langs & {"javascript", "typescript"} and analysis.detections.frontend_components:
        return "frontend"
    return "backend"
