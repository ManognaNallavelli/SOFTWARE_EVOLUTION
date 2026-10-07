"""Regression tests for RAG chunk ID uniqueness."""

from __future__ import annotations

from pathlib import Path

from app.rag.chunker import CodeChunk, _finalize_chunks, chunk_repository


def test_finalize_chunks_unique_ids_for_overlapping_spans():
    """Symbol + overview windows can share path/lines/text prefix."""
    project_id = "proj_overlap"
    body = "\n".join(f"line {i}" for i in range(1, 40))
    raw = [
        CodeChunk(
            chunk_id="",
            project_id=project_id,
            file_path="src/lib.js",
            language="javascript",
            symbol="foo",
            start_line=1,
            end_line=30,
            text=body,
        ),
        # Exact duplicate — should be dropped
        CodeChunk(
            chunk_id="",
            project_id=project_id,
            file_path="src/lib.js",
            language="javascript",
            symbol=None,
            start_line=1,
            end_line=30,
            text=body,
        ),
        # Same span but different content — must keep unique ID
        CodeChunk(
            chunk_id="",
            project_id=project_id,
            file_path="src/lib.js",
            language="javascript",
            symbol=None,
            start_line=1,
            end_line=30,
            text=body + "\n// overview",
        ),
    ]
    finalized = _finalize_chunks(project_id, raw)
    assert len(finalized) == 2
    ids = [c.chunk_id for c in finalized]
    assert len(ids) == len(set(ids))
    assert all(cid.startswith(f"{project_id}_") for cid in ids)
    assert all(len(cid) > len(project_id) + 20 for cid in ids)


def test_chunk_repository_ids_unique_with_symbol_and_overview(tmp_path: Path):
    project_id = "proj_axios_sim"
    src = tmp_path / "lib"
    src.mkdir()
    lines = ["export function request() {"] + [f"  const x{i} = {i};" for i in range(80)] + ["}"]
    (src / "core.js").write_text("\n".join(lines), encoding="utf-8")

    symbols = [
        {
            "file_path": "lib/core.js",
            "name": "request",
            "start_line": 1,
            "end_line": 40,
        }
    ]
    chunks, file_count = chunk_repository(
        project_id=project_id,
        repo_root=tmp_path,
        analysis_symbols=symbols,
    )
    assert file_count >= 1
    assert chunks
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), f"duplicate ids: {[i for i in ids if ids.count(i) > 1][:5]}"
