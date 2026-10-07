"""Filesystem walk producing file metadata for analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.ignore_rules import (
    BINARY_EXTENSIONS,
    IMPORTANT_FILE_NAMES,
    MAX_TEXT_FILE_BYTES,
    MAX_WALK_FILES,
    categorize_file,
    classify_code_role,
    detect_language,
    is_ignored_dirname,
    is_ignored_filename,
    relative_posix,
)


@dataclass
class FileRecord:
    path: str
    language: str | None
    size: int
    extension: str
    category: str
    code_role: str
    is_binary: bool


@dataclass
class WalkResult:
    files: list[FileRecord] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    truncated: bool = False
    important_files: list[str] = field(default_factory=list)
    has_readme: bool = False


def walk_repository(repo_root: Path) -> WalkResult:
    result = WalkResult()
    root = repo_root.resolve()

    for current, dirnames, filenames in os_walk_filtered(root):
        current_path = Path(current)
        rel_dir = relative_posix(current_path, root) if current_path != root else ""
        if rel_dir:
            result.directories.append(rel_dir)

        for filename in filenames:
            if is_ignored_filename(filename):
                continue
            file_path = current_path / filename
            if not file_path.is_file():
                continue

            try:
                size = file_path.stat().st_size
            except OSError:
                continue

            rel = relative_posix(file_path, root)
            ext = file_path.suffix.lower()
            is_binary = ext in BINARY_EXTENSIONS
            language = None if is_binary else detect_language(file_path)
            category = "binary" if is_binary else categorize_file(file_path, language)
            code_role = classify_code_role(file_path, category=category, is_binary=is_binary)

            result.files.append(
                FileRecord(
                    path=rel,
                    language=language,
                    size=size,
                    extension=ext or "",
                    category=category,
                    code_role=code_role,
                    is_binary=is_binary,
                )
            )

            lower_name = filename.lower()
            if lower_name.startswith("readme"):
                result.has_readme = True
            if lower_name in IMPORTANT_FILE_NAMES or lower_name.startswith("readme"):
                result.important_files.append(rel)

            if len(result.files) >= MAX_WALK_FILES:
                result.truncated = True
                return result

    result.important_files = sorted(set(result.important_files))
    result.directories = sorted(set(result.directories))
    return result


def os_walk_filtered(root: Path):
    import os

    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not is_ignored_dirname(d))
        yield current, dirnames, filenames


def read_text_file(path: Path) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > MAX_TEXT_FILE_BYTES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except OSError:
            return None
    except OSError:
        return None
