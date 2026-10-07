"""Decide which repository files are eligible for RAG indexing."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.analyzers.ignore_rules import BINARY_EXTENSIONS, IGNORE_FILE_NAMES, detect_language

SKIP_EXTENSIONS = BINARY_EXTENSIONS | {
    ".lock",
    ".min.js",
    ".min.css",
    ".map",
    ".svg",
    ".ico",
    ".css",
    ".scss",
    ".less",
    ".ipynb",
}

# Keep index lean: prioritize application source over tests/docs/noise.
SKIP_PATH_PARTS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    ".venv",
    "venv",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".next",
    "storybook-static",
    "migrations",
    "alembic",
    "fixtures",
    "snapshots",
    "testdata",
    "test-data",
    "e2e",
    "cypress",
    "playwright",
    "workflows",
    ".circleci",
    ".gitlab-ci",
}

TEST_PATH_PARTS = {
    "test",
    "tests",
    "testing",
    "__tests__",
    "spec",
    "specs",
}

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".kt",
    ".swift",
    ".scala",
    ".vue",
    ".svelte",
}

CONFIG_NAMES = {
    "dockerfile",
    "makefile",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "cargo.toml",
    "go.mod",
    "composer.json",
    "tsconfig.json",
    "docker-compose.yml",
    "docker-compose.yaml",
}

MAX_INDEX_FILE_BYTES = 120_000
MAX_INDEX_FILES = 180
MAX_TEST_FILES = 25
# Allow README + a modest set of docs without letting markdown dominate the index.
MAX_DOC_FILES = 15

_DOC_NAME_ALLOW = {
    "readme",
    "architecture",
    "contributing",
    "changelog",
    "history",
    "api",
    "guide",
    "usage",
    "overview",
    "getting-started",
    "getting_started",
    "quickstart",
    "quick-start",
    "install",
    "installation",
    "security",
    "design",
}


def _path_parts(path: Path) -> set[str]:
    return {p.lower() for p in PurePosixPath(path.as_posix()).parts}


def _is_relevant_doc_file(path: Path) -> bool:
    """Include README and useful documentation markdown; skip arbitrary notes."""
    name = path.name.lower()
    stem = path.stem.lower()
    ext = path.suffix.lower()
    if ext not in {".md", ".rst", ".txt", ".markdown"}:
        return False
    parts = _path_parts(path)
    if name.startswith("readme") or stem.startswith("readme"):
        return True
    if any(token in stem for token in _DOC_NAME_ALLOW):
        return True
    # Documentation trees (docs/, documentation/, doc/)
    if parts & {"docs", "documentation", "doc"}:
        return True
    # Top-level markdown only (avoid deep random notes)
    if len(parts) == 1:
        return True
    return False


def is_indexable_file(path: Path, *, size: int) -> bool:
    name = path.name.lower()
    if name in IGNORE_FILE_NAMES:
        return False
    if name.endswith(".min.js") or name.endswith(".min.css"):
        return False
    ext = path.suffix.lower()
    if ext in SKIP_EXTENSIONS:
        return False
    if size <= 0 or size > MAX_INDEX_FILE_BYTES:
        return False

    parts = _path_parts(path)
    if parts & SKIP_PATH_PARTS:
        return False

    # CI / generated workflow noise rarely helps implementation answers.
    if ".github" in parts and ext in {".yml", ".yaml"}:
        return False
    if "generated" in parts or name.endswith(".generated.ts") or name.endswith(".generated.js"):
        return False

    # Prefer source languages
    if ext in SOURCE_EXTENSIONS:
        return True

    # Useful config / dependency manifests
    if name in CONFIG_NAMES:
        return True

    if ext in {".toml", ".ini", ".cfg", ".env.example"}:
        return True

    if _is_relevant_doc_file(path):
        return True

    if ext in {".yml", ".yaml"} and name.startswith("docker-compose"):
        return True

    language = detect_language(path)
    return bool(language and ext in SOURCE_EXTENSIONS)


def classify_index_bucket(path: Path) -> str:
    parts = _path_parts(path)
    name = path.name.lower()
    if parts & TEST_PATH_PARTS or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if path.suffix.lower() in {".md", ".rst", ".txt", ".markdown"}:
        return "doc"
    if name.startswith("readme"):
        return "doc"
    return "source"
