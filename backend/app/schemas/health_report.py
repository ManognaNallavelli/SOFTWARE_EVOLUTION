"""Health report schemas derived from structural repository analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


HealthStatusLabel = Literal["Healthy", "Moderate", "Needs Improvement", "Critical"]
IssueSeverity = Literal["critical", "high", "medium", "low"]
RecommendationPriority = Literal["critical", "high", "medium", "low"]


class HealthCategoryResult(BaseModel):
    score: int | None = Field(
        default=None,
        description="0-100, or null when insufficient data",
    )
    status: Literal["scored", "insufficient_data"] = "scored"
    summary: str
    issues: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


class HealthIssue(BaseModel):
    severity: IssueSeverity
    title: str
    detail: str
    category: str
    evidence: list[str] = Field(default_factory=list)


class HealthRecommendation(BaseModel):
    title: str
    reason: str
    priority: RecommendationPriority
    expected_impact: str
    category: str


class ArchitectureOverview(BaseModel):
    main_technologies: list[str] = Field(default_factory=list)
    major_modules: list[str] = Field(default_factory=list)
    api_layer: list[str] = Field(default_factory=list)
    data_layer: list[str] = Field(default_factory=list)
    test_layer: list[str] = Field(default_factory=list)
    important_dependencies: list[str] = Field(default_factory=list)
    production_route_count: int = 0
    test_or_example_route_count: int = 0
    notes: list[str] = Field(default_factory=list)


class HealthReport(BaseModel):
    overall_score: int | None = None
    status: HealthStatusLabel | Literal["Insufficient data"] = "Insufficient data"
    categories: dict[str, HealthCategoryResult]
    strengths: list[str] = Field(default_factory=list)
    issues: list[HealthIssue] = Field(default_factory=list)
    recommendations: list[HealthRecommendation] = Field(default_factory=list)
    architecture_overview: ArchitectureOverview
    scoring_notes: list[str] = Field(default_factory=list)
    generated_from_analysis: bool = True
