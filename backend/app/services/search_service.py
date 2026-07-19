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
from urllib.parse import urlparse

from app.clients import openai_client, tavily_client
from app.config import settings
from app.models.lead import Lead

_PHONE_RE = re.compile(r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}")
_DIGITS_RE = re.compile(r"\D")


def _to_e164(phone: str) -> str:
    """Normalize a US phone number to E.164 format for Twilio.

    Inputs like '718-243-0221', '(347) 512-9972', '7189071830', '855-972-4089',
    '+1 718-243-0221' all become '+17182430221'.

    Toll-free numbers (800, 888, 877, 866, 855, 844, 833) are valid E.164
    and are kept — Twilio supports calling them.
    """
    digits = _DIGITS_RE.sub("", phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    # Already E.164 or international — return as-is
    return f"+{digits}" if not phone.startswith("+") else phone


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
IMPORTANT — Phone format: Return the phone number in E.164 format with the
+1 country code prefix (e.g. "+17182430221", not "718-243-0221"). If the page
shows a US number without the country code, add +1. For "24/7" or "24 hours"
service, use "24 hours" as the value for each day.
Omit any day from working_hours that isn't mentioned. If nothing is found for a
field, use null (or {} for working_hours) rather than guessing."""  # noqa: E501

_CITY_SYSTEM_PROMPT = """You extract the city and state/region from a street address.
Respond with JSON: {"city": "City, ST"}. Use just the city and state/region, no
street number, no zip code. If you cannot determine a city, respond {"city": null}."""  # noqa: E501

# Directory/aggregator/review sites — never the moving company itself, and
# calling their listed number would reach the platform, not a real mover.
_AGGREGATOR_DOMAINS = {
    "yelp.com",
    "thumbtack.com",
    "bbb.org",
    "angi.com",
    "homeadvisor.com",
    "google.com",
    "facebook.com",
    "nextdoor.com",
    "reddit.com",
    "tripadvisor.com",
    "mapquest.com",
    "manta.com",
    "yellowpages.com",
    "superpages.com",
    "porch.com",
    "moveline.com",
    "extraspace.com",
    "forbes.com",
}


def _domain(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_aggregator(url: str | None) -> bool:
    domain = _domain(url)
    return any(domain == d or domain.endswith(f".{d}") for d in _AGGREGATOR_DOMAINS)


def _normalize_phone(phone: str) -> str:
    """Digits only, for dedup comparison — '(704) 620-2154' == '704-620-2154'."""
    return _DIGITS_RE.sub("", phone)


def _extract_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text or "")
    return match.group(0) if match else None


def _normalize_website(value: str | None) -> str | None:
    """Ensure a website URL has a scheme (https://) for valid display."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


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
        # Discovery must not fail a lead just because profile extraction
        # hiccuped — callers fall back to regex phone + default hours below.
        return {}


def resolve_city(origin_address: str) -> str:
    """Detect 'City, ST' from a full street address the user already typed in
    the job spec — this is the only location input the pipeline needs; there
    is no separate city field or IP-based lookup.
    """
    try:
        raw = openai_client.complete_json(_CITY_SYSTEM_PROMPT, origin_address)
        parsed = json.loads(raw)
        city = _clean_text_field(parsed.get("city")) if isinstance(parsed, dict) else None
        if city:
            return city
    except Exception:
        pass
    # Fallback heuristic if the OpenAI call fails: US addresses are commonly
    # "street, city, ST zip" — the second-to-last comma segment is usually the city.
    parts = [p.strip() for p in origin_address.split(",") if p.strip()]
    if len(parts) >= 2:
        return ", ".join(parts[-2:])
    return origin_address


def find_movers(city: str) -> list[Lead]:
    """Search for residential movers in `city`, return cleaned, deduplicated Lead objects.

    Leads without a usable phone number are dropped — a company we can't call
    is not useful to the caller pipeline (see calls.py workflow). Aggregator/
    directory pages are skipped entirely. All phone numbers are normalized to
    E.164 (+1XXXXXXXXXX) so Twilio can place calls without reformatting.
    """
    query = settings.search_query_template.format(city=city)
    raw_results = tavily_client.raw_search(query, max_results=settings.max_companies_per_search)

    leads: list[Lead] = []
    seen_phones: set[str] = set()

    for result in raw_results:
        url = result.get("url")
        if _is_aggregator(url):
            continue

        # Prefer full page text (raw_content) over the short search snippet
        # (content) — contact details are more likely to actually appear there.
        text = result.get("raw_content") or result.get("content", "")
        profile = _extract_profile(text)

        raw_phone = profile.get("phone") or _extract_phone(text) or _extract_phone(result.get("title", ""))
        if not raw_phone:
            continue

        # Normalize to E.164 for Twilio compatibility
        phone = _to_e164(raw_phone)

        normalized_phone = _normalize_phone(phone)
        if normalized_phone in seen_phones:
            continue  # same company found under a different URL/result
        seen_phones.add(normalized_phone)

        raw_hours = profile.get("working_hours")
        clean_hours = (
            {day: value for day, value in raw_hours.items() if isinstance(value, str) and value}
            if isinstance(raw_hours, dict)
            else {}
        )
        hours = clean_hours or settings.default_working_hours

        website = _normalize_website(
            _clean_text_field(profile.get("website")) or url
        )

        leads.append(
            Lead(
                company_id=str(uuid.uuid4()),
                name=result.get("title", "Unknown Mover"),
                phone_number=phone,
                address=_clean_text_field(profile.get("address")),
                email=_clean_text_field(profile.get("email")),
                website=website,
                working_hours=hours if isinstance(hours, dict) else {},
                source_url=url,
                city=city,
            )
        )
    return leads


def find_movers_near(origin_address: str) -> list[Lead]:
    """Entry point matching the actual pipeline: user provides only their
    origin address (already collected in the job spec) — city detection and
    the search itself both happen here, nothing else is required upstream.
    """
    city = resolve_city(origin_address)
    return find_movers(city)