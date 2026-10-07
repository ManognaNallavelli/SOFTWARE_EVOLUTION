"""Auth-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    id: str
    email: str
    name: str
    picture: str | None = None
    created_at: datetime


class AuthMeResponse(BaseModel):
    authenticated: bool
    user: UserPublic | None = None
