"""SRP: Lead Discovery.

Takes a location, uses tavily_client to find moving companies, cleans the
raw search results into Lead objects, and extracts a structured profile
(phone, address, email, website, working hours) via a single OpenAI pass per
result — matching the discovery step of the search->call->negotiate pipeline.
Nothing here talks to Twilio or ElevenLabs.

Owned by P2; kept flexible (see Lead model) since P2's real implementation
isn't merged yet — this is a working default to build on, not a final cut.
"""

import json
import re
import uuid

from app.clients import openai_client, tavily_client
from app.config import settings
from app.models.lead import Lead

_PHONE_RE = re.compile(r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}")

_PROFILE_SYSTEM_PROMPT = """You extract a moving company's contact profile from web
page content. Only report fields that are actually present in the text — never
guess, infer, or invent a phone number, address, email, or website. Respond with
JSON matching this shape exactly:
{
  "phone": "string|null",
  "address": "string|null",
  "email": "string|null",
  "website": "string|null",
  "working_hours": {"mon": "08:00-18:00", "tue": "...", "...": "..."}
}
Omit any day from working_hours that isn't mentioned. If nothing is found for a
field, use null (or {} for working_hours) rather than guessing."""


def _extract_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text or "")
    return match.group(0) if match else None


def _clean_text_field(value) -> str | None:
    """Guard against LLM output artifacts like 'Charlotte, NC|null' — take the
    first non-empty, non-'null' segment rather than trusting the raw string."""
    if not isinstance(value, str):
        return None
    for part in value.split("|"):
        part = part.strip()
        if part and part.lower() != "null":
            return part
    return None


def _extract_profile(content: str) -> dict:
    if not content:
        return {}
    try:
        raw = openai_client.complete_json(_PROFILE_SYSTEM_PROMPT, content)
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        # Discovery must not fail a lead just because profile extraction hiccuped —
        # callers fall back to regex phone + default hours below.
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
        # (content) — contact details are more likely to actually appear there.
        text = result.get("raw_content") or result.get("content", "")
        profile = _extract_profile(text)

        phone = profile.get("phone") or _extract_phone(text) or _extract_phone(result.get("title", ""))
        if not phone:
            continue

        raw_hours = profile.get("working_hours")
        clean_hours = (
            {day: value for day, value in raw_hours.items() if isinstance(value, str) and value}
            if isinstance(raw_hours, dict)
            else {}
        )
        hours = clean_hours or settings.default_working_hours
        leads.append(
            Lead(
                company_id=str(uuid.uuid4()),
                name=result.get("title", "Unknown Mover"),
                phone_number=phone,
                address=_clean_text_field(profile.get("address")),
                email=_clean_text_field(profile.get("email")),
                website=_clean_text_field(profile.get("website")) or result.get("url"),
                working_hours=hours if isinstance(hours, dict) else {},
                source_url=result.get("url"),
                city=city,
            )
        )
    return leads
