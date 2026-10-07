"""API schemas for architecture generation (Phase 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


NodeKind = Literal[
    "frontend",
    "backend",
    "service",
    "module",
    "api",
    "database",
    "external",
    "config",
    "test",
    "other",
]

EdgeType = Literal[
    "calls",
    "imports",
    "uses",
    "contains",
    "exposes",
    "stores",
    "depends_on",
]


class ArchitectureNode(BaseModel):
    id: str
    label: str
    kind: NodeKind = "other"
    description: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class ArchitectureEdge(BaseModel):
    id: str
    source: str
    target: str
    type: EdgeType = "depends_on"
    label: str | None = None
    evidence: list[str] = Field(default_factory=list)


class ArchitectureGraph(BaseModel):
    """Canonical architecture graph — UI-independent (React Flow is an adapter)."""

    nodes: list[ArchitectureNode] = Field(default_factory=list)
    edges: list[ArchitectureEdge] = Field(default_factory=list)
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ArchitectureDocumentResponse(BaseModel):
    project_id: str
    status: Literal["not_generated", "generating", "completed", "failed"]
    graph: ArchitectureGraph | None = None
    source: Literal["gemini", "deterministic"] | None = None
    gemini_model: str | None = None
    analysis_project_id: str | None = None
    analyzed_at: datetime | None = None
    generated_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    error_code: str | None = None
    version: int = 1


class ArchitectureGenerateResponse(ArchitectureDocumentResponse):
    message: str
