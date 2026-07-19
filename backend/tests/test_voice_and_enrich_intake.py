import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import document_intake, voice_intake

client = TestClient(app)


# --- voice_intake.extract_job_spec_fields -------------------------------------


def test_voice_extracts_fields_from_valid_response():
    payload = {"origin_address": "123 Main St", "num_bags": 24, "num_trips": 1}
    with patch.object(voice_intake.openai_client, "complete_json", return_value=json.dumps(payload)):
        fields = voice_intake.extract_job_spec_fields("some transcript")
    assert fields == payload


def test_voice_returns_empty_dict_on_failure():
    with patch.object(voice_intake.openai_client, "complete_json", side_effect=RuntimeError("boom")):
        fields = voice_intake.extract_job_spec_fields("some transcript")
    assert fields == {}


# --- POST /api/specs/from-voice ------------------------------------------------


def test_from_voice_builds_spec_with_transcript_stored():
    payload = {
        "origin_address": "6161 Brookshire Blvd, Charlotte, NC",
        "destination_address": "1425 Elm Street, Rock Hill, SC",
        "move_date": "2026-08-08",
        "num_trips": 1,
        "num_bags": 24,
        "origin_floor": 3,
        "origin_has_elevator": False,
    }
    transcript = "Agent: where from? Customer: Charlotte, NC..."
    with patch.object(voice_intake.openai_client, "complete_json", return_value=json.dumps(payload)):
        response = client.post("/api/specs/from-voice", json={"transcript": transcript})

    assert response.status_code == 200
    body = response.json()
    assert body["origin_address"] == payload["origin_address"]
    assert body["destination_address"] == payload["destination_address"]
    assert body["num_bags"] == 24
    assert body["origin_floor"] == 3
    assert body["source"] == "voice_interview"
    assert body["intake_transcript"] == transcript
    assert body["confirmed_by_user"] is False


def test_from_voice_uses_safe_defaults_when_nothing_extracted():
    with patch.object(voice_intake.openai_client, "complete_json", return_value="{}"):
        response = client.post("/api/specs/from-voice", json={"transcript": "..."})

    assert response.status_code == 200
    body = response.json()
    assert body["origin_address"] == ""
    assert body["num_trips"] == 1
    assert body["num_bags"] == 0
    assert body["source"] == "voice_interview"


# --- POST /api/specs/{id}/enrich-from-document ---------------------------------


def test_enrich_fills_gaps_without_overwriting_existing_values():
    with patch.object(voice_intake.openai_client, "complete_json", return_value="{}"):
        created = client.post("/api/specs/from-voice", json={"transcript": "..."}).json()
    job_spec_id = created["job_spec_id"]
    assert created["origin_address"] == ""  # nothing extracted from the voice call

    doc_fields = {"origin_address": "6161 Brookshire Blvd, Charlotte, NC", "notes": "Piano needs care."}
    with patch.object(document_intake.openai_client, "complete_json_from_image", return_value=json.dumps(doc_fields)):
        response = client.post(
            f"/api/specs/{job_spec_id}/enrich-from-document",
            files={"file": ("quote.png", b"fake-bytes", "image/png")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["origin_address"] == doc_fields["origin_address"]
    assert body["notes"] == doc_fields["notes"]


def test_enrich_does_not_overwrite_a_field_the_spec_already_has():
    voice_payload = {"origin_address": "Already Confirmed Address, NC"}
    with patch.object(voice_intake.openai_client, "complete_json", return_value=json.dumps(voice_payload)):
        created = client.post("/api/specs/from-voice", json={"transcript": "..."}).json()
    job_spec_id = created["job_spec_id"]
    assert created["origin_address"] == "Already Confirmed Address, NC"

    doc_fields = {"origin_address": "A Totally Different Address"}
    with patch.object(document_intake.openai_client, "complete_json_from_image", return_value=json.dumps(doc_fields)):
        response = client.post(
            f"/api/specs/{job_spec_id}/enrich-from-document",
            files={"file": ("quote.png", b"fake-bytes", "image/png")},
        )

    assert response.status_code == 200
    # origin_address was already set from voice -- the document must not clobber it
    assert response.json()["origin_address"] == "Already Confirmed Address, NC"


def test_enrich_appends_to_existing_notes_rather_than_replacing():
    with patch.object(voice_intake.openai_client, "complete_json", return_value=json.dumps({"notes": "Voice note."})):
        created = client.post("/api/specs/from-voice", json={"transcript": "..."}).json()
    job_spec_id = created["job_spec_id"]

    with patch.object(
        document_intake.openai_client,
        "complete_json_from_image",
        return_value=json.dumps({"notes": "Document note."}),
    ):
        response = client.post(
            f"/api/specs/{job_spec_id}/enrich-from-document",
            files={"file": ("quote.png", b"fake-bytes", "image/png")},
        )

    notes = response.json()["notes"]
    assert "Voice note." in notes
    assert "Document note." in notes


def test_enrich_returns_404_for_unknown_job_spec():
    response = client.post(
        "/api/specs/does-not-exist/enrich-from-document",
        files={"file": ("quote.png", b"fake-bytes", "image/png")},
    )
    assert response.status_code == 404


# --- PUT /api/specs/{id} (user corrections after review) -----------------------


def test_update_lets_user_correct_a_field():
    with patch.object(voice_intake.openai_client, "complete_json", return_value=json.dumps({"num_bags": 5})):
        created = client.post("/api/specs/from-voice", json={"transcript": "..."}).json()
    job_spec_id = created["job_spec_id"]
    assert created["num_bags"] == 5

    created["num_bags"] = 24  # user corrects a mistranscribed number
    created["origin_address"] = "Corrected Address, Charlotte, NC"
    response = client.put(f"/api/specs/{job_spec_id}", json=created)

    assert response.status_code == 200
    body = response.json()
    assert body["num_bags"] == 24
    assert body["origin_address"] == "Corrected Address, Charlotte, NC"
    assert body["job_spec_id"] == job_spec_id  # unchanged even if body tried to change it


def test_update_recomputes_distance_from_new_coordinates():
    with patch.object(voice_intake.openai_client, "complete_json", return_value="{}"):
        created = client.post("/api/specs/from-voice", json={"transcript": "..."}).json()
    job_spec_id = created["job_spec_id"]

    created["origin_lat"] = 34.9249
    created["origin_lng"] = -81.0251
    created["destination_lat"] = 35.2271
    created["destination_lng"] = -80.8431
    response = client.put(f"/api/specs/{job_spec_id}", json=created)

    assert response.status_code == 200
    assert response.json()["distance_miles"] == 23.3


def test_update_returns_404_for_unknown_job_spec():
    payload = {
        "origin_address": "a", "destination_address": "b", "move_date": "2026-08-08",
        "num_trips": 1, "num_bags": 1, "source": "voice_interview",
    }
    response = client.put("/api/specs/does-not-exist", json=payload)
    assert response.status_code == 404
