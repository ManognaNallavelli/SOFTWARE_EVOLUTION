"""Pydantic schemas for structural repository analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.health_report import HealthReport

ProjectProcessStatus = Literal[
    "created",
    "pending",  # legacy Phase 1 value treated as not-analyzed
    "validating",
    "cloning",
    "analyzing",
    "completed",
    "failed",
]


class AnalysisRepositoryInfo(BaseModel):
    name: str
    url: str
    branch: str
    full_name: str | None = None


class LanguageCount(BaseModel):
    language: str
    file_count: int
    total_bytes: int = 0


class AnalysisSummary(BaseModel):
    total_files: int
    total_directories: int
    languages: list[LanguageCount]
    important_files: list[str]
    has_readme: bool
    dependency_manifests: list[str] = Field(default_factory=list)
    deep_analysis_languages: list[str] = Field(default_factory=list)
    truncated: bool = False
    symbol_count: int = 0
    import_count: int = 0
    export_count: int = 0
    route_count: int = 0
    production_route_count: int = 0
    test_or_example_route_count: int = 0


class AnalysisFile(BaseModel):
    path: str
    language: str | None = None
    size: int
    extension: str = ""
    category: str = "other"
    code_role: str = "production"


class AnalysisSymbol(BaseModel):
    name: str
    type: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    parent: str | None = None


class AnalysisImport(BaseModel):
    source_file: str
    imported_module: str
    names: list[str] = Field(default_factory=list)
    line: int | None = None


class AnalysisExport(BaseModel):
    source_file: str
    name: str
    export_type: str
    line: int | None = None


class AnalysisRoute(BaseModel):
    file_path: str
    function: str | None = None
    method: str
    path: str | None = None
    line: int | None = None
    evidence: str
    code_role: str = "production"


class AnalysisDetections(BaseModel):
    frontend_components: list[str] = Field(default_factory=list)
    backend_services: list[str] = Field(default_factory=list)
    api_routes: list[AnalysisRoute] = Field(default_factory=list)
    data_access_modules: list[str] = Field(default_factory=list)
    configuration_files: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)


class RepositoryAnalysisPayload(BaseModel):
    project_id: str
    repository: AnalysisRepositoryInfo
    summary: AnalysisSummary
    files: list[AnalysisFile]
    symbols: list[AnalysisSymbol]
    imports: list[AnalysisImport]
    exports: list[AnalysisExport]
    detections: AnalysisDetections
    limits: dict[str, Any] = Field(default_factory=dict)


class AnalysisDocumentResponse(BaseModel):
    project_id: str
    status: str
    analysis: RepositoryAnalysisPayload | None = None
    health_report: HealthReport | None = None
    health_error: str | None = None
    error: str | None = None
    error_code: str | None = None
    analyzed_at: datetime | None = None
    updated_at: datetime | None = None


class AnalyzeAcceptedResponse(BaseModel):
    project_id: str
    status: str
    message: str
    analysis: RepositoryAnalysisPayload | None = None
    health_report: HealthReport | None = None
    health_error: str | None = None
    error: str | None = None
    error_code: str | None = None
    analyzed_at: datetime | None = None
    updated_at: datetime | None = None
