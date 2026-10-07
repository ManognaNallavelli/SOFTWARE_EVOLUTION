"""Derive Detected Stack labels from Phase 2 repository analysis evidence only."""

from __future__ import annotations

from typing import Iterable

from app.schemas.analysis import RepositoryAnalysisPayload

# Manifest path fragments → stack labels (evidence from filenames only).
_MANIFEST_HINTS: tuple[tuple[str, str], ...] = (
    ("package.json", "Node.js"),
    ("package-lock.json", "Node.js"),
    ("yarn.lock", "Node.js"),
    ("pnpm-lock.yaml", "Node.js"),
    ("requirements.txt", "Python"),
    ("pyproject.toml", "Python"),
    ("pipfile", "Python"),
    ("poetry.lock", "Python"),
    ("go.mod", "Go"),
    ("cargo.toml", "Rust"),
    ("pom.xml", "Java"),
    ("build.gradle", "Java"),
    ("gemfile", "Ruby"),
    ("composer.json", "PHP"),
    ("dockerfile", "Docker"),
    ("docker-compose", "Docker"),
    ("tsconfig.json", "TypeScript"),
)

# Configuration / path fragments → optional stack hints.
_CONFIG_HINTS: tuple[tuple[str, str], ...] = (
    ("vite.config", "Vite"),
    ("next.config", "Next.js"),
    ("nuxt.config", "Nuxt"),
    ("angular.json", "Angular"),
    ("manage.py", "Django"),
    ("fastapi", "FastAPI"),
    ("flask", "Flask"),
    ("prisma", "Prisma"),
)

_LANGUAGE_NORMALIZE = {
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    "ruby": "Ruby",
    "php": "PHP",
    "c": "C",
    "c++": "C++",
    "c#": "C#",
    "csharp": "C#",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "shell": "Shell",
    "html": "HTML",
    "css": "CSS",
    "scss": "SCSS",
    "vue": "Vue",
    "svelte": "Svelte",
    "sql": "SQL",
}

# Config/doc formats are real analysis languages but not useful as "stack" chips.
_LANGUAGE_SKIP = {
    "markdown",
    "json",
    "yaml",
    "yml",
    "toml",
    "xml",
    "ini",
    "text",
    "plaintext",
    "restructuredtext",
    "rst",
    "csv",
    "tsv",
    "lock",
    "gitignore",
    "dockerfile",  # handled via Dockerfile path hint as Docker
}


def _add(ordered: list[str], seen: set[str], label: str) -> None:
    key = label.strip().lower()
    if not key or key in seen:
        return
    seen.add(key)
    ordered.append(label.strip())


def _match_hints(paths: Iterable[str], hints: tuple[tuple[str, str], ...], ordered: list[str], seen: set[str]) -> None:
    lowered = [p.replace("\\", "/").lower() for p in paths]
    for fragment, label in hints:
        if any(fragment in path for path in lowered):
            _add(ordered, seen, label)


def derive_detected_stack(analysis: RepositoryAnalysisPayload, *, limit: int = 8) -> list[str]:
    """Build a compact Detected Stack list from languages, manifests, and config evidence."""
    ordered: list[str] = []
    seen: set[str] = set()

    # Framework / runtime evidence first so truncation keeps the useful labels.
    _match_hints(analysis.summary.dependency_manifests, _MANIFEST_HINTS, ordered, seen)
    _match_hints(analysis.summary.important_files, _MANIFEST_HINTS, ordered, seen)
    _match_hints(analysis.detections.configuration_files, _CONFIG_HINTS, ordered, seen)
    _match_hints(analysis.summary.important_files, _CONFIG_HINTS, ordered, seen)
    service_paths = [
        *analysis.detections.backend_services,
        *analysis.detections.frontend_components,
        *analysis.detections.integrations,
    ]
    _match_hints(service_paths, _CONFIG_HINTS, ordered, seen)

    # Then programming languages ranked by repository weight (bytes, then files).
    ranked = sorted(
        analysis.summary.languages,
        key=lambda item: (item.total_bytes, item.file_count),
        reverse=True,
    )
    for lang in ranked:
        raw = (lang.language or "").strip()
        if not raw:
            continue
        key = raw.lower()
        if key in _LANGUAGE_SKIP:
            continue
        label = _LANGUAGE_NORMALIZE.get(key, raw.title() if raw.islower() else raw)
        _add(ordered, seen, label)

    return ordered[:limit]
