from __future__ import annotations

from pydantic import BaseModel, Field


class AISettingsUpdate(BaseModel):
    """Settings submitted from the NOCPilot settings page."""

    provider: str = Field(
        default="openai_compatible",
        min_length=1,
    )

    base_url: str = Field(
        min_length=1,
    )

    model: str = Field(
        min_length=1,
    )

    # None or an empty value means keep the existing API key.
    api_key: str | None = None

    timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
    )

    use_rag: bool = True


class AISettingsResponse(BaseModel):
    """Safe settings returned to the frontend."""

    provider: str
    base_url: str
    model: str
    timeout_seconds: int
    use_rag: bool
    api_key_configured: bool
