"""SRP: Data Normalization.

After a call ends, takes the transcript and asks OpenAI to turn it into a
structured Quote (base price, fees, differentiators). Does not decide
ranking or red flags — that is ranking.py's job.
"""

import json

from app.clients import openai_client
from app.models.quote import Quote

_SYSTEM_PROMPT = """You extract structured pricing data from a residential moving
company phone call transcript. Only report numbers and claims that were
actually stated in the transcript — never infer or invent a price, fee, or
guarantee that wasn't said. Respond with JSON matching this shape:
{
  "initial_price": number|null,
  "negotiated_price": number|null,
  "negotiation_successful": boolean,
  "fees": {"fee_name": number, ...},
  "differentiators": ["string", ...],
  "outcome": "quote" | "callback_scheduled" | "declined" | "no_answer"
}"""


def extract_quote(company_id: str, call_id: str, transcript: str, recording_url: str | None = None) -> Quote:
    raw = openai_client.complete_json(_SYSTEM_PROMPT, transcript)
    parsed = json.loads(raw)
    return Quote(
        company_id=company_id,
        call_id=call_id,
        transcript_url=None,
        recording_url=recording_url,
        **parsed,
    )
