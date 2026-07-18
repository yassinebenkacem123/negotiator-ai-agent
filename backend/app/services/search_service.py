"""SRP: Lead Discovery.

Takes a location, uses tavily_client to find moving companies, cleans the
raw search results into Lead objects, extracts phone numbers (regex), and
extracts working hours (LLM pass over the result content, since hours are
rarely in a consistent scrapeable format). Nothing here talks to Twilio or
ElevenLabs.
"""

import json
import re
import uuid

from app.clients import openai_client, tavily_client
from app.config import settings
from app.models.lead import Lead

_PHONE_RE = re.compile(r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}")

_HOURS_SYSTEM_PROMPT = """You extract a business's weekly working hours from web
search result content. Only report hours that are actually stated in the text
— never guess or assume standard hours. Respond with JSON:
{"mon": "08:00-18:00", "tue": "...", "wed": "...", "thu": "...", "fri": "...", "sat": "...", "sun": "..."}
Omit any day not mentioned in the text. If no hours are mentioned at all, respond with {}."""


def _extract_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text or "")
    return match.group(0) if match else None


def _extract_working_hours(content: str) -> dict:
    if not content:
        return {}
    try:
        raw = openai_client.complete_json(_HOURS_SYSTEM_PROMPT, content)
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        # Discovery must not fail a lead just because hours extraction hiccuped —
        # empty hours falls back to the working-hours gate's fail-safe (don't call).
        return {}


def find_movers(city: str) -> list[Lead]:
    """Search for residential movers in `city`, return cleaned Lead objects.

    Leads without a usable phone number are dropped — a company we can't call
    is not useful to the caller pipeline (see calls.py workflow).
    """
    query = settings.search_query_template.format(city=city)
    raw_results = tavily_client.raw_search(query, max_results=settings.max_companies_per_search)

    leads: list[Lead] = []
    for result in raw_results:
        # Prefer full page text (raw_content) over the short search snippet
        # (content) — hours/phone are more likely to actually appear there.
        text = result.get("raw_content") or result.get("content", "")
        phone = _extract_phone(text) or _extract_phone(result.get("title", ""))
        if not phone:
            continue
        hours = _extract_working_hours(text) or settings.default_working_hours
        leads.append(
            Lead(
                company_id=str(uuid.uuid4()),
                name=result.get("title", "Unknown Mover"),
                phone_number=phone,
                working_hours=hours,
                source_url=result.get("url"),
                city=city,
            )
        )
    return leads
