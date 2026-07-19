"""Stable P1 contracts for ElevenLabs call preparation and post-call results."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuoteType(str, Enum):
    HOURLY = "hourly"
    FLAT_RATE = "flat_rate"
    BINDING = "binding"
    NON_BINDING = "non_binding"
    RANGE = "range"
    UNKNOWN = "unknown"


class CallOutcome(str, Enum):
    QUOTE = "quote"
    CALLBACK_SCHEDULED = "callback_scheduled"
    DECLINED = "declined"
    NO_ANSWER = "no_answer"
    OUTSIDE_HOURS_SKIPPED = "outside_hours_skipped"
    UNKNOWN = "unknown"


class P3CallOutcome(str, Enum):
    QUOTE = "quote"
    CALLBACK_SCHEDULED = "callback_scheduled"
    DECLINED = "declined"
    NO_ANSWER = "no_answer"
    OUTSIDE_HOURS_SKIPPED = "outside_hours_skipped"


class NegotiationStyle(str, Enum):
    COOPERATIVE = "cooperative"
    STONEWALLER = "stonewaller"
    HARD_SELL = "hard_sell"
    UPSELLER = "upseller"
    TRANSPARENT = "transparent"
    UNKNOWN = "unknown"


class ConversationStatus(str, Enum):
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class WebhookEventType(str, Enum):
    POST_CALL_TRANSCRIPTION = "post_call_transcription"
    POST_CALL_AUDIO = "post_call_audio"
    CALL_INITIATION_FAILURE = "call_initiation_failure"


class StartCallPreparationRequest(BaseModel):
    job_spec_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    negotiation_mode: bool = False
    competing_quote: float | None = Field(default=None, ge=0)
    competing_company_name: str | None = None


class NegotiationContext(BaseModel):
    negotiation_mode: bool = False
    competing_quote: float | None = Field(default=None, ge=0)
    competing_company_name: str | None = None


class CallerDynamicVariables(BaseModel):
    job_spec_id: str
    company_id: str
    company_name: str
    origin_address: str
    origin_floor: str
    origin_has_elevator: str
    destination_address: str
    destination_floor: str
    destination_has_elevator: str
    distance_miles: str
    move_date: str
    date_flexible: str
    num_trips: str
    num_bags: str
    notes: str
    source: str
    confirmed_by_user: str
    negotiation_mode: str
    competing_quote: str
    competing_company_name: str


class PreparedOutboundCall(BaseModel):
    agent_id: str
    job_spec_id: str
    company_id: str
    company_name: str
    to_number: str
    dynamic_variables: CallerDynamicVariables


class ElevenLabsCollectedData(BaseModel):
    company_name: str | None = None
    representative_name: str | None = None
    route_supported: bool | None = None
    move_date_available: bool | None = None
    quote_type: QuoteType = QuoteType.UNKNOWN
    estimated_total: float | None = None
    initial_price: float | None = None
    negotiated_price: float | None = None
    negotiation_successful: bool = False
    fees: dict[str, float | str | bool | None] = Field(default_factory=dict)
    differentiators: list[str] = Field(default_factory=list)
    deposit_required: bool | None = None
    deposit_amount: float | None = None
    insurance_details: str | None = None
    cancellation_policy: str | None = None
    quote_validity: str | None = None
    callback_scheduled: bool = False
    call_outcome: CallOutcome = CallOutcome.UNKNOWN
    negotiation_style: NegotiationStyle = NegotiationStyle.UNKNOWN


class TranscriptTurn(BaseModel):
    role: str
    message: str | None = None
    time_in_call_secs: float | None = None


class ElevenLabsConversationResult(BaseModel):
    conversation_id: str
    status: ConversationStatus
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    call_duration_seconds: float | None = None
    analysis: dict[str, Any] = Field(default_factory=dict)
    recording_url: str | None = None
    collected_data: ElevenLabsCollectedData = Field(
        default_factory=ElevenLabsCollectedData
    )


class NormalizedCallResult(BaseModel):
    conversation_id: str
    call_id: str
    status: ConversationStatus
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    recording_url: str | None = None
    collected_data: ElevenLabsCollectedData = Field(
        default_factory=ElevenLabsCollectedData
    )


class P3QuoteInput(BaseModel):
    company_id: str
    call_id: str
    initial_price: float | None = None
    negotiated_price: float | None = None
    negotiation_successful: bool = False
    fees: dict[str, float | str | bool | None] = Field(default_factory=dict)
    differentiators: list[str] = Field(default_factory=list)
    outcome: P3CallOutcome
    transcript_url: str | None = None
    recording_url: str | None = None
    red_flag: bool = False


class PostCallWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: WebhookEventType
    data: dict[str, Any]
    event_timestamp: int | float | None = None


class StoredCallArtifact(BaseModel):
    call_id: str
    conversation_id: str
    job_spec_id: str | None = None
    company_id: str | None = None
    status: ConversationStatus = ConversationStatus.UNKNOWN
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    has_recording: bool = False


class WebhookProcessingResult(BaseModel):
    status: str
    event_type: WebhookEventType
    conversation_id: str
