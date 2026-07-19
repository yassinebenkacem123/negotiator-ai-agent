"""SRP: Voice Intake Normalization.

Turns an Estimator-agent interview transcript into the same job-spec fields
the document and manual paths produce — the required voice interview intake
path per the challenge brief. This is the consuming side of the contract:
whatever produces the transcript (a real ElevenLabs Estimator agent, or a
transcript captured any other way) hands it here, unchanged in shape from
document_intake.py's approach. Only reports fields actually stated in the
transcript; never invents an address, date, or count that isn't there.
"""

import json
import logging

from app.clients import openai_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You extract residential-moving job details from a transcript
of a voice interview between an AI estimator and a customer. Only report a field
if it was actually stated in the conversation; use null for anything not
mentioned, never guess or infer. Respond with JSON matching this shape exactly:
{
  "origin_address": "string|null",
  "destination_address": "string|null",
  "origin_floor": "number|null",
  "origin_has_elevator": "boolean|null",
  "destination_floor": "number|null",
  "destination_has_elevator": "boolean|null",
  "move_date": "string|null (ISO format YYYY-MM-DD if a date is shown)",
  "date_flexible": "boolean|null",
  "num_trips": "number|null",
  "num_bags": "number|null (boxes/items count if mentioned)",
  "notes": "string|null (any other relevant details: large items, special requests)"
}"""


def extract_job_spec_fields(transcript: str) -> dict:
    """Best-effort field extraction — returns {} on any failure rather than
    raising, so a malformed transcript doesn't crash intake; the caller fills
    gaps with safe defaults and the user reviews/corrects before confirming."""
    try:
        raw = openai_client.complete_json(_SYSTEM_PROMPT, transcript)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            logger.warning("voice_intake: OpenAI response was not a JSON object: %r", raw)
            return {}
        return parsed
    except Exception:
        logger.exception("voice_intake: extraction failed")
        return {}
