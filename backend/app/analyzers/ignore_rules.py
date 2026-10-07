"""Shared ignore rules and path helpers for repository walks."""

from __future__ import annotations

import os
from pathlib import Path

IGNORE_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "target",
    "vendor",
    ".idea",
    ".vscode",
    ".gradle",
    ".svn",
    ".hg",
    "Pods",
    "DerivedData",
    "out",
    "bin",
    "obj",
}

# Directory name patterns (suffix/prefix style) handled in helpers
IGNORE_DIR_SUFFIXES = (".egg-info",)

IGNORE_FILE_NAMES = {
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "composer.lock",
}

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".jar",
    ".war",
    ".o",
    ".a",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wasm",
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".kt": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".markdown": "markdown",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
    ".dockerfile": "dockerfile",
}

IMPORTANT_FILE_NAMES = {
    "package.json",
    "package-lock.json",
    "requirements.txt",
    "pyproject.toml",
    "pipfile",
    "pipfile.lock",
    "setup.py",
    "setup.cfg",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "cargo.toml",
    "go.mod",
    "composer.json",
    "gemfile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "readme",
    "readme.md",
    "readme.rst",
    "readme.txt",
    ".env.example",
    "tsconfig.json",
    "jsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "next.config.mjs",
    "webpack.config.js",
    "manage.py",
    "app.py",
    "main.py",
    "index.js",
    "index.ts",
    "index.tsx",
}

MAX_TEXT_FILE_BYTES = 1_000_000
MAX_WALK_FILES = 8_000


def is_ignored_dirname(name: str) -> bool:
    lower = name.lower()
    if lower in IGNORE_DIR_NAMES:
        return True
    if any(lower.endswith(suffix) for suffix in IGNORE_DIR_SUFFIXES):
        return True
    if lower.startswith(".") and lower not in {".github", ".config"}:
        # Keep .github workflows as config evidence; skip other hidden dirs
        if lower == ".github":
            return False
        return True
    return False


def is_ignored_filename(name: str) -> bool:
    lower = name.lower()
    if lower in IGNORE_FILE_NAMES:
        return True
    if lower.endswith(".min.js") or lower.endswith(".min.css") or lower.endswith(".map"):
        return True
    return False


def detect_language(path: Path) -> str | None:
    name = path.name.lower()
    if name == "dockerfile" or name.startswith("dockerfile."):
        return "dockerfile"
    if name == "readme" or name.startswith("readme."):
        if name == "readme" or name.endswith((".md", ".markdown", ".rst", ".txt")):
            return "markdown"
    ext = path.suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(ext)


def classify_code_role(path: Path, category: str | None = None, is_binary: bool = False) -> str:
    """Classify a file into production/test/example/docs/config/generated/binary."""
    if is_binary or category == "binary":
        return "binary"

    parts = [p.lower() for p in path.parts]
    name = path.name.lower()

    test_dir_tokens = {
        "test",
        "tests",
        "testing",
        "__tests__",
        "spec",
        "specs",
        "unit",
        "integration",
        "e2e",
    }
    example_dir_tokens = {
        "example",
        "examples",
        "sample",
        "samples",
        "demo",
        "demos",
        "tutorial",
        "tutorials",
        "playground",
    }
    docs_dir_tokens = {"docs", "doc", "documentation", "guides", "wiki"}
    generated_dir_tokens = {"generated", "codegen", "migrations"}  # migrations kept as config-ish elsewhere

    if any(p in test_dir_tokens for p in parts) or (
        name.startswith("test_")
        or name.endswith(("_test.py", ".test.js", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts", ".spec.tsx"))
    ):
        return "test"

    if any(p in example_dir_tokens for p in parts) or name.startswith("example") or category == "example":
        return "example"

    if category == "docs" or name.startswith("readme") or any(p in docs_dir_tokens for p in parts):
        return "documentation"

    if category in {"config", "dependency_manifest"} or any(
        p in {"config", "configs", "settings", ".github"} for p in parts
    ):
        return "configuration"

    if any(p in generated_dir_tokens for p in parts) and "migrations" not in parts:
        return "generated"

    if category in {
        "source",
        "api",
        "service",
        "data_access",
        "frontend_component",
        "frontend_asset",
    }:
        return "production"

    if category == "test":
        return "test"

    return "production" if category not in {"other", None} else "production"


def categorize_file(path: Path, language: str | None) -> str:
    name = path.name.lower()
    parts = {p.lower() for p in path.parts}

    if any(p in {"example", "examples", "sample", "samples", "demo", "demos"} for p in parts):
        if language == "markdown" or name.startswith("readme"):
            return "docs"
        return "example"

    if name in IMPORTANT_FILE_NAMES or name.startswith("readme"):
        if "docker" in name:
            return "config"
        if name.startswith("readme"):
            return "docs"
        if any(
            token in name
            for token in (
                "package.json",
                "requirements",
                "pyproject",
                "pom.xml",
                "cargo.toml",
                "go.mod",
                "gemfile",
                "composer.json",
                "pipfile",
            )
        ):
            return "dependency_manifest"
        return "config"

    if (
        "test" in parts
        or "tests" in parts
        or "__tests__" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.js")
    ):
        return "test"

    if language in {"python", "javascript", "typescript", "java", "go", "rust", "ruby", "php", "csharp", "cpp", "c", "kotlin", "swift", "scala"}:
        if any(p in parts for p in ("components", "component")):
            return "frontend_component"
        if any(p in parts for p in ("routes", "routers", "controllers", "api", "endpoints")):
            return "api"
        if any(p in parts for p in ("models", "repositories", "dao", "db", "database", "schemas")):
            return "data_access"
        if any(p in parts for p in ("services", "service")):
            return "service"
        if any(p in parts for p in ("config", "configs", "settings")):
            return "config"
        return "source"

    if language in {"html", "css", "scss", "sass", "less"}:
        return "frontend_asset"
    if language == "markdown":
        return "docs"
    if language in {"json", "yaml", "toml", "xml"}:
        return "config"
    if language == "sql":
        return "data_access"
    if language in {"shell", "powershell", "dockerfile"}:
        return "config"
    return "other"


def safe_repo_root(clone_root: Path, project_id: str) -> Path:
    """Resolve a project clone path and ensure it stays under clone_root."""
    if ".." in project_id or "/" in project_id or "\\" in project_id:
        raise ValueError("Invalid project_id for filesystem use")
    root = (clone_root / project_id).resolve()
    base = clone_root.resolve()
    if root != base and base not in root.parents:
        raise ValueError("Resolved clone path escapes repository workspace")
    return root


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()
