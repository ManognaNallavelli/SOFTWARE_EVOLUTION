"""Project request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ProjectCreateRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    github_url: str = Field(min_length=10, max_length=500)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("github_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("technologies")
    @classmethod
    def clean_technologies(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            tech = item.strip()
            if tech and tech not in cleaned:
                cleaned.append(tech)
        return cleaned

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ProjectPublic(BaseModel):
    id: str
    owner_user_id: str
    name: str
    github_url: str
    normalized_github_url: str
    github_repo_id: int
    github_full_name: str
    technologies: list[str]
    description: str | None
    status: str
    last_error: str | None = None
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    projects: list[ProjectPublic]


class DuplicateProjectDetail(BaseModel):
    code: str = "duplicate_repository"
    message: str
    existing_project_id: str
