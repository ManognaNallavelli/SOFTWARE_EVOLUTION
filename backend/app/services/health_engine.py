"""Health Analysis Engine — scores derived only from structural analysis evidence."""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

from app.schemas.analysis import AnalysisFile, AnalysisRoute, RepositoryAnalysisPayload
from app.schemas.health_report import (
    ArchitectureOverview,
    HealthCategoryResult,
    HealthIssue,
    HealthRecommendation,
    HealthReport,
)

CATEGORY_WEIGHTS = {
    "code_quality": 0.15,
    "maintainability": 0.15,
    "architecture": 0.15,
    "testing": 0.15,
    "security": 0.10,
    "documentation": 0.10,
    "dependency_health": 0.10,
    "technical_debt": 0.10,
}

LARGE_FILE_BYTES = 150_000
VERY_LARGE_FILE_BYTES = 400_000


def _clamp(score: float) -> int:
    return int(max(0, min(100, round(score))))


def _status_label(score: int | None) -> str:
    if score is None:
        return "Insufficient data"
    if score >= 80:
        return "Healthy"
    if score >= 60:
        return "Moderate"
    if score >= 40:
        return "Needs Improvement"
    return "Critical"


def _path_role(path: str, files_by_path: dict[str, AnalysisFile]) -> str:
    file_meta = files_by_path.get(path)
    if file_meta and file_meta.code_role:
        return file_meta.code_role
    parts = {p.lower() for p in PurePosixPath(path).parts}
    if parts & {"test", "tests", "testing", "__tests__", "spec", "specs"}:
        return "test"
    if parts & {"example", "examples", "sample", "samples", "demo", "demos"}:
        return "example"
    if parts & {"docs", "doc", "documentation"}:
        return "documentation"
    return "production"


def _top_level_modules(files: list[AnalysisFile], limit: int = 12) -> list[str]:
    counts: Counter[str] = Counter()
    for file in files:
        if file.code_role not in {"production", "test"}:
            continue
        parts = PurePosixPath(file.path).parts
        if not parts:
            continue
        if len(parts) == 1:
            continue
        counts[parts[0]] += 1
    return [name for name, _ in counts.most_common(limit)]


def calculate_code_quality(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    files = analysis.files
    source_files = [f for f in files if f.code_role == "production" and f.category in {
        "source", "api", "service", "data_access", "frontend_component"
    }]
    if not source_files and not analysis.summary.symbol_count:
        return HealthCategoryResult(
            score=None,
            status="insufficient_data",
            summary="Not enough production source evidence to score code quality.",
        )

    score = 72.0
    issues: list[str] = []
    strengths: list[str] = []

    large = [f for f in source_files if f.size >= LARGE_FILE_BYTES]
    very_large = [f for f in source_files if f.size >= VERY_LARGE_FILE_BYTES]
    if very_large:
        score -= min(25, 8 * len(very_large))
        issues.append(f"{len(very_large)} very large production file(s) (≥400KB).")
    elif large:
        score -= min(15, 4 * len(large))
        issues.append(f"{len(large)} large production file(s) (≥150KB).")

    if analysis.summary.symbol_count > 0:
        score += 8
        strengths.append(f"Extracted {analysis.summary.symbol_count} code symbols from supported languages.")
    if analysis.summary.deep_analysis_languages:
        strengths.append(
            "Deep structural parsing available for: "
            + ", ".join(analysis.summary.deep_analysis_languages)
        )
        score += 4
    if analysis.summary.truncated:
        score -= 10
        issues.append("Repository walk was truncated; quality signals may be incomplete.")

    lang_count = len(analysis.summary.languages)
    if lang_count >= 2:
        strengths.append(f"Multiple languages detected ({lang_count}).")
        score += 3

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Based on production file sizes, symbol extraction, and language coverage.",
        issues=issues,
        strengths=strengths,
    )


def calculate_maintainability(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    production = [f for f in analysis.files if f.code_role == "production"]
    if not production:
        return HealthCategoryResult(
            score=None,
            status="insufficient_data",
            summary="No production files available to assess maintainability.",
        )

    score = 70.0
    issues: list[str] = []
    strengths: list[str] = []

    avg_size = sum(f.size for f in production) / max(1, len(production))
    if avg_size > 40_000:
        score -= 15
        issues.append(f"High average production file size ({int(avg_size / 1024)}KB).")
    elif avg_size < 12_000:
        score += 8
        strengths.append("Production files are relatively small on average.")

    dirs = max(1, analysis.summary.total_directories)
    files_per_dir = analysis.summary.total_files / dirs
    if files_per_dir > 25:
        score -= 10
        issues.append("Many files per directory — structure may be flat or crowded.")
    elif 3 <= files_per_dir <= 15:
        score += 8
        strengths.append("Directory layout looks reasonably modular.")

    modules = _top_level_modules(analysis.files)
    if len(modules) >= 3:
        score += 6
        strengths.append(f"Clear top-level packaging ({', '.join(modules[:5])}).")

    symbols_per_file = analysis.summary.symbol_count / max(1, len(production))
    if symbols_per_file > 40:
        score -= 8
        issues.append("High symbol density — some modules may be doing too much.")

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Based on file size distribution, directory modularity, and symbol density.",
        issues=issues,
        strengths=strengths,
    )


def calculate_architecture_health(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    detections = analysis.detections
    production_routes = [r for r in detections.api_routes if r.code_role == "production"]
    layered = [
        bool(detections.frontend_components),
        bool(detections.backend_services),
        bool(detections.data_access_modules),
        bool(production_routes),
        bool(detections.configuration_files),
    ]
    if sum(1 for x in layered if x) == 0 and analysis.summary.total_files < 5:
        return HealthCategoryResult(
            score=None,
            status="insufficient_data",
            summary="Too little structural signal to score architecture.",
        )

    score = 60.0
    issues: list[str] = []
    strengths: list[str] = []

    layer_count = sum(1 for x in layered if x)
    score += layer_count * 6
    if layer_count >= 3:
        strengths.append("Multiple architectural layers detected (UI/API/data/config).")
    elif layer_count <= 1:
        issues.append("Limited layering signals — architecture may be monolithic or unclear.")
        score -= 5

    if production_routes:
        strengths.append(f"{len(production_routes)} production API route(s) detected.")
        score += 8
    test_example_routes = [r for r in detections.api_routes if r.code_role in {"test", "example"}]
    if test_example_routes and not production_routes:
        issues.append(
            f"{len(test_example_routes)} route(s) found only in tests/examples — not counted as production API."
        )
        score -= 6

    if detections.integrations:
        strengths.append("External integrations inferred from imports: " + ", ".join(detections.integrations[:6]))
        score += 4

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Based on detected layers, production routes, and integration imports.",
        issues=issues,
        strengths=strengths,
    )


def calculate_testing_health(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    production_source = [
        f
        for f in analysis.files
        if f.code_role == "production"
        and f.category in {"source", "api", "service", "data_access", "frontend_component"}
    ]
    test_files = [f for f in analysis.files if f.code_role == "test" or f.category == "test"]
    if not production_source and not test_files:
        return HealthCategoryResult(
            score=None,
            status="insufficient_data",
            summary="No production or test files found to assess testing.",
        )

    score = 40.0
    issues: list[str] = []
    strengths: list[str] = []
    ratio = len(test_files) / max(1, len(production_source))

    if not test_files:
        score = 25
        issues.append("No test files detected.")
    elif ratio < 0.1:
        score = 45
        issues.append(f"Low test presence ({len(test_files)} tests vs {len(production_source)} production source files).")
    elif ratio < 0.25:
        score = 65
        strengths.append("Some tests are present.")
        issues.append("Test coverage by file count is modest.")
    elif ratio < 0.5:
        score = 80
        strengths.append("Solid test file presence relative to production source.")
    else:
        score = 90
        strengths.append("Strong test organization and file presence.")

    if any("tests/" in f.path.replace("\\", "/") or f.path.startswith("test/") for f in test_files):
        strengths.append("Dedicated test directories detected.")
        score += 4

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Based on test vs production source file counts (not runtime coverage).",
        issues=issues,
        strengths=strengths,
    )


def calculate_security_health(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    """Conservative score from filesystem evidence only — no vulnerability scanning."""
    issues: list[str] = []
    strengths: list[str] = []
    score = 70.0

    sensitive_names = []
    for file in analysis.files:
        name = PurePosixPath(file.path).name.lower()
        if name in {".env", ".env.local", ".env.production", "id_rsa", "credentials.json", "secrets.json"}:
            sensitive_names.append(file.path)
        if name.endswith(".pem") or name.endswith(".key"):
            sensitive_names.append(file.path)

    if sensitive_names:
        score -= min(35, 12 * len(sensitive_names))
        issues.append(
            "Potentially sensitive files present in the repository tree: "
            + ", ".join(sensitive_names[:5])
        )
    else:
        strengths.append("No common secret filenames detected in the analyzed tree.")

    if any(PurePosixPath(f.path).name.lower() == ".env.example" for f in analysis.files):
        strengths.append("`.env.example` present — helps avoid committing real secrets.")
        score += 8

    if analysis.summary.dependency_manifests:
        strengths.append("Dependency manifests found (needed for future vulnerability checks).")
    else:
        issues.append("No dependency manifests found — dependency security cannot be assessed deeply.")
        score -= 5

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Based on sensitive filenames and env-example presence only (no CVE scanning).",
        issues=issues,
        strengths=strengths,
    )


def calculate_documentation_health(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    docs = [f for f in analysis.files if f.code_role == "documentation" or f.category == "docs"]
    score = 35.0
    issues: list[str] = []
    strengths: list[str] = []

    if analysis.summary.has_readme:
        score += 40
        strengths.append("README present.")
    else:
        issues.append("No README detected.")

    if docs:
        score += min(20, 3 * len(docs))
        strengths.append(f"{len(docs)} documentation file(s) detected.")
    elif analysis.summary.has_readme:
        issues.append("Limited docs beyond README.")

    if any("docs/" in f.path.replace("\\", "/") for f in docs):
        strengths.append("Dedicated docs directory found.")
        score += 5

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Based on README and documentation file presence.",
        issues=issues,
        strengths=strengths,
    )


def calculate_dependency_health(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    manifests = analysis.summary.dependency_manifests or [
        f.path for f in analysis.files if f.category == "dependency_manifest"
    ]
    languages = {lang.language for lang in analysis.summary.languages}
    issues: list[str] = []
    strengths: list[str] = []

    if not manifests:
        if languages & {"python", "javascript", "typescript", "java", "go", "rust", "ruby", "php"}:
            return HealthCategoryResult(
                score=35,
                status="scored",
                summary="Expected dependency manifests for detected languages were not found.",
                issues=["Missing dependency manifest for a language-heavy repository."],
                strengths=[],
            )
        return HealthCategoryResult(
            score=None,
            status="insufficient_data",
            summary="No dependency manifests or language ecosystem signals to score.",
        )

    score = 75.0
    strengths.append(f"Dependency manifests: {', '.join(manifests[:8])}")
    if len(manifests) >= 2:
        strengths.append("Multiple dependency ecosystems declared.")
        score += 5

    if "python" in languages and not any("requirements" in m or "pyproject" in m or "pipfile" in m for m in manifests):
        issues.append("Python detected but no requirements/pyproject-style manifest found.")
        score -= 12
    if languages & {"javascript", "typescript"} and not any("package.json" in m for m in manifests):
        issues.append("JS/TS detected but package.json not found among manifests.")
        score -= 12

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Based on presence and consistency of dependency manifests (not package age/CVEs).",
        issues=issues,
        strengths=strengths,
    )


def calculate_technical_debt(analysis: RepositoryAnalysisPayload) -> HealthCategoryResult:
    production = [f for f in analysis.files if f.code_role == "production"]
    if not production:
        return HealthCategoryResult(
            score=None,
            status="insufficient_data",
            summary="Insufficient production code to estimate technical debt.",
        )

    # Higher score = healthier (less debt), matching other categories.
    score = 75.0
    issues: list[str] = []
    strengths: list[str] = []

    large = [f for f in production if f.size >= LARGE_FILE_BYTES]
    if large:
        score -= min(20, 5 * len(large))
        issues.append(f"{len(large)} oversized production file(s) increase change risk.")

    test_files = [f for f in analysis.files if f.code_role == "test"]
    prod_source = [
        f
        for f in production
        if f.category in {"source", "api", "service", "data_access", "frontend_component"}
    ]
    if prod_source and len(test_files) / max(1, len(prod_source)) < 0.15:
        score -= 12
        issues.append("Sparse tests relative to production source contribute to debt.")

    example_files = [f for f in analysis.files if f.code_role == "example"]
    if example_files and len(example_files) > len(prod_source):
        issues.append("Example/demo code outweighs production source volume.")
        score -= 6

    if analysis.summary.truncated:
        score -= 8
        issues.append("Incomplete walk suggests the repository may be large/complex.")

    if not issues:
        strengths.append("No strong structural debt signals from file/test metrics.")
        score += 5

    return HealthCategoryResult(
        score=_clamp(score),
        status="scored",
        summary="Inverse structural-debt estimate from large files, test gaps, and complexity signals.",
        issues=issues,
        strengths=strengths,
    )


def calculate_overall_health(categories: dict[str, HealthCategoryResult]) -> tuple[int | None, str]:
    weighted = 0.0
    total_weight = 0.0
    for key, weight in CATEGORY_WEIGHTS.items():
        result = categories.get(key)
        if result is None or result.status != "scored" or result.score is None:
            continue
        weighted += result.score * weight
        total_weight += weight
    if total_weight == 0:
        return None, "Insufficient data"
    score = _clamp(weighted / total_weight)
    return score, _status_label(score)


def build_architecture_overview(analysis: RepositoryAnalysisPayload) -> ArchitectureOverview:
    files_by_path = {f.path: f for f in analysis.files}
    production_routes = [r for r in analysis.detections.api_routes if (r.code_role or _path_role(r.file_path, files_by_path)) == "production"]
    other_routes = [
        r
        for r in analysis.detections.api_routes
        if (r.code_role or _path_role(r.file_path, files_by_path)) in {"test", "example"}
    ]

    api_layer = sorted(
        {
            f"{r.method} {r.path or '(path unknown)'} ({r.file_path})"
            for r in production_routes[:25]
        }
    )
    notes = []
    if other_routes:
        notes.append(
            f"{len(other_routes)} route(s) classified as test/example and excluded from production API overview."
        )

    return ArchitectureOverview(
        main_technologies=[lang.language for lang in analysis.summary.languages[:8]],
        major_modules=_top_level_modules(analysis.files),
        api_layer=api_layer,
        data_layer=analysis.detections.data_access_modules[:15],
        test_layer=analysis.detections.tests[:15],
        important_dependencies=analysis.summary.dependency_manifests[:10]
        or analysis.summary.important_files[:10],
        production_route_count=len(production_routes),
        test_or_example_route_count=len(other_routes),
        notes=notes,
    )


def build_health_report(analysis: RepositoryAnalysisPayload) -> HealthReport:
    categories = {
        "code_quality": calculate_code_quality(analysis),
        "maintainability": calculate_maintainability(analysis),
        "architecture": calculate_architecture_health(analysis),
        "testing": calculate_testing_health(analysis),
        "security": calculate_security_health(analysis),
        "documentation": calculate_documentation_health(analysis),
        "dependency_health": calculate_dependency_health(analysis),
        "technical_debt": calculate_technical_debt(analysis),
    }

    overall, status = calculate_overall_health(categories)
    strengths: list[str] = []
    issues: list[HealthIssue] = []
    recommendations: list[HealthRecommendation] = []

    for key, result in categories.items():
        for item in result.strengths:
            if item not in strengths:
                strengths.append(item)
        for issue_text in result.issues:
            severity = "medium"
            if key in {"security", "testing"} and result.score is not None and result.score < 40:
                severity = "high"
            if key == "security" and "sensitive" in issue_text.lower():
                severity = "critical"
            if key == "testing" and "No test files" in issue_text:
                severity = "high"
            if result.score is not None and result.score < 40 and severity == "medium":
                severity = "high"
            issues.append(
                HealthIssue(
                    severity=severity,  # type: ignore[arg-type]
                    title=f"{key.replace('_', ' ').title()} finding",
                    detail=issue_text,
                    category=key,
                )
            )

    # Recommendations from scored weaknesses
    for key, result in categories.items():
        if result.status != "scored" or result.score is None:
            continue
        if result.score >= 75:
            continue
        if key == "testing":
            recommendations.append(
                HealthRecommendation(
                    title="Expand automated tests",
                    reason=result.issues[0] if result.issues else "Test presence is below a healthy range.",
                    priority="high" if result.score < 50 else "medium",
                    expected_impact="Improves confidence for refactors and reduces regression risk.",
                    category=key,
                )
            )
        elif key == "documentation":
            recommendations.append(
                HealthRecommendation(
                    title="Improve project documentation",
                    reason=result.issues[0] if result.issues else "Documentation signals are weak.",
                    priority="medium",
                    expected_impact="Helps onboarding and clarifies system intent.",
                    category=key,
                )
            )
        elif key in {"maintainability", "technical_debt", "code_quality"}:
            recommendations.append(
                HealthRecommendation(
                    title="Refactor complex or oversized modules",
                    reason=result.issues[0] if result.issues else "Structural complexity indicators are elevated.",
                    priority="medium" if result.score >= 50 else "high",
                    expected_impact="Improves maintainability and reduces technical debt.",
                    category=key,
                )
            )
        elif key == "architecture":
            recommendations.append(
                HealthRecommendation(
                    title="Clarify architectural boundaries",
                    reason=result.issues[0] if result.issues else "Layering signals are limited.",
                    priority="medium",
                    expected_impact="Makes ownership of API, data, and UI concerns clearer.",
                    category=key,
                )
            )
        elif key == "security":
            recommendations.append(
                HealthRecommendation(
                    title="Review sensitive files and secret handling",
                    reason=result.issues[0] if result.issues else "Security filesystem signals need attention.",
                    priority="high",
                    expected_impact="Reduces risk of leaking credentials or local secrets.",
                    category=key,
                )
            )
        elif key == "dependency_health":
            recommendations.append(
                HealthRecommendation(
                    title="Normalize dependency manifests",
                    reason=result.issues[0] if result.issues else "Dependency declaration looks incomplete.",
                    priority="medium",
                    expected_impact="Makes installs reproducible and enables future vulnerability checks.",
                    category=key,
                )
            )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    issues.sort(key=lambda i: severity_order.get(i.severity, 9))

    return HealthReport(
        overall_score=overall,
        status=status,  # type: ignore[arg-type]
        categories=categories,
        strengths=strengths[:12],
        issues=issues[:20],
        recommendations=recommendations[:10],
        architecture_overview=build_architecture_overview(analysis),
        scoring_notes=[
            "Scores are explainable heuristics from structural analysis only.",
            "Security does not include CVE or dependency vulnerability scanning.",
            "Testing score uses file presence ratios, not execution coverage.",
            "API routes under tests/ and examples/ are classified and excluded from production API counts.",
        ],
    )


def annotate_route_roles(
    routes: list[AnalysisRoute],
    files: list[AnalysisFile],
) -> list[AnalysisRoute]:
    files_by_path = {f.path: f for f in files}
    annotated: list[AnalysisRoute] = []
    for route in routes:
        role = route.code_role or _path_role(route.file_path, files_by_path)
        annotated.append(route.model_copy(update={"code_role": role}))
    return annotated
