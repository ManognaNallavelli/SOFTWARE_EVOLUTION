"""Gemini client for RAG answer generation (primary + one fallback model)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiChatError(Exception):
    def __init__(self, message: str, *, code: str = "gemini_chat_error") -> None:
        super().__init__(message)
        self.code = code


def _chat_models(settings: Settings) -> list[str]:
    primary = (settings.gemini_chat_model or "gemini-3.5-flash-lite").strip()
    fallback = (settings.gemini_chat_fallback_model or "gemini-3.1-flash-lite").strip()
    ordered: list[str] = []
    for name in (primary, fallback):
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _extract_text(body: dict[str, Any]) -> str:
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiChatError(
            "Unexpected Gemini chat response shape.",
            code="gemini_chat_invalid_response",
        ) from exc
    text = (text or "").strip()
    if not text:
        raise GeminiChatError("Gemini returned an empty chat response.", code="gemini_chat_empty")
    return text


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {404, 429, 503} or status_code >= 400


async def generate_chat_answer(
    *,
    settings: Settings,
    prompt: str,
) -> tuple[str, str]:
    """Generate a grounded chat answer. Returns (answer_text, model_used)."""
    api_key = settings.gemini_api_key.strip()
    if not api_key:
        raise GeminiChatError(
            "GEMINI_API_KEY is not configured.",
            code="gemini_not_configured",
        )

    models = _chat_models(settings)
    if not models:
        raise GeminiChatError("No Gemini chat model configured.", code="gemini_chat_no_model")

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024,
        },
    }

    last_error: GeminiChatError | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
        for index, model in enumerate(models):
            url = GEMINI_ENDPOINT.format(model=model)
            try:
                response = await client.post(url, params={"key": api_key}, json=payload)
            except httpx.TimeoutException as exc:
                last_error = GeminiChatError(
                    f"Gemini chat timed out for model '{model}'.",
                    code="gemini_chat_timeout",
                )
                logger.warning("Gemini chat timeout for %s: %s", model, exc)
                if index == 0 and len(models) > 1:
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = GeminiChatError(
                    f"Gemini chat request failed: {exc}",
                    code="gemini_chat_http_error",
                )
                logger.warning("Gemini chat HTTP error for %s: %s", model, exc)
                if index == 0 and len(models) > 1:
                    continue
                raise last_error from exc

            if _is_retryable_status(response.status_code) and response.status_code >= 400:
                detail = response.text[:400]
                last_error = GeminiChatError(
                    f"Gemini chat API returned {response.status_code} for '{model}'.",
                    code="gemini_chat_api_error",
                )
                logger.warning(
                    "Gemini chat API error for %s (%s): %s",
                    model,
                    response.status_code,
                    detail,
                )
                if index == 0 and len(models) > 1:
                    continue
                raise last_error

            try:
                body = response.json()
                answer = _extract_text(body)
            except GeminiChatError as exc:
                last_error = exc
                logger.warning("Gemini chat response parse failed for %s: %s", model, exc)
                if index == 0 and len(models) > 1:
                    continue
                raise

            if index > 0:
                logger.info("Gemini chat succeeded with fallback model %s", model)
            return answer, model

    raise last_error or GeminiChatError(
        "No Gemini chat model accepted the request.",
        code="gemini_chat_model_unavailable",
    )
