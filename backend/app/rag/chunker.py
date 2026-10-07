"""Code-aware repository chunking for RAG."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.analyzers.filesystem import read_text_file
from app.analyzers.ignore_rules import detect_language, relative_posix
from app.rag.file_filter import (
    MAX_DOC_FILES,
    MAX_INDEX_FILES,
    MAX_TEST_FILES,
    classify_index_bucket,
    is_indexable_file,
)

CHUNK_LINES = 48
CHUNK_OVERLAP = 6
MAX_CHUNKS = 350
MAX_CHUNK_CHARS = 1600
MAX_SYMBOL_WINDOWS_PER_FILE = 12

SYMBOL_HEADER_RE = re.compile(
    r"^(?:async\s+)?(?:def|class|function|export\s+(?:default\s+)?(?:async\s+)?function|export\s+class|interface|type)\s+([A-Za-z_][\w]*)",
    re.MULTILINE,
)


@dataclass
class CodeChunk:
    chunk_id: str
    project_id: str
    file_path: str
    language: str | None
    symbol: str | None
    start_line: int
    end_line: int
    text: str


def _chunk_id(
    project_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
    ordinal: int,
    text: str,
) -> str:
    """Deterministic ID unique within a project.

    Includes ordinal so overlapping windows (symbol + overview) that share the
    same path/lines/prefix cannot collide. Full SHA-1 avoids truncated-hash
    collisions that previously used digest[:20].
    """
    text_digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    material = (
        f"{project_id}\0{file_path}\0{start_line}\0{end_line}\0{ordinal}\0{text_digest}"
    ).encode("utf-8")
    digest = hashlib.sha1(material).hexdigest()
    return f"{project_id}_{digest}"


def _clip_text(text: str) -> str:
    if len(text) <= MAX_CHUNK_CHARS:
        return text
    return text[: MAX_CHUNK_CHARS - 20] + "\n...[truncated]..."


def _chunks_from_lines(
    *,
    project_id: str,
    file_path: str,
    language: str | None,
    lines: list[str],
    symbol: str | None = None,
    line_offset: int = 1,
) -> list[CodeChunk]:
    """Build sliding-window chunks. IDs are placeholders until finalize."""
    chunks: list[CodeChunk] = []
    if not lines:
        return chunks
    total = len(lines)
    start = 0
    while start < total:
        end = min(total, start + CHUNK_LINES)
        block = lines[start:end]
        text = _clip_text("\n".join(block).strip("\n"))
        if text.strip():
            start_line = line_offset + start
            end_line = line_offset + end - 1
            inferred = symbol
            if not inferred:
                match = SYMBOL_HEADER_RE.search(text)
                inferred = match.group(1) if match else None
            chunks.append(
                CodeChunk(
                    chunk_id="",  # assigned in _finalize_chunks
                    project_id=project_id,
                    file_path=file_path,
                    language=language,
                    symbol=inferred,
                    start_line=start_line,
                    end_line=end_line,
                    text=text,
                )
            )
        if end >= total:
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _symbol_windows(
    lines: list[str],
    symbols: list[dict[str, Any]],
    file_path: str,
) -> list[tuple[str | None, int, int]]:
    windows: list[tuple[str | None, int, int]] = []
    for symbol in symbols:
        if symbol.get("file_path") != file_path:
            continue
        start = symbol.get("start_line")
        end = symbol.get("end_line")
        name = symbol.get("name")
        if not isinstance(start, int) or start < 1:
            continue
        if not isinstance(end, int) or end < start:
            end = min(len(lines), start + CHUNK_LINES - 1)
        end = min(len(lines), max(end, start))
        # Skip tiny one-liners that add noise
        if end - start < 2:
            continue
        windows.append((str(name) if name else None, start, end))
    windows.sort(key=lambda w: (w[1], w[2]))
    # Cap per file to avoid explosion on large modules
    return windows[:MAX_SYMBOL_WINDOWS_PER_FILE]


def _finalize_chunks(project_id: str, chunks: list[CodeChunk]) -> list[CodeChunk]:
    """Drop exact duplicates and assign deterministically unique chunk IDs."""
    seen_content: set[tuple[str, int, int, str]] = set()
    finalized: list[CodeChunk] = []

    for chunk in chunks:
        if chunk.project_id != project_id:
            raise ValueError("chunk project_id mismatch during finalize")
        text_digest = hashlib.sha1(chunk.text.encode("utf-8")).hexdigest()
        key = (chunk.file_path, chunk.start_line, chunk.end_line, text_digest)
        if key in seen_content:
            continue
        seen_content.add(key)
        ordinal = len(finalized)
        finalized.append(
            CodeChunk(
                chunk_id=_chunk_id(
                    project_id,
                    chunk.file_path,
                    chunk.start_line,
                    chunk.end_line,
                    ordinal,
                    chunk.text,
                ),
                project_id=project_id,
                file_path=chunk.file_path,
                language=chunk.language,
                symbol=chunk.symbol,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text,
            )
        )

    ids = [c.chunk_id for c in finalized]
    if len(ids) != len(set(ids)):
        raise RuntimeError("chunk ID uniqueness invariant violated after finalize")
    return finalized


def chunk_repository(
    *,
    project_id: str,
    repo_root: Path,
    analysis_symbols: list[dict[str, Any]] | None = None,
) -> tuple[list[CodeChunk], int]:
    """Walk repo and produce code chunks. Returns (chunks, file_count)."""
    root = repo_root.resolve()
    symbols = analysis_symbols or []
    chunks: list[CodeChunk] = []
    file_count = 0
    test_files = 0
    doc_files = 0

    from app.analyzers.filesystem import os_walk_filtered
    from app.analyzers.ignore_rules import is_ignored_filename

    # Collect candidates first so we can prefer source over tests/docs
    candidates: list[tuple[Path, str, str]] = []
    for current, _dirnames, filenames in os_walk_filtered(root):
        current_path = Path(current)
        for filename in filenames:
            if is_ignored_filename(filename):
                continue
            path = current_path / filename
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if not is_indexable_file(path, size=size):
                continue
            rel = relative_posix(path, root)
            bucket = classify_index_bucket(Path(rel))
            candidates.append((path, rel, bucket))

    def _candidate_sort_key(item: tuple[Path, str, str]) -> tuple[int, int, str]:
        _path, rel, bucket = item
        bucket_rank = 0 if bucket == "source" else 1 if bucket == "doc" else 2
        name = Path(rel).name.lower()
        # Among docs, always keep README ahead of other markdown so it is not
        # crowded out of the MAX_CHUNKS budget by alphabetical guides.
        doc_rank = 0 if name.startswith("readme") else 1
        return (bucket_rank, doc_rank, rel.lower())

    # Prefer source files first; within docs prefer README.
    candidates.sort(key=_candidate_sort_key)

    for path, rel, bucket in candidates:
        if file_count >= MAX_INDEX_FILES or len(chunks) >= MAX_CHUNKS:
            break
        if bucket == "test":
            if test_files >= MAX_TEST_FILES:
                continue
        if bucket == "doc":
            if doc_files >= MAX_DOC_FILES:
                continue

        language = detect_language(path)
        text = read_text_file(path)
        if text is None:
            continue

        file_count += 1
        if bucket == "test":
            test_files += 1
        elif bucket == "doc":
            doc_files += 1

        lines = text.splitlines()
        windows = _symbol_windows(lines, symbols, rel) if bucket == "source" else []
        if windows:
            for symbol_name, start, end in windows:
                s = max(1, start)
                e = min(len(lines), max(end, start + 10))
                span_lines = lines[s - 1 : e]
                if e - s + 1 > CHUNK_LINES * 2:
                    chunks.extend(
                        _chunks_from_lines(
                            project_id=project_id,
                            file_path=rel,
                            language=language,
                            lines=span_lines,
                            symbol=symbol_name,
                            line_offset=s,
                        )
                    )
                else:
                    body = _clip_text("\n".join(span_lines).strip("\n"))
                    if body.strip():
                        chunks.append(
                            CodeChunk(
                                chunk_id="",
                                project_id=project_id,
                                file_path=rel,
                                language=language,
                                symbol=symbol_name,
                                start_line=s,
                                end_line=e,
                                text=body,
                            )
                        )
                if len(chunks) >= MAX_CHUNKS:
                    break
            # If symbol windows were sparse, add one file-level overview window
            if len(windows) < 2 and len(lines) > 0 and len(chunks) < MAX_CHUNKS:
                chunks.extend(
                    _chunks_from_lines(
                        project_id=project_id,
                        file_path=rel,
                        language=language,
                        lines=lines[: min(len(lines), CHUNK_LINES * 2)],
                    )[:2]
                )
        else:
            chunks.extend(
                _chunks_from_lines(
                    project_id=project_id,
                    file_path=rel,
                    language=language,
                    lines=lines,
                )
            )

    return _finalize_chunks(project_id, chunks[:MAX_CHUNKS]), file_count
