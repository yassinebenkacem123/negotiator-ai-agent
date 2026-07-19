"""P1 conversation contracts: call preparation and result normalization."""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.job_spec import JobSpec
from app.models.lead import Lead
from app.models.voice import (
    CallOutcome,
    CallerDynamicVariables,
    ConversationStatus,
    ElevenLabsCollectedData,
    ElevenLabsConversationResult,
    NegotiationContext,
    NegotiationStyle,
    P3CallOutcome,
    P3QuoteInput,
    PreparedOutboundCall,
    QuoteType,
    TranscriptTurn,
)

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_NUMERIC_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


class VoiceServiceError(Exception):
    pass


class UnconfirmedJobSpecError(VoiceServiceError):
    pass


class InvalidCompanyPhoneError(VoiceServiceError):
    pass


class InvalidJobSpecError(VoiceServiceError):
    pass


class MissingCallerAgentIdError(VoiceServiceError):
    pass


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _true_false(value: bool) -> str:
    return "true" if value else "false"


def _format_number(value: int | float | Decimal) -> str:
    number = Decimal(str(value))
    formatted = format(number, "f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix} floor"


def format_floor(value: int) -> str:
    if value == 0:
        return "ground floor"
    if value > 0:
        return _ordinal(value)
    return f"floor {value}"


def format_move_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidJobSpecError("move_date must be a valid ISO date") from exc
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def validate_e164(phone_number: str | None) -> str:
    candidate = (phone_number or "").strip()
    if not _E164_RE.fullmatch(candidate):
        raise InvalidCompanyPhoneError("company phone number must use E.164 format")
    return candidate


def build_dynamic_variables(
    job_spec: JobSpec,
    company: Lead,
    negotiation_context: NegotiationContext,
) -> CallerDynamicVariables:
    """Build the exact custom-variable contract configured on the caller agent."""

    if not job_spec.confirmed_by_user:
        raise UnconfirmedJobSpecError(
            "job_spec must be confirmed before call preparation"
        )

    competing_name = (
        negotiation_context.competing_company_name or ""
    ).strip() or "none"
    competing_quote = (
        _format_number(negotiation_context.competing_quote)
        if negotiation_context.competing_quote is not None
        else "none"
    )
    notes = (job_spec.notes or "").strip() or "No additional notes were provided."

    return CallerDynamicVariables(
        job_spec_id=job_spec.job_spec_id,
        company_id=company.company_id,
        company_name=company.name,
        origin_address=job_spec.origin_address,
        origin_floor=format_floor(job_spec.origin_floor),
        origin_has_elevator=_yes_no(job_spec.origin_has_elevator),
        destination_address=job_spec.destination_address,
        destination_floor=format_floor(job_spec.destination_floor),
        destination_has_elevator=_yes_no(job_spec.destination_has_elevator),
        distance_miles=(
            _format_number(job_spec.distance_miles)
            if job_spec.distance_miles is not None
            else "unknown"
        ),
        move_date=format_move_date(job_spec.move_date),
        date_flexible=_yes_no(job_spec.date_flexible),
        num_trips=str(job_spec.num_trips),
        num_bags=str(job_spec.num_bags),
        notes=notes,
        source=job_spec.source,
        confirmed_by_user=_true_false(job_spec.confirmed_by_user),
        negotiation_mode=_true_false(negotiation_context.negotiation_mode),
        competing_quote=competing_quote,
        competing_company_name=competing_name,
    )


def prepare_outbound_call(
    job_spec: JobSpec,
    company: Lead,
    negotiation_context: NegotiationContext,
    agent_id: str,
) -> PreparedOutboundCall:
    if not agent_id:
        raise MissingCallerAgentIdError("ELEVENLABS_CALLER_AGENT_ID is required")
    to_number = validate_e164(company.phone_number)
    dynamic_variables = build_dynamic_variables(job_spec, company, negotiation_context)
    return PreparedOutboundCall(
        agent_id=agent_id,
        job_spec_id=job_spec.job_spec_id,
        company_id=company.company_id,
        company_name=company.name,
        to_number=to_number,
        dynamic_variables=dynamic_variables,
    )


def _unwrap_collected_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "result_value", "result"):
            if key in value:
                return value[key]
    return value


def _collection_map(payload: dict[str, Any]) -> dict[str, Any]:
    raw_root = payload.get("data")
    root: dict[str, Any] = raw_root if isinstance(raw_root, dict) else payload
    raw_analysis = root.get("analysis")
    analysis: dict[str, Any] = raw_analysis if isinstance(raw_analysis, dict) else {}
    candidates = [
        analysis.get("data_collection_results"),
        analysis.get("data_collection"),
        analysis.get("data_collection_results_list"),
        root.get("data_collection_results"),
        root.get("collected_data"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return {
                key: _unwrap_collected_value(value) for key, value in candidate.items()
            }
        if isinstance(candidate, list):
            mapped: dict[str, Any] = {}
            for item in candidate:
                if not isinstance(item, dict):
                    continue
                identifier = (
                    item.get("data_collection_id") or item.get("id") or item.get("name")
                )
                if isinstance(identifier, str):
                    mapped[identifier] = _unwrap_collected_value(item)
            if mapped:
                return mapped
    return {}


def _text(value: Any) -> str | None:
    value = _unwrap_collected_value(value)
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _boolean(value: Any) -> bool | None:
    value = _unwrap_collected_value(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1"}:
            return True
        if normalized in {"false", "no", "n", "0"}:
            return False
    return None


def _price(value: Any) -> float | None:
    value = _unwrap_collected_value(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMERIC_RE.search(value.replace(" ", ""))
    if not match:
        return None
    try:
        return float(Decimal(match.group(0).replace(",", "")))
    except InvalidOperation:
        return None


def _enum_value(
    value: Any, enum_type: type[QuoteType] | type[CallOutcome] | type[NegotiationStyle]
):
    text = _text(value)
    if text is None:
        return enum_type("unknown")
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    try:
        return enum_type(normalized)
    except ValueError:
        return enum_type("unknown")


def _fees(value: Any) -> dict[str, float | str | bool | None]:
    value = _unwrap_collected_value(value)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            parsed: dict[str, float | str | bool | None] = {}
            for part in re.split(r"[;,]", value):
                if ":" not in part:
                    continue
                label, raw_amount = part.split(":", 1)
                label = label.strip()
                if label:
                    parsed[label] = (
                        _price(raw_amount)
                        if _price(raw_amount) is not None
                        else raw_amount.strip()
                    )
            return parsed
    if isinstance(value, dict):
        normalized: dict[str, float | str | bool | None] = {}
        for raw_label, raw_amount in value.items():
            label = str(raw_label).strip()
            amount = _unwrap_collected_value(raw_amount)
            if not label:
                continue
            numeric = _price(amount)
            if numeric is not None:
                normalized[label] = numeric
            elif isinstance(amount, (str, bool)) or amount is None:
                normalized[label] = (
                    amount.strip() if isinstance(amount, str) else amount
                )
        return normalized
    if isinstance(value, list):
        normalized = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            label = _text(item.get("label") or item.get("name") or item.get("fee"))
            if label:
                amount = next(
                    (item[key] for key in ("amount", "price", "value") if key in item),
                    None,
                )
                numeric = _price(amount)
                normalized[label] = (
                    numeric if numeric is not None else (_text(amount) or None)
                )
        return normalized
    return {}


def _string_list(value: Any) -> list[str]:
    value = _unwrap_collected_value(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                value = decoded
            else:
                raise json.JSONDecodeError("not a list", value, 0)
        except json.JSONDecodeError:
            value = re.split(r"[;,\n]", value)
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


def extract_collected_data(
    conversation_payload: dict[str, Any],
) -> ElevenLabsCollectedData:
    """Normalize current and known historical Data Collection response shapes."""

    data = _collection_map(conversation_payload)
    initial_price = _price(data.get("initial_price"))
    negotiated_price = _price(data.get("negotiated_price"))
    explicit_success = _boolean(data.get("negotiation_successful")) or False
    price_improved = (
        initial_price is not None
        and negotiated_price is not None
        and negotiated_price < initial_price
    )
    return ElevenLabsCollectedData(
        company_name=_text(data.get("company_name")),
        representative_name=_text(data.get("representative_name")),
        route_supported=_boolean(data.get("route_supported")),
        move_date_available=_boolean(data.get("move_date_available")),
        quote_type=_enum_value(data.get("quote_type"), QuoteType),
        estimated_total=_price(data.get("estimated_total")),
        initial_price=initial_price,
        negotiated_price=negotiated_price,
        negotiation_successful=explicit_success or price_improved,
        fees=_fees(data.get("additional_fees", data.get("fees"))),
        differentiators=_string_list(data.get("differentiators")),
        deposit_required=_boolean(data.get("deposit_required")),
        deposit_amount=_price(data.get("deposit_amount")),
        insurance_details=_text(data.get("insurance_details")),
        cancellation_policy=_text(data.get("cancellation_policy")),
        quote_validity=_text(data.get("quote_validity")),
        callback_scheduled=_boolean(data.get("callback_scheduled")) or False,
        call_outcome=_enum_value(data.get("call_outcome"), CallOutcome),
        negotiation_style=_enum_value(data.get("negotiation_style"), NegotiationStyle),
    )


def _normalize_status(value: Any) -> ConversationStatus:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"done": "completed", "ended": "completed", "inprogress": "in_progress"}
    normalized = aliases.get(normalized, normalized)
    try:
        return ConversationStatus(normalized)
    except ValueError:
        return ConversationStatus.UNKNOWN


def _transcript(value: Any) -> list[TranscriptTurn]:
    if not isinstance(value, list):
        return []
    turns: list[TranscriptTurn] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            continue
        time_value = item.get("time_in_call_secs")
        turns.append(
            TranscriptTurn(
                role=item["role"],
                message=item.get("message")
                if isinstance(item.get("message"), str)
                else None,
                time_in_call_secs=float(time_value)
                if isinstance(time_value, (int, float))
                else None,
            )
        )
    return turns


def normalize_conversation_result(
    payload: dict[str, Any],
    *,
    backend_public_url: str,
) -> ElevenLabsConversationResult:
    conversation_id = payload.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise InvalidJobSpecError("conversation payload is missing conversation_id")
    metadata_value = payload.get("metadata")
    raw_metadata: dict[str, Any] = (
        metadata_value if isinstance(metadata_value, dict) else {}
    )
    metadata: dict[str, Any] = {
        key: raw_metadata[key]
        for key in ("start_time_unix_secs", "call_duration_secs", "termination_reason")
        if key in raw_metadata
    }
    analysis_value = payload.get("analysis")
    raw_analysis: dict[str, Any] = (
        analysis_value if isinstance(analysis_value, dict) else {}
    )
    analysis: dict[str, Any] = {
        key: raw_analysis[key]
        for key in ("call_successful", "transcript_summary", "call_summary_title")
        if key in raw_analysis
    }
    duration = raw_metadata.get("call_duration_secs")
    has_audio = payload.get("has_audio") is True
    recording_url = (
        f"{backend_public_url.rstrip('/')}/api/results/calls/{conversation_id}/recording"
        if has_audio
        else None
    )
    return ElevenLabsConversationResult(
        conversation_id=conversation_id,
        status=_normalize_status(payload.get("status")),
        transcript=_transcript(payload.get("transcript")),
        metadata=metadata,
        call_duration_seconds=float(duration)
        if isinstance(duration, (int, float))
        else None,
        analysis=analysis,
        recording_url=recording_url,
        collected_data=extract_collected_data(payload),
    )


def _p3_outcome(collected: ElevenLabsCollectedData) -> P3CallOutcome:
    if collected.call_outcome != CallOutcome.UNKNOWN:
        return P3CallOutcome(collected.call_outcome.value)
    if collected.callback_scheduled:
        return P3CallOutcome.CALLBACK_SCHEDULED
    if collected.initial_price is not None or collected.negotiated_price is not None:
        return P3CallOutcome.QUOTE
    return P3CallOutcome.DECLINED


def map_to_p3_quote_input(
    *,
    company_id: str,
    call_id: str,
    collected_data: ElevenLabsCollectedData,
    transcript_url: str | None = None,
    recording_url: str | None = None,
) -> P3QuoteInput:
    """Prepare P3 input without ranking, total-price, or red-flag calculations."""

    success = collected_data.negotiation_successful or (
        collected_data.initial_price is not None
        and collected_data.negotiated_price is not None
        and collected_data.negotiated_price < collected_data.initial_price
    )
    return P3QuoteInput(
        company_id=company_id,
        call_id=call_id,
        initial_price=collected_data.initial_price,
        negotiated_price=collected_data.negotiated_price,
        negotiation_successful=success,
        fees=collected_data.fees,
        differentiators=collected_data.differentiators,
        outcome=_p3_outcome(collected_data),
        transcript_url=transcript_url,
        recording_url=recording_url,
        red_flag=False,
    )


def extract_dynamic_identifiers(
    payload: dict[str, Any],
) -> tuple[str | None, str | None]:
    raw_root = payload.get("data")
    root: dict[str, Any] = raw_root if isinstance(raw_root, dict) else payload
    client_data = root.get("conversation_initiation_client_data")
    if not isinstance(client_data, dict):
        return None, None
    override = client_data.get("conversation_config_override")
    override_variables = None
    if isinstance(override, dict):
        agent_override = override.get("agent")
        if isinstance(agent_override, dict):
            override_variables = agent_override.get("dynamic_variables")
    candidates = [
        client_data.get("dynamic_variables"),
        override_variables,
    ]
    for variables in candidates:
        if isinstance(variables, dict):
            job_spec_id = variables.get("job_spec_id")
            company_id = variables.get("company_id")
            return (
                job_spec_id if isinstance(job_spec_id, str) else None,
                company_id if isinstance(company_id, str) else None,
            )
    return None, None
