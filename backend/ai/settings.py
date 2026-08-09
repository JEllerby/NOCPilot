from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from .models import AISettingsUpdate


AI_DIRECTORY = Path(__file__).resolve().parent
SETTINGS_DIRECTORY = AI_DIRECTORY / "data"
SETTINGS_FILE = SETTINGS_DIRECTORY / "ai_settings.json"


DEFAULT_AI_SETTINGS: dict[str, Any] = {
    "provider": "openai_compatible",
    "base_url": "http://25.5.202.103:1234/v1",
    "model": "qwen/qwen3-8b",
    "api_key": "unused",
    "timeout_seconds": 60,
    "use_rag": True,
}


def normalize_base_url(base_url: str) -> str:
    """Validate and normalize the configured AI endpoint."""

    normalized_url = base_url.strip().rstrip("/")

    if not normalized_url:
        raise ValueError("The AI base URL cannot be empty.")

    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError(
            "The AI base URL must begin with http:// or https://."
        )

    return normalized_url


def load_ai_settings() -> dict[str, Any]:
    """
    Load settings from disk.

    The defaults are returned if the local settings file does not exist
    or cannot be read.
    """

    settings = DEFAULT_AI_SETTINGS.copy()

    if not SETTINGS_FILE.exists():
        return settings

    try:
        with SETTINGS_FILE.open(
            "r",
            encoding="utf-8",
        ) as settings_file:
            saved_settings = json.load(settings_file)

        if not isinstance(saved_settings, dict):
            raise ValueError(
                "The AI settings file must contain a JSON object."
            )

        for key in DEFAULT_AI_SETTINGS:
            if key in saved_settings:
                settings[key] = saved_settings[key]

        settings["provider"] = (
            str(settings["provider"]).strip()
            or DEFAULT_AI_SETTINGS["provider"]
        )

        settings["base_url"] = normalize_base_url(
            str(settings["base_url"])
        )

        settings["model"] = (
            str(settings["model"]).strip()
            or DEFAULT_AI_SETTINGS["model"]
        )

        settings["api_key"] = (
            str(settings["api_key"]).strip()
            or DEFAULT_AI_SETTINGS["api_key"]
        )

        timeout_seconds = int(settings["timeout_seconds"])

        if not 5 <= timeout_seconds <= 300:
            timeout_seconds = DEFAULT_AI_SETTINGS[
                "timeout_seconds"
            ]

        settings["timeout_seconds"] = timeout_seconds
        settings["use_rag"] = bool(settings["use_rag"])

        return settings

    except (
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"[NOCPilot] Unable to load AI settings: {error}"
        )

        return DEFAULT_AI_SETTINGS.copy()


def public_ai_settings(
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return settings that are safe to send to the browser.

    The actual API key is never returned.
    """

    current_settings = settings or load_ai_settings()

    api_key = str(
        current_settings.get("api_key", "")
    ).strip()

    return {
        "provider": current_settings["provider"],
        "base_url": current_settings["base_url"],
        "model": current_settings["model"],
        "timeout_seconds": current_settings[
            "timeout_seconds"
        ],
        "use_rag": current_settings["use_rag"],
        "api_key_configured": bool(api_key),
    }


def save_ai_settings(
    update: AISettingsUpdate,
) -> dict[str, Any]:
    """Save validated AI settings to the local JSON file."""

    current_settings = load_ai_settings()

    api_key = update.api_key

    if api_key is None or not api_key.strip():
        api_key = current_settings["api_key"]

    settings: dict[str, Any] = {
        "provider": update.provider.strip(),
        "base_url": normalize_base_url(
            update.base_url
        ),
        "model": update.model.strip(),
        "api_key": api_key.strip(),
        "timeout_seconds": update.timeout_seconds,
        "use_rag": update.use_rag,
    }

    if not settings["provider"]:
        raise ValueError(
            "The AI provider cannot be empty."
        )

    if not settings["model"]:
        raise ValueError(
            "The AI model name cannot be empty."
        )

    SETTINGS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = SETTINGS_FILE.with_suffix(
        ".json.tmp"
    )

    with temporary_file.open(
        "w",
        encoding="utf-8",
    ) as settings_file:
        json.dump(
            settings,
            settings_file,
            indent=2,
        )

        settings_file.write("\n")

    temporary_file.replace(SETTINGS_FILE)

    return public_ai_settings(settings)


def restore_default_ai_settings() -> dict[str, Any]:
    """Restore NOCPilot's original AI configuration."""

    default_update = AISettingsUpdate(
        **DEFAULT_AI_SETTINGS
    )

    return save_ai_settings(default_update)
