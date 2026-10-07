"""Health check response schema."""

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="Overall API status")
    service: str = Field(description="Service display name")
    environment: str = Field(description="Deployment environment name")
    timestamp: datetime = Field(description="UTC time of the health check")
    mongodb: str = Field(default="unknown", description="MongoDB connectivity")
    google_oauth: str = Field(
        default="unknown",
        description="Whether Google OAuth env vars are set",
    )
    gemini: str = Field(
        default="unknown",
        description="Whether Gemini API key is set for architecture and RAG chat",
    )
