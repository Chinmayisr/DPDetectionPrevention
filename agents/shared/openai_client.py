"""
agents/shared/openai_client.py
Async OpenAI GPT-4o wrapper with retry logic.
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
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        max_retries=0,
        timeout=60.0,
    )


_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
)


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
    Always returns a parsed dict. Raises ValueError on parse failure.
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
        raise ValueError(f"GPT-4o returned non-JSON: {raw[:300]}") from exc