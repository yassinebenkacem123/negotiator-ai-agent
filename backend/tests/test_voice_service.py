import pytest

from app.models.voice import (
    CallOutcome,
    ElevenLabsCollectedData,
    NegotiationContext,
    P3CallOutcome,
)
from app.services.voice_service import (
    UnconfirmedJobSpecError,
    build_dynamic_variables,
    extract_collected_data,
    map_to_p3_quote_input,
)
from tests.conftest import make_company, make_spec


EXPECTED_VARIABLES = {
    "job_spec_id",
    "company_id",
    "company_name",
    "origin_address",
    "origin_floor",
    "origin_has_elevator",
    "destination_address",
    "destination_floor",
    "destination_has_elevator",
    "distance_miles",
    "move_date",
    "date_flexible",
    "num_trips",
    "num_bags",
    "notes",
    "source",
    "confirmed_by_user",
    "negotiation_mode",
    "competing_quote",
    "competing_company_name",
}


def test_builds_exact_dynamic_variables_and_formats_values() -> None:
    variables = build_dynamic_variables(
        make_spec(), make_company(), NegotiationContext()
    )
    payload = variables.model_dump()
    assert set(payload) == EXPECTED_VARIABLES
    assert payload["origin_floor"] == "4th floor"
    assert payload["destination_floor"] == "2nd floor"
    assert payload["move_date"] == "August 8, 2026"
    assert payload["origin_has_elevator"] == "no"
    assert payload["destination_has_elevator"] == "yes"
    assert payload["date_flexible"] == "yes"
    assert payload["confirmed_by_user"] == "true"
    assert payload["negotiation_mode"] == "false"
    assert payload["distance_miles"] == "214.7"
    assert payload["num_trips"] == "2"
    assert payload["num_bags"] == "18"


def test_floor_zero_is_ground_floor() -> None:
    variables = build_dynamic_variables(
        make_spec(origin_floor=0, destination_floor=0),
        make_company(),
        NegotiationContext(),
    )
    assert variables.origin_floor == "ground floor"
    assert variables.destination_floor == "ground floor"


def test_null_distance_notes_and_competing_values_use_safe_defaults() -> None:
    variables = build_dynamic_variables(
        make_spec(distance_miles=None, notes="  "),
        make_company(),
        NegotiationContext(),
    )
    assert variables.distance_miles == "unknown"
    assert variables.notes == "No additional notes were provided."
    assert variables.competing_quote == "none"
    assert variables.competing_company_name == "none"


def test_verified_competing_context_and_source_are_preserved() -> None:
    variables = build_dynamic_variables(
        make_spec(source="document_upload"),
        make_company(),
        NegotiationContext(
            negotiation_mode=True,
            competing_quote=1850,
            competing_company_name="Acme Movers",
        ),
    )
    assert variables.source == "document_upload"
    assert variables.negotiation_mode == "true"
    assert variables.competing_quote == "1850"
    assert variables.competing_company_name == "Acme Movers"


def test_coordinates_are_not_in_spoken_variables() -> None:
    payload = build_dynamic_variables(
        make_spec(), make_company(), NegotiationContext()
    ).model_dump()
    assert "origin_lat" not in payload
    assert "origin_lng" not in payload
    assert "destination_lat" not in payload
    assert "destination_lng" not in payload


def test_unconfirmed_spec_is_rejected() -> None:
    with pytest.raises(UnconfirmedJobSpecError):
        build_dynamic_variables(
            make_spec(confirmed_by_user=False),
            make_company(),
            NegotiationContext(),
        )


def test_extracts_complete_data_collection() -> None:
    payload = {
        "analysis": {
            "data_collection_results": {
                "company_name": {"value": "Fast Move Logistics"},
                "representative_name": {"value": "Alex"},
                "route_supported": {"value": "yes"},
                "move_date_available": {"value": True},
                "quote_type": {"value": "flat_rate"},
                "estimated_total": {"value": "$2,100"},
                "initial_price": {"value": "$2,000.00"},
                "negotiated_price": {"value": "$1,850"},
                "negotiation_successful": {"value": "false"},
                "additional_fees": {"value": {"fuel": "$50", "stairs": 30}},
                "differentiators": {"value": ["fully insured", "weekend availability"]},
                "deposit_required": {"value": "yes"},
                "deposit_amount": {"value": "$200"},
                "insurance_details": {"value": "Full valuation available"},
                "cancellation_policy": {"value": "48 hours"},
                "quote_validity": {"value": "7 days"},
                "callback_scheduled": {"value": "no"},
                "call_outcome": {"value": "quote"},
                "negotiation_style": {"value": "cooperative"},
            }
        }
    }
    result = extract_collected_data(payload)
    assert result.company_name == "Fast Move Logistics"
    assert result.route_supported is True
    assert result.estimated_total == 2100
    assert result.initial_price == 2000
    assert result.negotiated_price == 1850
    assert result.negotiation_successful is True
    assert result.fees == {"fuel": 50.0, "stairs": 30.0}
    assert result.differentiators == ["fully insured", "weekend availability"]
    assert result.deposit_required is True
    assert result.deposit_amount == 200
    assert result.call_outcome == CallOutcome.QUOTE


def test_missing_analysis_returns_safe_defaults() -> None:
    result = extract_collected_data({"conversation_id": "conv_1"})
    assert result.initial_price is None
    assert result.negotiated_price is None
    assert result.fees == {}
    assert result.differentiators == []
    assert result.call_outcome == CallOutcome.UNKNOWN


def test_malformed_prices_and_invalid_enums_normalize_safely() -> None:
    result = extract_collected_data(
        {
            "analysis": {
                "data_collection_results": {
                    "initial_price": {"value": "not discussed"},
                    "negotiated_price": {"value": {}},
                    "quote_type": {"value": "auction"},
                    "call_outcome": {"value": "maybe"},
                    "negotiation_style": {"value": "mysterious"},
                }
            }
        }
    )
    assert result.initial_price is None
    assert result.negotiated_price is None
    assert result.quote_type.value == "unknown"
    assert result.call_outcome.value == "unknown"
    assert result.negotiation_style.value == "unknown"


@pytest.mark.parametrize(
    ("fees", "expected"),
    [
        ([{"label": "fuel", "amount": "$40"}], {"fuel": 40.0}),
        ('{"stairs": "$25"}', {"stairs": 25.0}),
        ("fuel: $40; stairs: 25", {"fuel": 40.0, "stairs": 25.0}),
    ],
)
def test_normalizes_fee_variations(fees, expected) -> None:
    result = extract_collected_data(
        {"analysis": {"data_collection_results": {"additional_fees": {"value": fees}}}}
    )
    assert result.fees == expected


def test_normalizes_string_differentiators() -> None:
    result = extract_collected_data(
        {
            "analysis": {
                "data_collection_results": {
                    "differentiators": {"value": "insured; weekend availability"}
                }
            }
        }
    )
    assert result.differentiators == ["insured", "weekend availability"]


def test_maps_normalized_data_to_p3_without_red_flag_or_final_price() -> None:
    mapped = map_to_p3_quote_input(
        company_id="company_123",
        call_id="conv_123",
        collected_data=ElevenLabsCollectedData(
            initial_price=2000,
            negotiated_price=1850,
            negotiation_successful=False,
            fees={"fuel": 50.0},
            differentiators=["insured"],
            call_outcome=CallOutcome.QUOTE,
        ),
        transcript_url="http://test/transcript",
    )
    assert mapped.negotiation_successful is True
    assert mapped.outcome == P3CallOutcome.QUOTE
    assert mapped.red_flag is False
    assert "total" not in mapped.model_dump()
    assert "final_price" not in mapped.model_dump()


def test_callback_outcome_mapping() -> None:
    mapped = map_to_p3_quote_input(
        company_id="company_123",
        call_id="conv_123",
        collected_data=ElevenLabsCollectedData(callback_scheduled=True),
    )
    assert mapped.outcome == P3CallOutcome.CALLBACK_SCHEDULED
