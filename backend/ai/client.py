from __future__ import annotations

from typing import Any

from openai import OpenAI

from .settings import load_ai_settings


def create_ai_client(
    settings: dict[str, Any] | None = None,
) -> tuple[OpenAI, dict[str, Any]]:
    """
    Create an OpenAI-compatible client using the current AI settings.

    Settings are loaded for each request, so NOCPilot does not need to
    restart when the AI endpoint or model changes.
    """

    current_settings = settings or load_ai_settings()

    client = OpenAI(
        base_url=current_settings["base_url"],
        api_key=current_settings["api_key"],
        timeout=float(current_settings["timeout_seconds"]),
    )

    return client, current_settings


def test_ai_connection() -> dict[str, Any]:
    """Test the currently saved AI configuration."""

    client, settings = create_ai_client()

    try:
        response = client.chat.completions.create(
            model=settings["model"],
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Reply with exactly: "
                        "NOCPilot AI connection successful"
                    ),
                }
            ],
            max_tokens=20,
        )

        answer = str(
            response.choices[0].message.content or ""
        ).strip()

        return {
            "success": True,
            "message": (
                answer
                or "The AI server responded successfully."
            ),
            "provider": settings["provider"],
            "base_url": settings["base_url"],
            "model": settings["model"],
        }

    except Exception as error:
        return {
            "success": False,
            "message": str(error),
            "provider": settings["provider"],
            "base_url": settings["base_url"],
            "model": settings["model"],
        }
