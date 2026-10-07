"""Gemini client for architecture generation via REST (httpx)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings
from app.schemas.architecture import ArchitectureGraph

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiArchitectureError(Exception):
    def __init__(self, message: str, *, code: str = "gemini_error") -> None:
        super().__init__(message)
        self.code = code


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise GeminiArchitectureError(
            "Gemini response did not contain JSON.",
            code="gemini_invalid_json",
        )
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise GeminiArchitectureError(
            "Gemini JSON root must be an object.",
            code="gemini_invalid_json",
        )
    return data


def _architecture_models(settings: Settings) -> list[str]:
    primary = (settings.gemini_model or "gemini-3.5-flash").strip()
    fallback = (settings.gemini_architecture_fallback_model or "gemini-3.1-flash-lite").strip()
    ordered: list[str] = []
    for name in (primary, fallback):
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {404, 429, 503} or status_code >= 400


async def generate_architecture_graph(
    *,
    prompt: str,
    settings: Settings,
) -> tuple[ArchitectureGraph, str]:
    api_key = settings.gemini_api_key.strip()
    if not api_key:
        raise GeminiArchitectureError(
            "GEMINI_API_KEY is not configured.",
            code="gemini_not_configured",
        )

    models = _architecture_models(settings)
    if not models:
        raise GeminiArchitectureError(
            "No Gemini architecture model configured.",
            code="gemini_no_model",
        )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    last_error: GeminiArchitectureError | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
        for index, model in enumerate(models):
            url = GEMINI_ENDPOINT.format(model=model)
            try:
                response = await client.post(url, params={"key": api_key}, json=payload)
            except httpx.TimeoutException as exc:
                last_error = GeminiArchitectureError(
                    f"Gemini timed out for model '{model}'.",
                    code="gemini_timeout",
                )
                logger.warning("Gemini architecture timeout for %s: %s", model, exc)
                if index == 0 and len(models) > 1:
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = GeminiArchitectureError(
                    f"Gemini request failed: {exc}",
                    code="gemini_http_error",
                )
                logger.warning("Gemini architecture HTTP error for %s: %s", model, exc)
                if index == 0 and len(models) > 1:
                    continue
                raise last_error from exc

            if _is_retryable_status(response.status_code) and response.status_code >= 400:
                detail = response.text[:500]
                last_error = GeminiArchitectureError(
                    f"Gemini API returned {response.status_code} for '{model}'.",
                    code="gemini_api_error",
                )
                logger.warning(
                    "Gemini architecture API error for %s (%s): %s",
                    model,
                    response.status_code,
                    detail,
                )
                if index == 0 and len(models) > 1:
                    continue
                raise last_error

            try:
                body = response.json()
                text = body["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError) as exc:
                last_error = GeminiArchitectureError(
                    "Unexpected Gemini response shape.",
                    code="gemini_invalid_response",
                )
                logger.warning("Gemini architecture response shape error for %s", model)
                if index == 0 and len(models) > 1:
                    continue
                raise last_error from exc

            try:
                raw = _extract_json_object(text)
                graph = ArchitectureGraph.model_validate(raw)
            except GeminiArchitectureError as exc:
                # Content/schema issues are not model-availability failures —
                # do not silently switch models; let the service fall back to deterministic.
                raise exc
            except Exception as exc:  # noqa: BLE001
                raise GeminiArchitectureError(
                    f"Gemini JSON failed schema validation: {exc}",
                    code="gemini_schema_mismatch",
                ) from exc

            if index > 0:
                logger.info("Gemini architecture succeeded with fallback model %s", model)
            return graph, model

    raise last_error or GeminiArchitectureError(
        "No Gemini model accepted the request.",
        code="gemini_model_unavailable",
    )
