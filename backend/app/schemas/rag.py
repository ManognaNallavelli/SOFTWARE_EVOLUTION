"""RAG / chat API schemas (Phase 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RagIndexStatusValue = Literal[
    "not_indexed",
    "indexing",
    "ready",
    "failed",
]


class RagStatusResponse(BaseModel):
    project_id: str
    status: RagIndexStatusValue = "not_indexed"
    chunk_count: int = 0
    file_count: int = 0
    indexed_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    error_code: str | None = None
    embedding_model: str | None = None
    message: str | None = None


class RagIndexResponse(RagStatusResponse):
    message: str


WorkspacePage = Literal["overview", "health", "architecture"]


class ChatHealthSelection(BaseModel):
    kind: Literal["issue", "recommendation"]
    # Position in the stored health report list; the title is re-checked server-side.
    index: int = Field(ge=0, le=1000)
    title: str = Field(min_length=1, max_length=300)


class ChatContext(BaseModel):
    """What the user is looking at in the workspace. Identifiers only; resolved against stored analysis."""

    page: WorkspacePage | None = None
    file_path: str | None = Field(default=None, max_length=500)
    architecture_node_id: str | None = Field(default=None, max_length=200)
    health_item: ChatHealthSelection | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    context: ChatContext | None = None


class ChatSource(BaseModel):
    file_path: str
    language: str | None = None
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    excerpt: str
    score: float | None = None
    # Analysis finding ids (e.g. "A3") this code chunk was fetched to support.
    supports: list[str] = Field(default_factory=list)


class AnalysisFileRef(BaseModel):
    file_path: str
    line: int | None = None
    end_line: int | None = None


class AnalysisFinding(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    file_refs: list[AnalysisFileRef] = Field(default_factory=list)


class ChatResponse(BaseModel):
    project_id: str
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    context_insufficient: bool = False
    model: str | None = None
    analysis_findings: list[AnalysisFinding] = Field(default_factory=list)
    analysis_notes: list[str] = Field(default_factory=list)
    # Workspace selection that was resolved and used to answer, e.g. "Architecture component: Data access".
    context_applied: str | None = None
