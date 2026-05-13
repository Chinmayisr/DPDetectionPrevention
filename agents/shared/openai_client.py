"""
agents/shared/openai_client.py
─────────────────────────────────────────────────────────────────
Async OpenAI GPT-4o wrapper with retry logic.
Supports both text completions and vision (image) completions.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI, APIConnectionError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    """
    Return a cached singleton AsyncOpenAI client.
    lru_cache ensures the client is created only once per process.
    timeout=120.0 to accommodate vision calls which take longer than text.
    """
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        max_retries=0,      # tenacity handles retries manually below
        timeout=120.0,
    )


# ── Retry policy (shared by all API call functions) ───────────
_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
)


# ── Text completion ───────────────────────────────────────────

@_retry
async def chat_complete_json(
    system_prompt: str,
    user_message: str,
    model: str = "gpt-4o",
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """
    Call GPT-4o with json_object response format.

    Always returns a parsed dict.
    Raises ValueError if the model returns non-JSON content.

    Args:
        system_prompt : Detailed instructions for the model
        user_message  : The content to analyse (pre-formatted text)
        model         : OpenAI model identifier (default gpt-4o)
        temperature   : 0.0 for deterministic detection results
        max_tokens    : Max response tokens (2048 sufficient for detection JSON)

    Returns:
        Parsed dict from the model's JSON response
    """
    client = get_openai_client()

    response = await client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    )

    raw = response.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"GPT-4o returned non-JSON: {raw[:300]}"
        ) from exc


# ── Vision completion ─────────────────────────────────────────

@_retry
async def chat_complete_vision_json(
    system_prompt: str,
    text_context: str,
    image_b64: str,
    image_media_type: str = "image/jpeg",
    model: str = "gpt-4o",
    temperature: float = 0.0,
    max_tokens: int = 3000,
) -> dict[str, Any]:
    """
    Call GPT-4o vision with a screenshot + structured text context.

    The message is multimodal — text context is sent first so the model
    reads the DOM signals before examining the image. This grounds visual
    analysis in the structural page data.

    Args:
        system_prompt    : Detailed visual detection instructions
        text_context     : Structured DOM data (signals, elements) as plain text
        image_b64        : Base64-encoded screenshot string (no data URI prefix)
        image_media_type : MIME type — "image/jpeg" (default) or "image/png"
        model            : Must be a vision-capable model — gpt-4o supports vision
        temperature      : 0.0 for deterministic detection
        max_tokens       : 3000 — vision responses are more verbose than text

    Returns:
        Parsed dict from the model's JSON response

    Raises:
        ValueError: if the model returns non-JSON content
    """
    client = get_openai_client()

    # Multimodal user message: text context first, screenshot second
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": text_context,
        },
        {
            "type": "image_url",
            "image_url": {
                "url":    f"data:{image_media_type};base64,{image_b64}",
                "detail": "high",   # high = full resolution tile analysis
            },
        },
    ]

    response = await client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
    )

    raw = response.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"GPT-4o vision returned non-JSON: {raw[:300]}"
        ) from exc