"""Thin wrapper around the OpenAI API — no domain logic here.

Only responsibility: send a prompt (with optional JSON schema), return the raw
completion. Callers (extraction.py, ranking.py) own the prompt content and
interpret the response.
"""

from functools import lru_cache

from openai import OpenAI

from app.config import settings


@lru_cache
def _get_client() -> OpenAI:
    """Created lazily on first use, not at import time — so the app can boot
    even before this key is configured; it only fails when actually called."""
    return OpenAI(api_key=settings.openai_api_key)


def complete_json(system_prompt: str, user_prompt: str, model: str = "gpt-4o-mini") -> str:
    """Run a chat completion constrained to JSON output, return the raw JSON string."""
    response = _get_client().chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content
